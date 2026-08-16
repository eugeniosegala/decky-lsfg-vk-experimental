"""
Flatpak service for managing lsfg-vk Flatpak runtime extensions.
"""

import subprocess
import os
import re
import unicodedata
import json
from dataclasses import replace
from pathlib import Path
from typing import Dict, Any, List, Literal, Optional

from .base_service import BaseService
from .config_schema import ConfigurationManager
from .constants import (
    BIN_DIR,
    FLATPAK_23_08_FILENAME,
    FLATPAK_24_08_FILENAME,
    FLATPAK_25_08_FILENAME,
    FLATPAK_EXTENSION_NAME,
    FLATPAK_IMPLICIT_LAYER_DIR,
    FLATPAK_OVERRIDE_OWNERSHIP_FILENAME,
)
from .state_transaction import (
    MutationBlockedError,
    MutationBusyError,
    MutationCoordinator,
    PathLayout,
    read_bytes_nofollow,
)
from .types import (
    BaseResponse,
    FlatpakObservedState,
    FlatpakOverrideOperation,
    FlatpakOverrideOperationResponse,
)


FLATPAK_DIAGNOSTIC_LIMIT = 512
FLATPAK_OVERRIDE_STEP = "apply_override"
FLATPAK_APP_ID_MAX_LENGTH = 255
FLATPAK_APP_ID_PATTERN = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._-]{{0,{FLATPAK_APP_ID_MAX_LENGTH - 1}}}\Z"
)
LEGACY_ENVIRONMENT_FIELDS = {
    "LSFGVK_CONFIG": "lsfg_config_env",
    "VK_IMPLICIT_LAYER_PATH": "vk_implicit_layer_path_env",
    "VK_ADD_IMPLICIT_LAYER_PATH": "vk_add_implicit_layer_path_env",
}
FLATPAK_OWNERSHIP_SCHEMA = 1
FLATPAK_OWNERSHIP_MAX_BYTES = 1024 * 1024
FLATPAK_FILESYSTEM_ROLES = ("config", "dll", "wrapper")
FLATPAK_MANAGED_MODES = {"config": "rw", "dll": "ro", "wrapper": "ro"}
FLATPAK_FILESYSTEM_MODES = frozenset(("ro", "rw", "create"))


class FlatpakExtensionStatus(BaseResponse):
    """Response for Flatpak extension status"""
    def __init__(self, success: bool = False, message: str = "", error: str = "", 
                 installed_23_08: bool = False, installed_24_08: bool = False, installed_25_08: bool = False):
        super().__init__(success, message, error)
        self.installed_23_08 = installed_23_08
        self.installed_24_08 = installed_24_08
        self.installed_25_08 = installed_25_08


class FlatpakAppInfo(BaseResponse):
    """Response for Flatpak app information"""
    def __init__(self, success: bool = False, message: str = "", error: str = "",
                 apps: List[Dict[str, Any]] = None, total_apps: int = 0):
        super().__init__(success, message, error)
        self.apps = apps or []
        self.total_apps = total_apps


