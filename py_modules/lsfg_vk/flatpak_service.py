"""
Flatpak service for managing lsfg-vk Flatpak runtime extensions.
"""

import subprocess
import os
import re
import threading
import unicodedata
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
        self._app_override_lock = threading.Lock()

    def _get_lsfg_paths(self) -> tuple[str, str]:
        """Return the config directory and read-only directory containing Lossless.dll.

        Upstream's Flatpak guide grants the Steam common directory so the sandbox can
        load Lossless Scaling. If the user selected a custom DLL path, grant that
        DLL's directory instead.
        """
        home_path = os.path.expanduser("~")
        config_path = str(self.config_dir)
        dll_directory = f"{home_path}/.local/share/Steam/steamapps/common"

        if not self.config_file_path.exists():
            return config_path, dll_directory

        try:
            profile_data = ConfigurationManager.parse_toml_content_multi_profile(
                self.config_file_path.read_text(encoding="utf-8")
            )
            configured_dll = profile_data["global_config"].get("dll", "")
            if configured_dll:
                dll_directory = str(Path(str(configured_dll)).parent)
        except Exception as error:
            self.log.debug("Could not read configured DLL path for Flatpak override: %s", error)

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

            apps = []
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue

                parts = line.split('\t')
                if len(parts) >= 2:
                    app_name = parts[0].strip()
                    app_id = parts[1].strip()

                    observation, observation_error = self._observe_app_override_status(app_id)
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
                        })
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
        if not self._valid_app_id(app_id):
            return None, "Invalid Flatpak application identifier."
        try:
            result = self._run_flatpak_command(
                ["override", "--user", "--show", app_id],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                detail = self._sanitize_flatpak_detail(result.stderr or result.stdout)
                return None, detail or "Flatpak could not read the application overrides."

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

            return {
                "config_filesystem": has_config_fs,
                "dll_filesystem": has_dll_fs,
                "wrapper_filesystem": has_wrapper_fs,
                "config_filesystem_ready": config_fs_ready,
                "dll_filesystem_ready": dll_fs_ready,
                "wrapper_filesystem_ready": wrapper_fs_ready,
                **environment_state,
            }, None

        except Exception as e:
            detail = self._sanitize_flatpak_detail(e)
            self.log.error("Error checking override status for %s: %s", app_id, detail)
            return None, detail or "Flatpak override status is unavailable."

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
        }

    @staticmethod
    def _valid_app_id(app_id: str) -> bool:
        """Reject values that could be parsed as options or omit the APP target."""
        return isinstance(app_id, str) and bool(FLATPAK_APP_ID_PATTERN.fullmatch(app_id))

    def _observe_before_mutation(
        self, app_id: str, operation: FlatpakOverrideOperation
    ) -> tuple[Optional[FlatpakObservedState], Optional[FlatpakOverrideOperationResponse]]:
        observed_state, observation_error = self._observe_app_override_status(app_id)
        if observed_state is not None:
            return observed_state, None
        detail = observation_error or "Flatpak override status is unavailable."
        return None, self._override_unverified(
            app_id,
            operation,
            self._sanitize_flatpak_detail(
                "No settings were changed because the current override state "
                f"could not be read: {detail}"
            ),
        )

    def _override_unverified(
        self,
        app_id: str,
        operation: FlatpakOverrideOperation,
        error: str,
        error_code: Literal["status_unavailable", "operation_busy"] = "status_unavailable",
        failed: bool = False,
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
        }

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
            failed=True,
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
        filesystems_ready = (
            observed_state["config_filesystem_ready"],
            observed_state["dll_filesystem_ready"],
            observed_state["wrapper_filesystem_ready"],
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
            }
        else:
            outcome = "partial" if partial else "failed"
            error_code = "partial_failure" if partial else "operation_failed"
            summary = (
                "Flatpak applied only part of the requested override state."
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
            }

        self.log.info(
            "Flatpak override result app=%s operation=%s outcome=%s failed_steps=%s",
            app_id,
            operation,
            response["outcome"],
            failed_steps,
        )
        return response

    def _apply_and_observe_override(
        self, app_id: str, operation: FlatpakOverrideOperation, arguments: List[str]
    ) -> FlatpakOverrideOperationResponse:
        command_error = None
        try:
            result = self._run_flatpak_command(
                arguments,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                command_error = self._sanitize_flatpak_detail(
                    result.stderr or result.stdout or f"Flatpak exited with {result.returncode}."
                )
        except Exception as error:
            command_error = self._sanitize_flatpak_detail(error)

        observed_state, observation_error = self._observe_app_override_status(app_id)
        if observed_state is None:
            detail = observation_error or "Flatpak override status is unavailable."
            error = self._sanitize_flatpak_detail(
                "The operation may have changed settings, but the current state "
                f"could not be verified: {detail}"
            )
            return self._override_unverified(
                app_id,
                operation,
                error,
                failed=command_error is not None,
            )
        return self._classify_override_result(
            app_id, operation, observed_state, command_error
        )

    def _try_override_lock(
        self, app_id: str, operation: FlatpakOverrideOperation
    ) -> Optional[FlatpakOverrideOperationResponse]:
        if self._app_override_lock.acquire(blocking=False):
            return None
        return self._override_unverified(
            app_id,
            operation,
            "Another Flatpak application change is still in progress. Refresh shortly.",
            error_code="operation_busy",
        )

    def set_app_override(self, app_id: str) -> FlatpakOverrideOperationResponse:
        """Prepare one Flatpak app and report its strictly observed final state."""
        if not self._valid_app_id(app_id):
            return self._override_rejected(
                app_id, "set", "Invalid Flatpak application identifier."
            )
        busy = self._try_override_lock(app_id, "set")
        if busy is not None:
            return busy
        mutation_started = False
        try:
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

            config_path, dll_directory = self._get_lsfg_paths()
            wrapper_path = str(self.lsfg_launch_script_path)
            initial_state, read_error = self._observe_before_mutation(app_id, "set")
            if initial_state is None:
                assert read_error is not None
                return read_error

            arguments = [
                "override",
                "--user",
                f"--filesystem={config_path}:rw",
                f"--filesystem={dll_directory}:ro",
                f"--filesystem={wrapper_path}:ro",
                *[
                    f"--unset-env={variable}"
                    for variable, field in LEGACY_ENVIRONMENT_FIELDS.items()
                    if initial_state[field]
                ],
                app_id,
            ]
            mutation_started = True
            return self._apply_and_observe_override(app_id, "set", arguments)
        except Exception as error:
            if mutation_started:
                return self._override_execution_unavailable(app_id, "set", error)
            return self._override_precondition_unavailable(app_id, "set", error)
        finally:
            self._app_override_lock.release()

    def remove_app_override(self, app_id: str) -> FlatpakOverrideOperationResponse:
        """Remove managed overrides and report the strictly observed final state."""
        if not self._valid_app_id(app_id):
            return self._override_rejected(
                app_id, "remove", "Invalid Flatpak application identifier."
            )
        busy = self._try_override_lock(app_id, "remove")
        if busy is not None:
            return busy
        mutation_started = False
        try:
            if not self.check_flatpak_available():
                return self._override_rejected(
                    app_id, "remove", "Flatpak is not available on this system"
                )

            config_path, dll_directory = self._get_lsfg_paths()
            wrapper_path = str(self.lsfg_launch_script_path)
            initial_state, read_error = self._observe_before_mutation(app_id, "remove")
            if initial_state is None:
                assert read_error is not None
                return read_error

            options = []
            if initial_state["dll_filesystem"]:
                options.append(f"--nofilesystem={dll_directory}")
            if initial_state["config_filesystem"]:
                options.append(f"--nofilesystem={config_path}")
            if initial_state["wrapper_filesystem"]:
                options.append(f"--nofilesystem={wrapper_path}")
            options.extend(
                f"--unset-env={variable}"
                for variable, field in LEGACY_ENVIRONMENT_FIELDS.items()
                if initial_state[field]
            )
            if not options:
                return self._classify_override_result(
                    app_id, "remove", initial_state, command_error=None
                )

            arguments = ["override", "--user", *options, app_id]
            mutation_started = True
            return self._apply_and_observe_override(app_id, "remove", arguments)
        except Exception as error:
            if mutation_started:
                return self._override_execution_unavailable(app_id, "remove", error)
            return self._override_precondition_unavailable(app_id, "remove", error)
        finally:
            self._app_override_lock.release()