class FlatpakService(BaseService):
    """Service for handling Flatpak runtime extensions and app overrides"""

    def __init__(self, logger=None):
        super().__init__(logger)
        self.extension_id_23_08 = f"{FLATPAK_EXTENSION_NAME}/x86_64/23.08"
        self.extension_id_24_08 = f"{FLATPAK_EXTENSION_NAME}/x86_64/24.08"
        self.extension_id_25_08 = f"{FLATPAK_EXTENSION_NAME}/x86_64/25.08"
        self.flatpak_command = None

    @property
    def _flatpak_ownership_path(self) -> Path:
        return self.config_dir / FLATPAK_OVERRIDE_OWNERSHIP_FILENAME

    def _flatpak_mutation_coordinator(self) -> MutationCoordinator:
        layout = PathLayout.from_home(self.user_home)
        layout = replace(
            layout,
            config_dir=self.config_dir,
            lock_file=self.config_dir / ".state-mutation.lock",
            journal_file=self.config_dir / ".state-transaction.json",
            flatpak_override_ownership=self._flatpak_ownership_path,
        )
        return MutationCoordinator(layout)

    def _load_flatpak_ownership(self) -> dict[str, Any]:
        """Load the strict ownership ledger without following a symlink."""
        path = self._flatpak_ownership_path
        try:
            content = read_bytes_nofollow(path)
        except FileNotFoundError:
            return {"schema": FLATPAK_OWNERSHIP_SCHEMA, "apps": {}}
        if len(content) > FLATPAK_OWNERSHIP_MAX_BYTES:
            raise MutationBlockedError("Flatpak ownership ledger is too large")
        try:
            document = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MutationBlockedError("Flatpak ownership ledger is corrupt") from error
        self._validate_flatpak_ownership_document(document)
        return document

    def _validate_flatpak_ownership_document(self, document: object) -> None:
        """Reject a ledger that this version could not safely recover later."""
        if (
            not isinstance(document, dict)
            or set(document) != {"schema", "apps"}
            or document["schema"] != FLATPAK_OWNERSHIP_SCHEMA
            or not isinstance(document["apps"], dict)
        ):
            raise MutationBlockedError("Flatpak ownership ledger has an unsupported schema")
        for app_id, record in document["apps"].items():
            self._validate_flatpak_ownership_record(app_id, record)

    def _validate_flatpak_ownership_record(self, app_id: object, record: object) -> None:
        if not isinstance(app_id, str) or not self._valid_app_id(app_id):
            raise MutationBlockedError("Flatpak ownership ledger contains an invalid app ID")
        if not isinstance(record, dict) or record.get("status") not in {
            "active", "baseline", "pending"
        }:
            raise MutationBlockedError("Flatpak ownership ledger contains an invalid record")
        if record["status"] == "pending":
            if (
                set(record) != {"status", "operation", "before", "after"}
                or record.get("operation") not in {"set", "remove"}
            ):
                raise MutationBlockedError("Flatpak ownership ledger contains an invalid intent")
            for boundary in (record["before"], record["after"]):
                if boundary is not None:
                    self._validate_flatpak_active_record(boundary)
            self._validate_flatpak_pending_transition(record)
            return
        self._validate_flatpak_active_record(record)

    @staticmethod
    def _validate_flatpak_active_record(record: object) -> None:
        if (
            not isinstance(record, dict)
            or set(record) != {"status", "paths", "retired_paths"}
            or record.get("status") not in {"active", "baseline"}
            or not isinstance(record.get("paths"), dict)
            or not isinstance(record.get("retired_paths"), list)
        ):
            raise MutationBlockedError("Flatpak ownership ledger contains an invalid record")
        paths = record["paths"]
        if set(paths) != set(FLATPAK_FILESYSTEM_ROLES):
            raise MutationBlockedError("Flatpak ownership ledger contains an incomplete path set")
        for role, entry in paths.items():
            if not isinstance(entry, dict) or set(entry) != {"path", "owned", "present"}:
                raise MutationBlockedError("Flatpak ownership ledger contains an invalid path")
            path, owned, present = entry["path"], entry["owned"], entry["present"]
            if (
                role not in FLATPAK_FILESYSTEM_ROLES
                or not isinstance(path, str)
                or not Path(path).is_absolute()
                or not isinstance(owned, bool)
                or not isinstance(present, bool)
                or (owned and not present)
            ):
                raise MutationBlockedError("Flatpak ownership ledger contains an invalid path")
        if len({entry["path"] for entry in paths.values()}) != len(paths):
            raise MutationBlockedError(
                "Flatpak ownership ledger contains overlapping managed paths"
            )
        if record["status"] == "active" and not all(
            entry["present"] for entry in paths.values()
        ):
            raise MutationBlockedError(
                "Flatpak active ownership state contains an absent path"
            )
        if record["status"] == "active" and (
            record["retired_paths"]
            or not all(entry["owned"] for entry in paths.values())
        ):
            raise MutationBlockedError(
                "Flatpak active ownership state is not exclusive"
            )
        if record["status"] == "baseline" and any(
            entry["owned"] for entry in paths.values()
        ):
            raise MutationBlockedError(
                "Flatpak baseline ownership state claims plugin-owned access"
            )
        if any(
            not isinstance(path, str) or not Path(path).is_absolute()
            for path in record["retired_paths"]
        ) or len(set(record["retired_paths"])) != len(record["retired_paths"]):
            raise MutationBlockedError("Flatpak ownership ledger contains invalid history")
        active_paths = {entry["path"] for entry in paths.values()}
        if active_paths.intersection(record["retired_paths"]):
            raise MutationBlockedError(
                "Flatpak ownership ledger has active paths in retired history"
            )

    @staticmethod
    def _validate_flatpak_pending_transition(record: dict[str, Any]) -> None:
        """Accept only transitions emitted by set/remove ownership planning."""
        operation = record["operation"]
        before, after = record["before"], record["after"]
        if operation == "remove":
            if (
                before is None
                or before["status"] != "active"
                or after is not None
            ):
                raise MutationBlockedError(
                    "Flatpak ownership ledger contains an invalid remove intent"
                )
            if before["retired_paths"] or not all(
                entry["owned"] for entry in before["paths"].values()
            ):
                raise MutationBlockedError(
                    "Flatpak ownership ledger contains an unsafe remove transition"
                )
            return

        if after is None or after["status"] != "active" or (
            before is not None and before["status"] not in {"active", "baseline"}
        ):
            raise MutationBlockedError(
                "Flatpak ownership ledger contains an invalid set intent"
            )
        if before is None:
            if after["retired_paths"] or not all(
                entry["owned"] for entry in after["paths"].values()
            ):
                raise MutationBlockedError(
                    "Flatpak initial ownership intent is not exclusive"
                )
            return

        if before["status"] != "active" or before != after:
            raise MutationBlockedError(
                "Flatpak set intent must not replace an active ownership boundary"
            )

    def _write_flatpak_ownership(
        self, coordinator: MutationCoordinator, document: dict[str, Any]
    ) -> None:
        self._validate_flatpak_ownership_document(document)
        content = (
            json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode("utf-8")
        if len(content) > FLATPAK_OWNERSHIP_MAX_BYTES:
            raise MutationBlockedError("Flatpak ownership ledger is too large")
        result = coordinator.commit(
            "flatpak", {self._flatpak_ownership_path: (content, 0o600)}, []
        )
        if result.refresh_required:
            raise MutationBlockedError(
                "recovered another state transaction; retry the Flatpak operation"
            )

    def _remove_flatpak_ownership(
        self, coordinator: MutationCoordinator, document: dict[str, Any], app_id: str
    ) -> None:
        document["apps"].pop(app_id, None)
        if document["apps"]:
            self._write_flatpak_ownership(coordinator, document)
        else:
            result = coordinator.commit("flatpak", {}, [self._flatpak_ownership_path])
            if result.refresh_required:
                raise MutationBlockedError(
                    "recovered another state transaction; retry the Flatpak operation"
                )

    def _get_lsfg_paths(self) -> tuple[str, str]:
        """Return the config directory and read-only directory containing Lossless.dll.

        Upstream's Flatpak guide grants the Steam common directory so the sandbox can
        load Lossless Scaling. If the user selected a custom DLL path, grant that
        DLL's directory instead.
        """
        config_path = str(self.config_dir)
        dll_directory = str(
            self.user_home / ".local/share/Steam/steamapps/common"
        )
        try:
            config_content = read_bytes_nofollow(self.config_file_path).decode("utf-8")
        except FileNotFoundError:
            return config_path, dll_directory

        try:
            profile_data = ConfigurationManager.parse_toml_content_multi_profile(
                config_content
            )
        except Exception as error:
            raise MutationBlockedError(
                "The persisted LSFG configuration could not be parsed safely"
            ) from error

        configured_dll = str(profile_data["global_config"].get("dll", "")).strip()
        if configured_dll:
            configured_path = Path(configured_dll)
            if "\x00" in configured_dll or not configured_path.is_absolute():
                raise MutationBlockedError(
                    "The configured Lossless.dll path must be absolute"
                )
            configured_path = Path(os.path.normpath(str(configured_path)))
            if configured_path.parent == Path("/"):
                raise MutationBlockedError(
                    "The configured Lossless.dll path would grant filesystem root access"
                )
            dll_directory = str(configured_path.parent)

        return config_path, dll_directory

    def _get_clean_env(self):
        """Get a clean environment without PyInstaller's bundled libraries"""
        env = os.environ.copy()

        if 'LD_LIBRARY_PATH' in env:
            del env['LD_LIBRARY_PATH']

        standard_paths = ['/usr/bin', '/usr/local/bin', '/bin']
        current_path = env.get('PATH', '')

        path_parts = current_path.split(':') if current_path else []
        for std_path in standard_paths:
            if std_path not in path_parts:
                path_parts.insert(0, std_path)

        env['PATH'] = ':'.join(path_parts)

        return env

    def _get_extension_id(self, version: str) -> Optional[str]:
        """Return the isolated experimental extension reference for a runtime."""
        extension_ids = {
            "23.08": self.extension_id_23_08,
            "24.08": self.extension_id_24_08,
            "25.08": self.extension_id_25_08,
        }
        return extension_ids.get(version)

    def _get_app_runtime_version(self, app_id: str) -> Optional[str]:
        """Return a supported Flatpak runtime branch for an application."""
        result = self._run_flatpak_command(
            ["info", "--show-runtime", app_id],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None

        runtime = result.stdout.strip()
        for version in ("23.08", "24.08", "25.08"):
            if runtime.endswith(f"/{version}") or runtime.endswith(f"//{version}"):
                return version
        return None

    def _is_extension_installed(self, version: str) -> bool:
        """Check whether the isolated experimental extension is installed."""
        extension_id = self._get_extension_id(version)
        if extension_id is None:
            return False
        result = self._run_flatpak_command(
            ["info", "--user", extension_id],
            capture_output=True, text=True
        )
        return result.returncode == 0

    def _run_flatpak_command(self, args: List[str], **kwargs):
        """Run flatpak command with clean environment to avoid library conflicts"""
        if self.flatpak_command is None:
            raise FileNotFoundError("Flatpak command not available")

        env = self._get_clean_env()

        self.log.info(f"Running flatpak with PATH: {env.get('PATH')}")
        self.log.info(f"LD_LIBRARY_PATH removed: {'LD_LIBRARY_PATH' not in env}")

        return subprocess.run([self.flatpak_command] + args, env=env, **kwargs)

    def check_flatpak_available(self) -> bool:
        """Check if flatpak command is available and store the working command"""
        self.log.info(f"PATH: {os.environ.get('PATH', 'Not set')}")
        self.log.info(f"HOME: {os.environ.get('HOME', 'Not set')}")
        self.log.info(f"USER: {os.environ.get('USER', 'Not set')}")

        flatpak_paths = [
            "flatpak",
            "/usr/bin/flatpak",
            "/var/lib/flatpak/exports/bin/flatpak",
            "/home/deck/.local/bin/flatpak"
        ]

        for flatpak_path in flatpak_paths:
            try:
                result = subprocess.run([flatpak_path, "--version"], 
                                      capture_output=True, check=True, text=True,
                                      env=self._get_clean_env())
                self.log.info(f"Flatpak found at {flatpak_path}: {result.stdout.strip()}")
                self.flatpak_command = flatpak_path
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                self.log.debug(f"Flatpak not found at {flatpak_path}")
                continue

        self.log.error("Flatpak command not found in any known locations")
        self.flatpak_command = None
        return False

    def get_extension_status(self) -> FlatpakExtensionStatus:
        """Check if lsfg-vk Flatpak extensions are installed"""
        try:
            if not self.check_flatpak_available():
                error_msg = "Flatpak is not available on this system"
                if self.flatpak_command is None:
                    error_msg += ". Command not found in PATH or common install locations."
                self.log.error(error_msg)
                return self._error_response(FlatpakExtensionStatus, 
                                          error_msg,
                                          installed_23_08=False, installed_24_08=False, installed_25_08=False)

            result = self._run_flatpak_command(
                ["list", "--runtime"],
                capture_output=True, text=True, check=True
            )

            installed_runtimes = result.stdout

            base_extension_name = FLATPAK_EXTENSION_NAME
            installed_23_08 = False
            installed_24_08 = False
            installed_25_08 = False

            for line in installed_runtimes.split('\n'):
                if base_extension_name in line:
                    if "23.08" in line:
                        installed_23_08 = True
                    elif "24.08" in line:
                        installed_24_08 = True
                    elif "25.08" in line:
                        installed_25_08 = True

            status_msg = []
            if installed_23_08:
                status_msg.append("23.08 runtime extension installed")
            if installed_24_08:
                status_msg.append("24.08 runtime extension installed")
            if installed_25_08:
                status_msg.append("25.08 runtime extension installed")

            if not status_msg:
                status_msg.append("No experimental lsfg-vk runtime extensions installed")

            return self._success_response(FlatpakExtensionStatus,
                                        "; ".join(status_msg),
                                        installed_23_08=installed_23_08,
                                        installed_24_08=installed_24_08,
                                        installed_25_08=installed_25_08)

        except subprocess.CalledProcessError as e:
            error_msg = f"Error checking Flatpak extensions: {e.stderr if e.stderr else str(e)}"
            self.log.error(error_msg)
            return self._error_response(FlatpakExtensionStatus, error_msg,
                                      installed_23_08=False, installed_24_08=False, installed_25_08=False)

    def install_extension(self, version: str) -> BaseResponse:
        """Install or refresh a specific lsfg-vk Flatpak runtime extension."""
        try:
            if version not in ["23.08", "24.08", "25.08"]:
                return self._error_response(BaseResponse, "Invalid version. Must be '23.08', '24.08', or '25.08'")

            if not self.check_flatpak_available():
                return self._error_response(BaseResponse, "Flatpak is not available on this system")

            plugin_dir = Path(__file__).parent.parent.parent
            filenames = {
                "23.08": FLATPAK_23_08_FILENAME,
                "24.08": FLATPAK_24_08_FILENAME,
                "25.08": FLATPAK_25_08_FILENAME,
            }
            flatpak_path = plugin_dir / BIN_DIR / filenames[version]

            if not flatpak_path.is_file():
                return self._error_response(
                    BaseResponse,
                    "Experimental Flatpak bundle is missing from this plugin package. "
                    "Install a release that includes Flatpak support.",
                )

            was_installed = self._is_extension_installed(version)
            install_args = ["install", "--user", "--noninteractive"]
            if was_installed:
                # The plugin ZIP can carry a newer engine with the same Flatpak
                # extension ID/runtime branch. Reinstall in place so Heroic's
                # preparation and its per-game wrapper commands remain intact.
                install_args.append("--reinstall")
            install_args.append(str(flatpak_path))
            result = self._run_flatpak_command(
                install_args,
                capture_output=True, text=True
            )

            if result.returncode != 0:
                error_msg = f"Failed to install Flatpak extension: {result.stderr}"
                self.log.error(error_msg)
                return self._error_response(BaseResponse, error_msg)

            action = "updated" if was_installed else "installed"
            self.log.info(f"Successfully {action} experimental lsfg-vk Flatpak extension {version}")
            return self._success_response(
                BaseResponse,
                f"Experimental lsfg-vk {version} runtime extension {action} successfully"
            )

        except Exception as e:
            error_msg = f"Error installing Flatpak extension {version}: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(BaseResponse, error_msg)

    def uninstall_extension(self, version: str) -> BaseResponse:
        """Uninstall a specific version of the lsfg-vk Flatpak extension"""
        try:
            if version not in ["23.08", "24.08", "25.08"]:
                return self._error_response(BaseResponse, "Invalid version. Must be '23.08', '24.08', or '25.08'")

            if not self.check_flatpak_available():
                return self._error_response(BaseResponse, "Flatpak is not available on this system")

            extension_id = self._get_extension_id(version)
            if extension_id is None:
                return self._error_response(BaseResponse, f"Unsupported Flatpak runtime: {version}")

            result = self._run_flatpak_command(
                ["uninstall", "--user", "--noninteractive", extension_id],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                error_msg = f"Failed to uninstall Flatpak extension: {result.stderr}"
                self.log.error(error_msg)
                return self._error_response(BaseResponse, error_msg)

            self.log.info(f"Successfully uninstalled lsfg-vk Flatpak extension {version}")
            return self._success_response(BaseResponse, f"lsfg-vk {version} runtime extension uninstalled successfully")

        except Exception as e:
            error_msg = f"Error uninstalling Flatpak extension {version}: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(BaseResponse, error_msg)

    def get_flatpak_apps(self) -> FlatpakAppInfo:
        """Get list of installed Flatpak apps and their lsfg-vk override status"""
        try:
            if not self.check_flatpak_available():
                error_msg = "Flatpak is not available on this system"
                if self.flatpak_command is None:
                    error_msg += ". Command not found in PATH or common install locations."
                return self._error_response(FlatpakAppInfo, 
                                          error_msg,
                                          apps=[], total_apps=0)

            result = self._run_flatpak_command(
                ["list", "--app"],
                capture_output=True, text=True, check=True
            )

            try:
                ownership = self._load_flatpak_ownership()
                ownership_blocked = False
            except MutationBlockedError:
                ownership = {"schema": FLATPAK_OWNERSHIP_SCHEMA, "apps": {}}
                ownership_blocked = True

            apps = []
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue

                parts = line.split('\t')
                if len(parts) >= 2:
                    app_name = parts[0].strip()
                    app_id = parts[1].strip()

                    observation, observation_error, exact_states = (
                        self._observe_app_override_snapshot(app_id)
                    )
                    app = {
                        "app_id": app_id,
                        "app_name": app_name,
                        "wrapper_path": str(self.lsfg_launch_script_path),
                    }
                    if observation is None:
                        app.update({
                            "status_available": False,
                            "status_error_code": "status_unavailable",
                            "status_error": observation_error,
                        })
                    else:
                        app.update(observation)
                        record = ownership["apps"].get(app_id)
                        ownership_status = (
                            "blocked"
                            if ownership_blocked
                            else self._flatpak_ownership_status(
                                app_id, observation, ownership, exact_states
                            )
                        )
                        app.update({
                            "status_available": True,
                            "has_filesystem_override": (
                                observation["config_filesystem_ready"]
                                and observation["dll_filesystem_ready"]
                            ),
                            "has_wrapper_override": observation["wrapper_filesystem_ready"],
                            "has_env_override": any(
                                observation[field]
                                for field in LEGACY_ENVIRONMENT_FIELDS.values()
                            ),
                            "ownership_status": ownership_status,
                        })
                        if ownership_status == "pending" and record is not None:
                            app.update({
                                "ownership_operation": record["operation"],
                                "ownership_error_code": "ownership_pending",
                            })
                        elif ownership_status == "blocked":
                            app["ownership_error_code"] = "ownership_blocked"
                    apps.append(app)

            return self._success_response(FlatpakAppInfo,
                                        f"Found {len(apps)} Flatpak applications",
                                        apps=apps, total_apps=len(apps))

        except Exception as e:
            detail = e.stderr if isinstance(e, subprocess.CalledProcessError) and e.stderr else e
            error_msg = self._sanitize_flatpak_detail(
                f"Error getting Flatpak apps: {detail}"
            )
            self.log.error(error_msg)
            return self._error_response(FlatpakAppInfo, error_msg, apps=[], total_apps=0)

    def _observe_app_override_status(
        self, app_id: str
    ) -> tuple[Optional[FlatpakObservedState], Optional[str]]:
        """Strictly observe the override state without inventing an all-false result."""
        observed, error, _modes = self._observe_app_override_snapshot(app_id)
        return observed, error

    def _observe_app_override_snapshot(
        self, app_id: str
    ) -> tuple[Optional[FlatpakObservedState], Optional[str], dict[str, str]]:
        """Observe the public state plus exact effective modes used by ownership."""
        if not self._valid_app_id(app_id):
            return None, "Invalid Flatpak application identifier.", {}
        try:
            result = self._run_flatpak_command(
                ["override", "--user", "--show", app_id],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                detail = self._sanitize_flatpak_detail(result.stderr or result.stdout)
                return None, detail or "Flatpak could not read the application overrides.", {}

            output = result.stdout
            config_path, dll_directory = self._get_lsfg_paths()
            wrapper_path = str(self.lsfg_launch_script_path)

            filesystem_section = ""
            in_context = False
            
            for line in output.split('\n'):
                line = line.strip()
                if line == "[Context]":
                    in_context = True
                elif line.startswith("[") and line != "[Context]":
                    in_context = False
                elif in_context and line.startswith("filesystems="):
                    filesystem_section = line
                    break
            
            has_config_fs, config_fs_ready = self._filesystem_override_state(
                filesystem_section, config_path, "rw"
            )
            has_dll_fs, dll_fs_ready = self._filesystem_override_state(
                filesystem_section, dll_directory, "ro"
            )
            has_wrapper_fs, wrapper_fs_ready = self._filesystem_override_state(
                filesystem_section, wrapper_path, "ro"
            )

            environment_state = {
                field: False for field in LEGACY_ENVIRONMENT_FIELDS.values()
            }
            expected_environment = {
                "LSFGVK_CONFIG": f"{config_path}/conf.toml",
                "VK_IMPLICIT_LAYER_PATH": FLATPAK_IMPLICIT_LAYER_DIR,
                "VK_ADD_IMPLICIT_LAYER_PATH": FLATPAK_IMPLICIT_LAYER_DIR,
            }
            in_environment = False
            
            for line in output.split('\n'):
                line = line.strip()
                if line == "[Environment]":
                    in_environment = True
                elif line.startswith("[") and line != "[Environment]":
                    in_environment = False
                elif in_environment:
                    variable, separator, value = line.partition("=")
                    if separator and variable in LEGACY_ENVIRONMENT_FIELDS:
                        # ``--unset-env`` is represented separately in Context.
                        # Only plugin-owned legacy values are safe to neutralize;
                        # unrelated user values must be preserved.
                        environment_state[LEGACY_ENVIRONMENT_FIELDS[variable]] = (
                            value == expected_environment[variable]
                        )

            self.log.debug(
                "Override status for %s: config=%s dll=%s wrapper=%s legacy_env=%s",
                app_id,
                has_config_fs,
                has_dll_fs,
                has_wrapper_fs,
                environment_state,
            )

            observed: FlatpakObservedState = {
                "config_filesystem": has_config_fs,
                "dll_filesystem": has_dll_fs,
                "wrapper_filesystem": has_wrapper_fs,
                "config_filesystem_ready": config_fs_ready,
                "dll_filesystem_ready": dll_fs_ready,
                "wrapper_filesystem_ready": wrapper_fs_ready,
                **environment_state,
            }
            return observed, None, self._parse_override_exact_states(
                output, filesystem_section
            )

        except Exception as e:
            detail = self._sanitize_flatpak_detail(e)
            self.log.error("Error checking override status for %s: %s", app_id, detail)
            return None, detail or "Flatpak override status is unavailable.", {}

    def _parse_override_exact_states(
        self, output: str, filesystem_section: str
    ) -> dict[str, str]:
        """Return exact app-layer grant/deny and legacy-environment states."""
        states: dict[str, str] = {}
        _, _, raw_entries = filesystem_section.partition("=")
        denied_paths: set[str] = set()
        for raw_entry in raw_entries.split(";"):
            entry = raw_entry.strip()
            if not entry:
                continue
            denied = entry.startswith("!")
            permission = entry[1:] if denied else entry
            permission_path, separator, mode = permission.rpartition(":")
            if not separator or mode not in FLATPAK_FILESYSTEM_MODES:
                permission_path, mode = permission, "rw"
            if permission_path.startswith("~/"):
                permission_path = str(self.user_home / permission_path[2:])
            if denied:
                denied_paths.add(permission_path)
                states[permission_path] = "deny"
            elif permission_path not in denied_paths:
                states[permission_path] = f"grant_{mode}"
        in_environment = False
        in_context = False
        section = ""
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line == "[Environment]":
                section = "Environment"
                in_environment, in_context = True, False
            elif line == "[Context]":
                section = "Context"
                in_environment, in_context = False, True
            elif line.startswith("["):
                section = line
                in_environment = in_context = False
            elif in_environment:
                variable, separator, _value = line.partition("=")
                if separator:
                    states[f"@env:{variable}"] = "value"
            elif in_context and line.startswith("unset-environment="):
                for variable in line.partition("=")[2].split(";"):
                    if variable:
                        states[f"@env:{variable}"] = "unset"
            elif in_context and line.startswith("filesystems="):
                continue
            elif in_context and line and not line.startswith("filesystems="):
                key = line.partition("=")[0]
                states[f"@other:Context:{key}"] = "present"
            elif line and "=" in line:
                key = line.partition("=")[0]
                states[f"@other:{section}:{key}"] = "present"
        return states

    @staticmethod
    def _sanitize_flatpak_detail(value: object) -> str:
        """Return bounded single-line diagnostic text safe for the local UI/log."""
        printable = "".join(
            " " if unicodedata.category(character) in {"Cc", "Cf", "Cs"} else character
            for character in str(value or "")
        )
        normalized = " ".join(printable.split())
        if len(normalized) <= FLATPAK_DIAGNOSTIC_LIMIT:
            return normalized
        return f"{normalized[:FLATPAK_DIAGNOSTIC_LIMIT - 1]}…"

    def _filesystem_override_state(
        self, filesystem_section: str, host_path: str, required_mode: Literal["ro", "rw"]
    ) -> tuple[bool, bool]:
        """Return exact-path presence and required-mode readiness separately.

        ``flatpak override --show`` may render a user-home path as ``~/.…``
        even though the plugin originally set it as an absolute path. Accept
        both forms so a successfully prepared Heroic app is not shown as off.
        A leading ``!`` is Flatpak's explicit denial form and must not count as
        an enabled permission after the user turns the toggle off.
        """
        try:
            relative_path = Path(host_path).relative_to(self.user_home)
        except ValueError:
            relative_path = None

        accepted_paths = {host_path}
        if relative_path is not None:
            accepted_paths.add(f"~/{relative_path.as_posix()}")

        _, _, raw_entries = filesystem_section.partition("=")
        present = False
        ready = False
        for entry in raw_entries.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            denied = entry.startswith("!")
            permission = entry[1:] if denied else entry
            permission_path, separator, mode = permission.rpartition(":")
            if not separator or mode not in {"ro", "rw", "create"}:
                permission_path = permission
                mode = "rw"
            if permission_path in accepted_paths:
                if denied:
                    return False, False
                present = True
                ready = mode == required_mode

        return present, ready

    def _override_rejected(
        self, app_id: str, operation: FlatpakOverrideOperation, error: str
    ) -> FlatpakOverrideOperationResponse:
        return {
            "success": False,
            "outcome": "rejected",
            "status_available": False,
            "error_code": "precondition_failed",
            "retryable": False,
            "app_id": app_id,
            "operation": operation,
            "message": "",
            "error": error,
            "warning": None,
            "failed_steps": [],
            "ownership_status": "unmanaged",
        }

    @staticmethod
    def _valid_app_id(app_id: str) -> bool:
        """Reject values that could be parsed as options or omit the APP target."""
        return isinstance(app_id, str) and bool(FLATPAK_APP_ID_PATTERN.fullmatch(app_id))

    def _observe_before_owned_mutation(
        self, app_id: str, operation: FlatpakOverrideOperation
    ) -> tuple[
        Optional[FlatpakObservedState],
        dict[str, str],
        Optional[FlatpakOverrideOperationResponse],
    ]:
        observed_state, observation_error, modes = self._observe_app_override_snapshot(app_id)
        if observed_state is not None:
            return observed_state, modes, None
        detail = observation_error or "Flatpak override status is unavailable."
        return None, {}, self._override_unverified(
            app_id,
            operation,
            self._sanitize_flatpak_detail(
                "No settings were changed because the current override state "
                f"could not be read: {detail}"
            ),
        )

    def _ownership_failure(
        self,
        app_id: str,
        operation: FlatpakOverrideOperation,
        status: Literal["unknown", "pending", "blocked"],
        detail: str,
    ) -> FlatpakOverrideOperationResponse:
        return self._override_unverified(
            app_id,
            operation,
            self._sanitize_flatpak_detail(
                f"No settings were changed because Flatpak override ownership is {status}: "
                f"{detail}"
            ),
            error_code={
                "unknown": "ownership_unknown",
                "pending": "ownership_pending",
                "blocked": "ownership_blocked",
            }[status],
            ownership_status=status,
        )

    def _override_unverified(
        self,
        app_id: str,
        operation: FlatpakOverrideOperation,
        error: str,
        error_code: Literal[
            "status_unavailable",
            "operation_busy",
            "ownership_unknown",
            "ownership_pending",
            "ownership_blocked",
        ] = "status_unavailable",
        failed: bool = False,
        ownership_status: Literal[
            "managed", "unmanaged", "unknown", "pending", "blocked"
        ] = "unknown",
    ) -> FlatpakOverrideOperationResponse:
        return {
            "success": False,
            "outcome": "unverified",
            "status_available": False,
            "error_code": error_code,
            "retryable": True,
            "app_id": app_id,
            "operation": operation,
            "message": "",
            "error": error,
            "warning": None,
            "failed_steps": [FLATPAK_OVERRIDE_STEP] if failed else [],
            "ownership_status": ownership_status,
        }

    def _flatpak_ownership_status(
        self,
        app_id: str,
        observed_state: FlatpakObservedState,
        document: dict[str, Any],
        states: Optional[dict[str, str]] = None,
    ) -> Literal["managed", "unmanaged", "unknown", "pending", "blocked"]:
        record = document["apps"].get(app_id)
        if record is None:
            has_app_layer_state = any(observed_state.values()) or bool(states)
            return "unknown" if has_app_layer_state else "unmanaged"
        if record["status"] == "pending":
            return "pending"
        if states is None:
            return "managed"
        if not self._exclusive_boundary_matches(record, states):
            return "blocked"
        return "managed" if record["status"] == "active" else "unmanaged"

    @classmethod
    def _exclusive_boundary_matches(
        cls, record: dict[str, Any], states: dict[str, str]
    ) -> bool:
        return states == cls._boundary_states(record)

    @staticmethod
    def _active_boundary_matches(
        record: dict[str, Any], states: dict[str, str]
    ) -> bool:
        for role, entry in record["paths"].items():
            expected = (
                f"grant_{FLATPAK_MANAGED_MODES[role]}"
                if entry["present"]
                else "absent"
            )
            if states.get(entry["path"], "absent") != expected:
                return False
        return all(
            states.get(path, "absent") == "absent" for path in record["retired_paths"]
        )

    @staticmethod
    def _boundary_states(
        record: dict[str, Any], *, remove_owned: bool = False
    ) -> dict[str, str]:
        expected: dict[str, str] = {}
        for role, entry in record["paths"].items():
            if remove_owned and entry["owned"]:
                expected[entry["path"]] = "absent"
            elif entry["present"]:
                expected[entry["path"]] = f"grant_{FLATPAK_MANAGED_MODES[role]}"
            else:
                expected[entry["path"]] = "absent"
        expected.update({path: "absent" for path in record["retired_paths"]})
        return expected

    @classmethod
    def _pending_boundary_states(
        cls, pending: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, str]]:
        before, after = pending["before"], pending["after"]
        before_states = (
            cls._boundary_states(before)
            if before is not None
            else cls._boundary_states(after, remove_owned=True)
        )
        after_states = (
            cls._boundary_states(after)
            if after is not None
            else cls._boundary_states(before, remove_owned=True)
        )
        if pending["operation"] == "set" and before is not None:
            for role, entry in after["paths"].items():
                if entry["path"] not in before_states:
                    before_states[entry["path"]] = (
                        "absent"
                        if entry["owned"]
                        else f"grant_{FLATPAK_MANAGED_MODES[role]}"
                    )
            for entry in before["paths"].values():
                if not entry["owned"] and entry["path"] not in after_states:
                    after_states[entry["path"]] = before_states[entry["path"]]
        return before_states, after_states

    @staticmethod
    def _pending_repair_options(
        before_states: dict[str, str],
        after_states: dict[str, str],
        current_states: dict[str, str],
    ) -> Optional[list[str]]:
        options: list[str] = []
        for path in sorted(set(before_states) | set(after_states)):
            before = before_states.get(path, "absent")
            after = after_states.get(path, "absent")
            current = current_states.get(path, "absent")
            if current not in {before, after}:
                return None
            if current == after:
                continue
            if after.startswith("grant_") and current == "absent":
                options.append(
                    f"--filesystem={path}:{after.removeprefix('grant_')}"
                )
            else:
                return None
        return options

    def _reconcile_pending_ownership(
        self,
        coordinator: MutationCoordinator,
        document: dict[str, Any],
        app_id: str,
        operation: FlatpakOverrideOperation,
    ) -> Optional[FlatpakOverrideOperationResponse]:
        pending = document["apps"].get(app_id)
        if pending is None or pending["status"] != "pending":
            return None
        observed, error, states = self._observe_app_override_snapshot(app_id)
        if observed is None:
            return self._override_unverified(
                app_id,
                operation,
                self._sanitize_flatpak_detail(
                    "A pending ownership intent could not be reconciled because the "
                    f"current state is unavailable: {error or 'status unavailable'}"
                ),
                error_code="ownership_pending",
                ownership_status="pending",
            )
        if any(key.startswith("@env:") for key in states):
            return self._ownership_failure(
                app_id, operation, "blocked", "pending state contains legacy environment overrides"
            )
        before, after = pending["before"], pending["after"]
        after_matches = (
            self._exclusive_boundary_matches(after, states)
            if after is not None
            else not states
        )
        before_matches = (
            self._exclusive_boundary_matches(before, states)
            if before is not None
            else not states
        )
        if after_matches:
            stable = after
        elif before_matches:
            stable = before
        else:
            if operation != pending["operation"]:
                return self._ownership_failure(
                    app_id,
                    operation,
                    "pending",
                    f"retry the recorded {pending['operation']} operation first",
                )
            if pending["operation"] == "remove":
                return self._ownership_failure(
                    app_id,
                    operation,
                    "blocked",
                    "pending remove state contains an unexpected external change",
                )
            before_states, after_states = self._pending_boundary_states(pending)
            options = self._pending_repair_options(
                before_states, after_states, states
            )
            if options is None or any(key.startswith("@") for key in states):
                return self._ownership_failure(
                    app_id,
                    operation,
                    "blocked",
                    "pending filesystem state contains an unexpected external change",
                )

            command_error = None
            try:
                command = self._run_flatpak_command(
                    ["override", "--user", *options, app_id],
                    capture_output=True,
                    text=True,
                )
                if command.returncode != 0:
                    command_error = self._sanitize_flatpak_detail(
                        command.stderr
                        or command.stdout
                        or f"Flatpak exited with {command.returncode}."
                    )
            except Exception as error:
                command_error = self._sanitize_flatpak_detail(error)

            final, final_error, final_states = self._observe_app_override_snapshot(
                app_id
            )
            if final is None:
                return self._override_unverified(
                    app_id,
                    operation,
                    self._sanitize_flatpak_detail(
                        "The pending operation may have changed settings, but its "
                        "current state could not be verified: "
                        f"{final_error or 'status unavailable'}"
                    ),
                    error_code="ownership_pending",
                    failed=command_error is not None,
                    ownership_status="pending",
                )

            if after is not None and self._exclusive_boundary_matches(
                after, final_states
            ):
                document["apps"][app_id] = after
                try:
                    self._write_flatpak_ownership(coordinator, document)
                except Exception as error:
                    return self._override_execution_unavailable(
                        app_id, operation, error
                    )
                response = (
                    self._ownership_complete_remove(app_id, final)
                    if operation == "remove"
                    else self._classify_override_result(
                        app_id, operation, final, command_error
                    )
                )
                if command_error and response["success"]:
                    response["warning"] = self._sanitize_flatpak_detail(
                        "The requested state was verified, although Flatpak reported: "
                        f"{command_error}"
                    )
                    response["failed_steps"] = [FLATPAK_OVERRIDE_STEP]
                return response

            if after is None and not final_states:
                try:
                    self._remove_flatpak_ownership(coordinator, document, app_id)
                except Exception as error:
                    return self._override_execution_unavailable(app_id, operation, error)
                response = self._ownership_complete_remove(app_id, final)
                if command_error:
                    response["warning"] = self._sanitize_flatpak_detail(
                        "The requested state was verified, although Flatpak reported: "
                        f"{command_error}"
                    )
                    response["failed_steps"] = [FLATPAK_OVERRIDE_STEP]
                return response

            result = self._classify_override_result(
                app_id, operation, final, command_error
            )
            result["ownership_status"] = "pending"
            return result
        if stable is None:
            try:
                self._remove_flatpak_ownership(coordinator, document, app_id)
            except Exception as error:
                return self._override_execution_unavailable(app_id, operation, error)
        else:
            document["apps"][app_id] = stable
            try:
                self._write_flatpak_ownership(coordinator, document)
            except Exception as error:
                return self._override_execution_unavailable(app_id, operation, error)
        return None

    def _override_precondition_unavailable(
        self,
        app_id: str,
        operation: FlatpakOverrideOperation,
        error: Exception,
    ) -> FlatpakOverrideOperationResponse:
        """Return a truthful RPC response when a prerequisite probe raises."""
        detail = self._sanitize_flatpak_detail(error)
        self.log.warning(
            "Flatpak override prerequisite failed app=%s operation=%s: %s",
            app_id,
            operation,
            detail,
        )
        return self._override_unverified(
            app_id,
            operation,
            self._sanitize_flatpak_detail(
                "No settings were changed because a prerequisite check failed: "
                f"{detail}"
            ),
        )

    def _override_execution_unavailable(
        self,
        app_id: str,
        operation: FlatpakOverrideOperation,
        error: Exception,
    ) -> FlatpakOverrideOperationResponse:
        """Fail closed when an unexpected error occurs after mutation starts."""
        detail = self._sanitize_flatpak_detail(error)
        self.log.error(
            "Flatpak override result handling failed app=%s operation=%s: %s",
            app_id,
            operation,
            detail,
        )
        return self._override_unverified(
            app_id,
            operation,
            self._sanitize_flatpak_detail(
                "The operation may have changed settings, but its final state "
                f"could not be verified: {detail}"
            ),
            error_code="ownership_pending",
            failed=True,
            ownership_status="pending",
        )

    def _classify_override_result(
        self,
        app_id: str,
        operation: FlatpakOverrideOperation,
        observed_state: FlatpakObservedState,
        command_error: Optional[str],
    ) -> FlatpakOverrideOperationResponse:
        filesystems_present = (
            observed_state["config_filesystem"],
            observed_state["dll_filesystem"],
            observed_state["wrapper_filesystem"],
        )
        filesystems_ready = tuple(
            present and ready
            for present, ready in zip(
                filesystems_present,
                (
                    observed_state["config_filesystem_ready"],
                    observed_state["dll_filesystem_ready"],
                    observed_state["wrapper_filesystem_ready"],
                ),
            )
        )
        legacy_environment = tuple(
            observed_state[field] for field in LEGACY_ENVIRONMENT_FIELDS.values()
        )

        if operation == "set":
            target_matches = filesystems_ready + tuple(
                not present for present in legacy_environment
            )
        else:
            all_values = filesystems_present + legacy_environment
            target_matches = tuple(not present for present in all_values)

        complete = all(target_matches)
        partial = not complete and any(target_matches)

        failed_steps = [FLATPAK_OVERRIDE_STEP] if command_error else []
        if complete:
            message = (
                f"lsfg-vk per-game wrapper access prepared for {app_id}"
                if operation == "set"
                else f"lsfg-vk overrides removed for {app_id}"
            )
            warning = None
            if command_error:
                warning = self._sanitize_flatpak_detail(
                    "The requested state was verified, although Flatpak reported: "
                    f"{command_error}"
                )
            response: FlatpakOverrideOperationResponse = {
                "success": True,
                "outcome": "complete",
                "status_available": True,
                "retryable": False,
                "app_id": app_id,
                "operation": operation,
                "message": message,
                "error": None,
                "warning": warning,
                "failed_steps": failed_steps,
                "observed_state": observed_state,
                "ownership_status": "managed" if operation == "set" else "unmanaged",
            }
        else:
            outcome = "partial" if partial else "failed"
            error_code = "partial_failure" if partial else "operation_failed"
            summary = (
                "The current Flatpak override state matches only part of the request."
                if partial
                else "Flatpak did not reach the requested override state."
            )
            error = self._sanitize_flatpak_detail(
                f"{summary} {command_error}" if command_error else summary
            )
            response = {
                "success": False,
                "outcome": outcome,
                "status_available": True,
                "error_code": error_code,
                "retryable": True,
                "app_id": app_id,
                "operation": operation,
                "message": "",
                "error": error,
                "warning": None,
                "failed_steps": failed_steps,
                "observed_state": observed_state,
                "ownership_status": "managed" if operation == "set" else "unknown",
            }

        self.log.info(
            "Flatpak override result app=%s operation=%s outcome=%s failed_steps=%s",
            app_id,
            operation,
            response["outcome"],
            failed_steps,
        )
        return response

    def _ownership_complete_remove(
        self, app_id: str, observed: FlatpakObservedState
    ) -> FlatpakOverrideOperationResponse:
        return {
            "success": True,
            "outcome": "complete",
            "status_available": True,
            "retryable": False,
            "app_id": app_id,
            "operation": "remove",
            "message": f"lsfg-vk overrides removed for {app_id}",
            "error": None,
            "warning": None,
            "failed_steps": [],
            "observed_state": observed,
            "ownership_status": "unmanaged",
        }

    def set_app_override(self, app_id: str) -> FlatpakOverrideOperationResponse:
        """Prepare one app while durably tracking only grants created by this plugin."""
        if not self._valid_app_id(app_id):
            return self._override_rejected(
                app_id, "set", "Invalid Flatpak application identifier."
            )
        mutation_started = False
        coordinator = self._flatpak_mutation_coordinator()
        try:
            with coordinator.external_operation("flatpak", [self._flatpak_ownership_path]):
                document = self._load_flatpak_ownership()
                previous = document["apps"].get(app_id)
                if previous is not None and previous["status"] == "pending":
                    reconciliation = self._reconcile_pending_ownership(
                        coordinator, document, app_id, "set"
                    )
                    if reconciliation is not None:
                        return reconciliation
                    document = self._load_flatpak_ownership()
                    previous = document["apps"].get(app_id)
                if not self.check_flatpak_available():
                    return self._override_rejected(
                        app_id, "set", "Flatpak is not available on this system"
                    )
                runtime_version = self._get_app_runtime_version(app_id)
                if runtime_version is None:
                    return self._override_rejected(
                        app_id,
                        "set",
                        "Could not determine a supported Flatpak runtime for this application. "
                        "Install the matching experimental runtime extension first.",
                    )
                if not self._is_extension_installed(runtime_version):
                    return self._override_rejected(
                        app_id,
                        "set",
                        f"Install the experimental {runtime_version} runtime extension before enabling this application.",
                    )
                if not self.lsfg_launch_script_path.is_file():
                    return self._override_rejected(
                        app_id,
                        "set",
                        "Install Experimental LSFG-VK before preparing a Flatpak application.",
                    )

                observed, exact_states, read_error = self._observe_before_owned_mutation(
                    app_id, "set"
                )
                if observed is None:
                    assert read_error is not None
                    return read_error
                if any(key.startswith("@env:") for key in exact_states):
                    return self._ownership_failure(
                        app_id,
                        "set",
                        "unknown",
                        "a legacy LSFG environment override or unset is already present",
                    )
                if previous is None and exact_states:
                    return self._ownership_failure(
                        app_id,
                        "set",
                        "unknown",
                        "the application already has user or Flatseal overrides; automatic setup would not be safely reversible",
                    )
                if previous is not None and self._flatpak_ownership_status(
                    app_id, observed, document, exact_states
                ) == "blocked":
                    return self._ownership_failure(
                        app_id, "set", "blocked", "tracked filesystem state was changed externally"
                    )

                config_path, dll_directory = self._get_lsfg_paths()
                paths = {
                    "config": config_path,
                    "dll": dll_directory,
                    "wrapper": str(self.lsfg_launch_script_path),
                }
                if len(set(paths.values())) != len(paths):
                    return self._ownership_failure(
                        app_id, "set", "blocked", "managed filesystem paths overlap"
                    )
                if previous is not None:
                    previous_paths = {
                        role: entry["path"] for role, entry in previous["paths"].items()
                    }
                    if previous["status"] != "active" or not all(
                        entry["owned"] for entry in previous["paths"].values()
                    ):
                        return self._ownership_failure(
                            app_id,
                            "set",
                            "blocked",
                            "the existing ownership record is not exclusive",
                        )
                    if previous_paths != paths:
                        return self._ownership_failure(
                            app_id,
                            "set",
                            "blocked",
                            "the managed paths changed; remove the existing override before enabling it again",
                        )
                for role, path in paths.items():
                    state = exact_states.get(path, "absent")
                    if state not in {"absent", f"grant_{FLATPAK_MANAGED_MODES[role]}"}:
                        return self._ownership_failure(
                            app_id,
                            "set",
                            "unknown",
                            f"{role} path already has an incompatible app-layer state",
                        )

                active = {
                    "status": "active",
                    "paths": {
                        role: {"path": path, "owned": True, "present": True}
                        for role, path in paths.items()
                    },
                    "retired_paths": [],
                }
                options: list[str] = []
                for role, entry in active["paths"].items():
                    if entry["owned"] and exact_states.get(entry["path"], "absent") == "absent":
                        options.append(
                            f"--filesystem={entry['path']}:{FLATPAK_MANAGED_MODES[role]}"
                        )

                if not options:
                    document["apps"][app_id] = active
                    self._write_flatpak_ownership(coordinator, document)
                    result = self._classify_override_result(
                        app_id, "set", observed, command_error=None
                    )
                    result["ownership_status"] = self._flatpak_ownership_status(
                        app_id, observed, document, exact_states
                    )
                    return result

                document["apps"][app_id] = {
                    "status": "pending",
                    "operation": "set",
                    "before": previous,
                    "after": active,
                }
                self._write_flatpak_ownership(coordinator, document)
                mutation_started = True
                command_error = None
                try:
                    command = self._run_flatpak_command(
                        ["override", "--user", *options, app_id],
                        capture_output=True,
                        text=True,
                    )
                    if command.returncode != 0:
                        command_error = self._sanitize_flatpak_detail(
                            command.stderr or command.stdout or f"Flatpak exited with {command.returncode}."
                        )
                except Exception as error:
                    command_error = self._sanitize_flatpak_detail(error)

                final, final_error, final_states = self._observe_app_override_snapshot(app_id)
                if final is None:
                    return self._override_unverified(
                        app_id,
                        "set",
                        self._sanitize_flatpak_detail(
                            "The operation may have changed settings, but the current state "
                            f"could not be verified: {final_error or 'status unavailable'}"
                        ),
                        failed=command_error is not None,
                        ownership_status="pending",
                    )
                target_matches = all(
                    final_states.get(entry["path"], "absent")
                    == f"grant_{FLATPAK_MANAGED_MODES[role]}"
                    for role, entry in active["paths"].items()
                ) and final_states == self._boundary_states(active)
                result = self._classify_override_result(
                    app_id, "set", final, command_error
                )
                if target_matches and result["outcome"] == "complete":
                    document["apps"][app_id] = active
                    self._write_flatpak_ownership(coordinator, document)
                    result["ownership_status"] = self._flatpak_ownership_status(
                        app_id, final, document, final_states
                    )
                else:
                    result["ownership_status"] = "pending"
                return result
        except MutationBusyError:
            return self._override_unverified(
                app_id,
                "set",
                "Another plugin state change is still in progress. Refresh shortly.",
                error_code="operation_busy",
            )
        except MutationBlockedError as error:
            return self._ownership_failure(app_id, "set", "blocked", str(error))
        except Exception as error:
            if mutation_started:
                return self._override_execution_unavailable(app_id, "set", error)
            return self._override_precondition_unavailable(app_id, "set", error)

    def remove_app_override(self, app_id: str) -> FlatpakOverrideOperationResponse:
        """Remove only exact filesystem grants durably recorded as plugin-owned."""
        if not self._valid_app_id(app_id):
            return self._override_rejected(
                app_id, "remove", "Invalid Flatpak application identifier."
            )
        mutation_started = False
        coordinator = self._flatpak_mutation_coordinator()
        try:
            with coordinator.external_operation("flatpak", [self._flatpak_ownership_path]):
                document = self._load_flatpak_ownership()
                record = document["apps"].get(app_id)
                if record is not None and record["status"] == "pending":
                    reconciliation = self._reconcile_pending_ownership(
                        coordinator, document, app_id, "remove"
                    )
                    if reconciliation is not None:
                        return reconciliation
                    document = self._load_flatpak_ownership()
                    record = document["apps"].get(app_id)
                if not self.check_flatpak_available():
                    return self._override_rejected(
                        app_id, "remove", "Flatpak is not available on this system"
                    )
                observed, exact_states, read_error = self._observe_before_owned_mutation(
                    app_id, "remove"
                )
                if observed is None:
                    assert read_error is not None
                    return read_error
                if record is None:
                    if any(observed.values()) or any(
                        key.startswith("@env:") for key in exact_states
                    ):
                        return self._ownership_failure(
                            app_id,
                            "remove",
                            "unknown",
                            "matching app-layer overrides exist without an ownership record",
                        )
                    return self._ownership_complete_remove(app_id, observed)
                if any(key.startswith("@env:") for key in exact_states):
                    return self._ownership_failure(
                        app_id,
                        "remove",
                        "unknown",
                        "legacy environment state is not owned by the filesystem ledger",
                    )
                if self._flatpak_ownership_status(
                    app_id, observed, document, exact_states
                ) == "blocked":
                    return self._ownership_failure(
                        app_id, "remove", "blocked", "tracked filesystem state was changed externally"
                    )

                if (
                    record["status"] != "active"
                    or record["retired_paths"]
                    or not all(entry["owned"] for entry in record["paths"].values())
                    or not self._exclusive_boundary_matches(record, exact_states)
                ):
                    return self._ownership_failure(
                        app_id,
                        "remove",
                        "blocked",
                        "the app override is not exclusively owned by this plugin",
                    )

                document["apps"][app_id] = {
                    "status": "pending",
                    "operation": "remove",
                    "before": record,
                    "after": None,
                }
                self._write_flatpak_ownership(coordinator, document)
                mutation_started = True
                command_error = None
                try:
                    command = self._run_flatpak_command(
                        ["override", "--user", "--reset", app_id],
                        capture_output=True,
                        text=True,
                    )
                    if command.returncode != 0:
                        command_error = self._sanitize_flatpak_detail(
                            command.stderr or command.stdout or f"Flatpak exited with {command.returncode}."
                        )
                except Exception as error:
                    command_error = self._sanitize_flatpak_detail(error)

                final, final_error, final_states = self._observe_app_override_snapshot(app_id)
                if final is None:
                    return self._override_unverified(
                        app_id,
                        "remove",
                        self._sanitize_flatpak_detail(
                            "The operation may have changed settings, but the current state "
                            f"could not be verified: {final_error or 'status unavailable'}"
                        ),
                        failed=command_error is not None,
                        ownership_status="pending",
                    )
                if not final_states:
                    self._remove_flatpak_ownership(coordinator, document, app_id)
                    response = self._ownership_complete_remove(app_id, final)
                    if command_error:
                        response["warning"] = self._sanitize_flatpak_detail(
                            "The requested state was verified, although Flatpak reported: "
                            f"{command_error}"
                        )
                        response["failed_steps"] = [FLATPAK_OVERRIDE_STEP]
                    return response
                result = self._classify_override_result(
                    app_id, "remove", final, command_error
                )
                if result["success"]:
                    result = {
                        **result,
                        "success": False,
                        "outcome": "partial",
                        "error_code": "partial_failure",
                        "retryable": True,
                        "message": "",
                        "error": (
                            "Flatpak did not remove every exact plugin-owned app-layer grant."
                        ),
                        "warning": None,
                    }
                result["ownership_status"] = "pending"
                return result
        except MutationBusyError:
            return self._override_unverified(
                app_id,
                "remove",
                "Another plugin state change is still in progress. Refresh shortly.",
                error_code="operation_busy",
            )
        except MutationBlockedError as error:
            return self._ownership_failure(app_id, "remove", "blocked", str(error))
        except Exception as error:
            if mutation_started:
                return self._override_execution_unavailable(app_id, "remove", error)
            return self._override_precondition_unavailable(app_id, "remove", error)
