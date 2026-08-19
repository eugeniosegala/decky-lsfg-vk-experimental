"""
Installation service for lsfg-vk.
"""

import shutil
import tarfile
import tempfile
import json
import os
import hashlib
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any, BinaryIO, Dict, Optional

from .base_service import BaseService
from .constants import (
    LIB_FILENAME, JSON_FILENAME, JSON32_FILENAME, CLI_FILENAME, CLI_DIR, BIN_DIR,
    DIAGNOSTICS_HELPER_FILENAME, EXPERIMENTAL_LAYER_NAME,
    EXPERIMENTAL_LAYER_ENABLE_ENV, EXPERIMENTAL_LAYER_DISABLE_ENV,
    EXPERIMENTAL_LAYER_BUILD_MARKER, LEGACY_PRIVATE_JSON_FILENAMES,
)
from .config_schema import ConfigurationManager
from .types import InstallationResponse, UninstallationResponse, InstallationCheckResponse


_MAX_ARCHIVE_MEMBERS = 1024
_MAX_SELECTED_MEMBER_BYTES = 256 * 1024 * 1024


def _engine_lifecycle_targets(layout):
    """Return the finite set used only to select install versus update."""
    return (
        layout.registered_manifest64,
        layout.registered_manifest32,
        layout.obsolete_hdr_manifest,
        layout.private_library64,
        layout.private_library32,
        layout.private_manifest64,
        layout.private_manifest32,
        layout.cli,
        layout.engine_state,
        *layout.legacy_private_manifests,
    )


def _select_install_or_update_locked(layout) -> str:
    """Select install only when every engine lifecycle target is absent."""
    for target in _engine_lifecycle_targets(layout):
        try:
            target.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return "update"
        return "update"
    return "install"


class InstallationService(BaseService):
    """Service for handling lsfg-vk installation and uninstallation"""
    
    def __init__(self, logger=None):
        super().__init__(logger)
        
        self.lib_file = self.local_lib_dir / LIB_FILENAME
        self.lib32_file = self.local_lib32_dir / LIB_FILENAME
        self.json_file = self.local_share_dir / JSON_FILENAME
        self.json32_file = self.local_share_dir / JSON32_FILENAME
        self.cli_file = self.user_home / CLI_DIR / CLI_FILENAME
        self.engine_state_file = self.local_lib_dir.parent / "installed-engine.json"
    
    def install(self) -> InstallationResponse:
        """Install or update the bundled engine in one recoverable transaction."""
        from . import state_transaction

        layout = state_transaction.PathLayout.from_home(self.user_home)
        coordinator = state_transaction.MutationCoordinator(layout)
        try:
            with coordinator.locked("install"):
                recovery = coordinator.recover()
                if recovery.refresh_required:
                    return self._lifecycle_error(
                        InstallationResponse,
                        "Recovered interrupted state; refresh before retrying",
                        "refresh_required",
                    )
                operation = _select_install_or_update_locked(layout)
                if operation == "update":
                    self._validate_lifecycle_types(layout)
                plugin_dir = Path(__file__).parent.parent.parent
                metadata = self._bundled_archive_metadata(plugin_dir)
                archive_path = plugin_dir / BIN_DIR / metadata["name"]
                payload = self._validate_archive_checksum(
                    archive_path, metadata["sha256hash"]
                )
                replacements, removals = self._build_install_plan(
                    layout, plugin_dir, payload, metadata
                )
                steps = self._ordered_install_steps(
                    layout, operation, replacements, removals
                )
                result = coordinator.commit(
                    operation,
                    replacements={},
                    removals=(),
                    ordered_steps=steps,
                )
                if result.refresh_required:
                    return self._lifecycle_error(
                        InstallationResponse,
                        "Recovered interrupted state; refresh before retrying",
                        "refresh_required",
                    )
                return self._success_response(
                    InstallationResponse,
                    "lsfg-vk installed successfully",
                    retryable=False,
                    recovery_pending=result.recovery_pending,
                    recovery_action=(
                        "wait_for_recovery" if result.recovery_pending else "none"
                    ),
                    warning=result.warning,
                    **({"error_code": "recovery_pending"} if result.recovery_pending else {}),
                )
        except state_transaction.MutationBusyError as error:
            return self._lifecycle_error(
                InstallationResponse, error, "mutation_busy"
            )
        except state_transaction.MutationBlockedError as error:
            return self._lifecycle_error(
                InstallationResponse, error, "recovery_blocked"
            )
        except (OSError, tarfile.TarError, shutil.Error, ValueError, TypeError, json.JSONDecodeError) as error:
            code = "invalid_persisted_state" if "persisted" in str(error).lower() else "durability_failure"
            return self._lifecycle_error(InstallationResponse, error, code)

    @staticmethod
    def _validate_lifecycle_types(layout) -> None:
        """Fail closed on partial engine state with unsafe filesystem types."""
        from .state_transaction import MutationBlockedError

        for target in _engine_lifecycle_targets(layout):
            try:
                metadata = target.lstat()
            except FileNotFoundError:
                continue
            except OSError as error:
                raise MutationBlockedError(
                    f"cannot inspect managed target {target}: {error}"
                ) from error
            if not stat.S_ISREG(metadata.st_mode):
                raise MutationBlockedError(
                    f"managed target is not a regular file: {target}"
                )

    def _lifecycle_error(self, response_type, error, error_code, **kwargs):
        kwargs.setdefault("retryable", error_code == "mutation_busy")
        kwargs.setdefault("recovery_pending", False)
        kwargs.setdefault(
            "recovery_action", self._recovery_action_for_error(error_code)
        )
        kwargs.setdefault("warning", None)
        return self._error_response(
            response_type,
            str(error),
            message="",
            error_code=error_code,
            **kwargs,
        )

    @staticmethod
    def _render_manifest(source: bytes, library_path: str, architecture: str) -> bytes:
        try:
            value = json.loads(source)
            layer = value.get("layer")
            if not isinstance(layer, dict) or not isinstance(layer.get("library_path"), str):
                raise ValueError("missing layer.library_path")
            layer.update({
                "name": EXPERIMENTAL_LAYER_NAME,
                "description": "Lossless Scaling experimental frame generation layer",
                "library_path": library_path,
                "library_arch": architecture,
                "enable_environment": {EXPERIMENTAL_LAYER_ENABLE_ENV: "1"},
                "disable_environment": {EXPERIMENTAL_LAYER_DISABLE_ENV: "1"},
            })
            return (json.dumps(value, indent=2) + "\n").encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise OSError(f"Invalid Vulkan layer manifest: {error}") from error

    def _read_archive_payload(self, archive_source: BinaryIO) -> Dict[str, bytes]:
        selected = {
            f"lib/{LIB_FILENAME}",
            f"lib32/{LIB_FILENAME}",
            f"share/vulkan/implicit_layer.d/{JSON_FILENAME}",
            f"share/vulkan/implicit_layer.d/{JSON32_FILENAME}",
            f"bin/{CLI_FILENAME}",
        }
        payload: Dict[str, bytes] = {}
        with tarfile.open(fileobj=archive_source, mode="r:xz") as archive:
            members = archive.getmembers()
            if len(members) > _MAX_ARCHIVE_MEMBERS:
                raise OSError("Archive member resource limit exceeded")
            for member in members:
                name = member.name.removeprefix("./")
                if name not in selected:
                    continue
                if name in payload:
                    raise OSError(f"Archive contains duplicate selected member: {name}")
                if not member.isfile():
                    raise OSError(f"Archive selected member is not a regular file: {name}")
                if member.size < 0 or member.size > _MAX_SELECTED_MEMBER_BYTES:
                    raise OSError(f"Archive selected member is too large: {name}")
                source = archive.extractfile(member)
                if source is None:
                    raise OSError(f"Archive selected member is unreadable: {name}")
                with source:
                    content = source.read(_MAX_SELECTED_MEMBER_BYTES + 1)
                if len(content) != member.size or len(content) > _MAX_SELECTED_MEMBER_BYTES:
                    raise OSError(f"Archive selected member size is invalid: {name}")
                payload[name] = content
        required = (
            f"lib/{LIB_FILENAME}",
            f"share/vulkan/implicit_layer.d/{JSON_FILENAME}",
        )
        missing = [name for name in required if name not in payload]
        if missing:
            raise OSError("Archive did not contain required lsfg-vk files: " + ", ".join(missing))
        has_lib32 = f"lib32/{LIB_FILENAME}" in payload
        has_json32 = f"share/vulkan/implicit_layer.d/{JSON32_FILENAME}" in payload
        if has_lib32 != has_json32:
            raise OSError("Archive contained an incomplete 32-bit Vulkan layer pair")
        binaries = [payload[f"lib/{LIB_FILENAME}"]]
        if has_lib32:
            binaries.append(payload[f"lib32/{LIB_FILENAME}"])
        if any(EXPERIMENTAL_LAYER_BUILD_MARKER not in binary for binary in binaries):
            raise OSError("Experimental layer build marker is missing from archive payload")
        return payload

    def _configuration_plan(self, layout):
        from .configuration import ConfigurationService
        from .config_schema import DEFAULT_PROFILE_NAME, SCRIPT_ONLY_FIELDS

        service = ConfigurationService(logger=self.log)
        service.user_home = self.user_home
        service.config_dir = layout.config_dir
        service.config_file_path = layout.config_file
        service.wrapper_profile_settings_path = layout.wrapper_settings
        service.lsfg_script_path = layout.launcher
        try:
            layout.config_file.lstat()
            config_exists = True
        except FileNotFoundError:
            config_exists = False
        try:
            layout.wrapper_settings.lstat()
            wrapper_exists = True
        except FileNotFoundError:
            wrapper_exists = False

        if config_exists and wrapper_exists:
            try:
                profile_data, settings = service._load_effective_state_strict()
            except Exception as error:
                raise ValueError(f"Invalid persisted state: {error}") from error
            rendered = service._render_effective_state(profile_data, settings)
            return {layout.launcher: rendered[layout.launcher]}

        if config_exists:
            try:
                profile_data = service._get_profile_data()
            except Exception as error:
                raise ValueError(f"Invalid persisted state: {error}") from error
            settings = {
                profile_name: service._wrapper_settings_defaults()
                for profile_name in profile_data["profiles"]
            }
            rendered = service._render_effective_state(profile_data, settings)
            return {
                layout.wrapper_settings: rendered[layout.wrapper_settings],
                layout.launcher: rendered[layout.launcher],
            }

        if wrapper_exists:
            try:
                settings = service._read_wrapper_profile_settings_strict()
            except Exception as error:
                raise ValueError(f"Invalid persisted state: {error}") from error
            profile_names = list(settings) or [DEFAULT_PROFILE_NAME]
            current_profile = (
                DEFAULT_PROFILE_NAME
                if DEFAULT_PROFILE_NAME in profile_names
                else profile_names[0]
            )
            defaults = ConfigurationManager.get_defaults()
            profile_data = {
                "current_profile": current_profile,
                "profiles": {name: dict(defaults) for name in profile_names},
                "global_config": {
                    "dll": defaults.get("dll", ""),
                    "allow_fp16": defaults.get("allow_fp16", True),
                },
            }
            rendered = service._render_effective_state(profile_data, settings)
            return {
                layout.config_file: rendered[layout.config_file],
                layout.launcher: rendered[layout.launcher],
            }

        defaults = ConfigurationManager.get_defaults()
        profile_data = {
            "current_profile": DEFAULT_PROFILE_NAME,
            "profiles": {DEFAULT_PROFILE_NAME: defaults},
            "global_config": {
                "dll": defaults.get("dll", ""),
                "allow_fp16": defaults.get("allow_fp16", True),
            },
        }
        settings = {
            DEFAULT_PROFILE_NAME: {
                field: defaults[field] for field in SCRIPT_ONLY_FIELDS
            }
        }
        return service._render_effective_state(profile_data, settings)

    def _build_install_plan(self, layout, plugin_dir, payload, metadata):
        private64 = self._render_manifest(
            payload[f"share/vulkan/implicit_layer.d/{JSON_FILENAME}"],
            "../../lib/liblsfg-vk-layer.so", "64",
        )
        replacements = {
            layout.private_library64: (payload[f"lib/{LIB_FILENAME}"], 0o644),
            layout.private_manifest64: (private64, 0o644),
            layout.registered_manifest64: (
                self._render_manifest(
                    payload[f"share/vulkan/implicit_layer.d/{JSON_FILENAME}"],
                    str(layout.private_library64), "64",
                ), 0o644,
            ),
            layout.diagnostics_helper: (
                self._diagnostics_helper_source(plugin_dir).read_bytes(), 0o755
            ),
            layout.engine_state: ((json.dumps({
                "archive": metadata["name"],
                "version": metadata["version"],
                "sha256hash": metadata["sha256hash"],
                "architectures": metadata.get("architectures", ["64", "32"]),
            }, indent=2) + "\n").encode("utf-8"), 0o644),
            **self._configuration_plan(layout),
        }
        removals = {
            layout.obsolete_hdr_manifest,
            *layout.legacy_private_manifests,
        }
        cli_name = f"bin/{CLI_FILENAME}"
        if cli_name in payload:
            replacements[layout.cli] = (payload[cli_name], 0o755)
        else:
            removals.add(layout.cli)
        manifest32_name = f"share/vulkan/implicit_layer.d/{JSON32_FILENAME}"
        if manifest32_name in payload:
            replacements[layout.private_library32] = (
                payload[f"lib32/{LIB_FILENAME}"], 0o644
            )
            replacements[layout.private_manifest32] = (
                self._render_manifest(payload[manifest32_name], "../../lib32/liblsfg-vk-layer.so", "32"), 0o644
            )
            replacements[layout.registered_manifest32] = (
                self._render_manifest(payload[manifest32_name], str(layout.private_library32), "32"), 0o644
            )
        else:
            removals.update((layout.private_library32, layout.private_manifest32, layout.registered_manifest32))
        return replacements, removals

    @staticmethod
    def _ordered_install_steps(layout, operation, replacements, removals):
        registered = (layout.registered_manifest64, layout.registered_manifest32)
        marker = layout.engine_state
        steps = []
        if operation == "update":
            for path in registered:
                if path.exists():
                    steps.append((path, "remove", None, 0))
        middle_order = (
            layout.private_library64, layout.private_library32, layout.cli,
            layout.private_manifest64, layout.private_manifest32,
            layout.diagnostics_helper, layout.config_file,
            layout.wrapper_settings, layout.launcher,
            layout.obsolete_hdr_manifest, *layout.legacy_private_manifests,
        )
        for path in middle_order:
            if path in replacements:
                content, mode = replacements[path]
                steps.append((path, "replace", content, mode))
            elif path in removals and path.exists():
                steps.append((path, "remove", None, 0))
        for path in registered:
            if path in replacements:
                content, mode = replacements[path]
                steps.append((path, "replace", content, mode))
            elif path in removals and path.exists() and not any(
                step[0] == path for step in steps
            ):
                steps.append((path, "remove", None, 0))
        content, mode = replacements[marker]
        steps.append((marker, "replace", content, mode))
        return steps

    def _bundled_archive_metadata(self, plugin_dir: Path) -> Dict[str, Any]:
        """Return the versioned host payload metadata from package.json."""
        manifest_path = plugin_dir / "package.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            binaries = manifest.get("remote_binary")
            if not isinstance(binaries, list) or len(binaries) != 1:
                raise ValueError("package.json must define exactly one remote_binary entry")
            binary = binaries[0]
            archive_name = binary.get("name")
            version = binary.get("version")
            checksum = binary.get("sha256hash")
            architectures = binary.get("architectures", ["64", "32"])
            if not isinstance(archive_name, str) or Path(archive_name).name != archive_name:
                raise ValueError("remote_binary name must be a filename")
            if not isinstance(version, str) or not version:
                raise ValueError("remote_binary version must be a non-empty string")
            if (
                not isinstance(checksum, str)
                or len(checksum) != 64
                or any(character not in "0123456789abcdefABCDEF" for character in checksum)
            ):
                raise ValueError("remote_binary sha256hash must be a SHA-256 checksum")
            if (
                not isinstance(architectures, list)
                or not architectures
                or any(architecture not in ("64", "32") for architecture in architectures)
                or "64" not in architectures
            ):
                raise ValueError("remote_binary architectures must contain 64 and optional 32")
            return {
                "name": archive_name,
                "version": version,
                "sha256hash": checksum,
                "architectures": architectures,
            }
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise OSError(f"Could not read bundled lsfg-vk metadata from {manifest_path}: {exc}") from exc

    def _write_engine_state(self, archive_metadata: Dict[str, Any]) -> None:
        """Record exactly which pinned payload was installed by this plugin."""
        state = {
            "archive": archive_metadata["name"],
            "version": archive_metadata["version"],
            "sha256hash": archive_metadata["sha256hash"],
            "architectures": archive_metadata.get("architectures", ["64", "32"]),
        }
        self._write_file(self.engine_state_file, json.dumps(state, indent=2) + "\n", 0o644)

    def _validate_archive_checksum(
        self, archive_path: Path, expected_checksum: str
    ) -> Dict[str, bytes]:
        """Hash and consume one stable opened archive, returning its payload."""
        digest = hashlib.sha256()
        with archive_path.open("rb") as archive:
            opened_before = os.fstat(archive.fileno())
            if not stat.S_ISREG(opened_before.st_mode):
                raise OSError(f"Bundled archive is not a regular file: {archive_path}")
            for chunk in iter(lambda: archive.read(1024 * 1024), b""):
                digest.update(chunk)
            opened_after_hash = os.fstat(archive.fileno())
            stable_before = (
                opened_before.st_dev,
                opened_before.st_ino,
                opened_before.st_size,
                opened_before.st_mtime_ns,
                opened_before.st_ctime_ns,
            )
            stable_after_hash = (
                opened_after_hash.st_dev,
                opened_after_hash.st_ino,
                opened_after_hash.st_size,
                opened_after_hash.st_mtime_ns,
                opened_after_hash.st_ctime_ns,
            )
            if stable_before != stable_after_hash:
                raise OSError("Bundled lsfg-vk archive changed during checksum validation")
            actual_checksum = digest.hexdigest()
            if actual_checksum.lower() != expected_checksum.lower():
                raise OSError(
                    "Bundled lsfg-vk archive checksum mismatch: "
                    f"expected {expected_checksum.lower()}, got {actual_checksum}"
                )
            archive.seek(0)
            payload = self._read_archive_payload(archive)
            opened_after_read = os.fstat(archive.fileno())
            stable_after_read = (
                opened_after_read.st_dev,
                opened_after_read.st_ino,
                opened_after_read.st_size,
                opened_after_read.st_mtime_ns,
                opened_after_read.st_ctime_ns,
            )
            if stable_before != stable_after_read:
                raise OSError("Bundled lsfg-vk archive changed during payload read")
        return payload

    def _read_engine_state(self) -> Optional[Dict[str, Any]]:
        """Return the plugin-managed payload record, if one exists."""
        from .state_transaction import read_bytes_nofollow

        try:
            state = json.loads(read_bytes_nofollow(self.engine_state_file).decode("utf-8"))
            if not isinstance(state, dict):
                return None
            if not all(isinstance(state.get(key), str) and state[key] for key in ("archive", "version", "sha256hash")):
                return None
            return state
        except FileNotFoundError:
            return None

    @staticmethod
    def _regular_file_exists_nofollow(path: Path) -> bool:
        """Inspect a managed file across the coordinator's nofollow boundary."""
        from .state_transaction import regular_file_exists_nofollow

        return regular_file_exists_nofollow(path)
    
    def _extract_and_install_files(self, archive_path: Path) -> None:
        """Install the layer, manifest, and optional CLI from an upstream tar.xz.
        
        Args:
            archive_path: Path to the tar.xz archive to extract
            
        Raises:
            tarfile.TarError: If the archive is corrupted
            OSError: If file operations fail
        """
        required_destinations = {
            f"lib/{LIB_FILENAME}": self.lib_file,
            f"share/vulkan/implicit_layer.d/{JSON_FILENAME}": self.json_file,
        }
        optional_32bit_destinations = {
            f"lib32/{LIB_FILENAME}": self.lib32_file,
            f"share/vulkan/implicit_layer.d/{JSON32_FILENAME}": self.json32_file,
        }
        destinations = {**required_destinations, **optional_32bit_destinations}
        with tarfile.open(archive_path, "r:xz") as archive:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                staged_files = {}
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    member_path = member.name.removeprefix("./")
                    filename = Path(member_path).name
                    destination = destinations.get(member_path)
                    if filename == CLI_FILENAME:
                        destination = self.cli_file
                    if destination is None:
                        continue
                    source = archive.extractfile(member)
                    if source is None:
                        continue
                    # Use a generated staging name rather than the archive path;
                    # this also keeps the two same-named architecture libraries
                    # separate without trusting member path traversal.
                    temp_file = temp_path / f"{len(staged_files)}-{filename}"
                    with source, temp_file.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    staged_files[destination] = (temp_file, filename)

                missing = [
                    str(path) for path in required_destinations.values()
                    if path not in staged_files
                ]
                if missing:
                    raise OSError(
                        "Archive did not contain required lsfg-vk files: "
                        + ", ".join(missing)
                    )

                has_32bit_library = self.lib32_file in staged_files
                has_32bit_manifest = self.json32_file in staged_files
                if has_32bit_library != has_32bit_manifest:
                    raise OSError(
                        "Archive contained an incomplete 32-bit Vulkan layer pair"
                    )

                layer_binaries = [staged_files[self.lib_file][0]]
                if has_32bit_library:
                    layer_binaries.append(staged_files[self.lib32_file][0])
                self._validate_layer_binary_identity(*layer_binaries)

                for destination, (temp_file, filename) in staged_files.items():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if filename == JSON_FILENAME:
                        self._copy_and_fix_json_file(
                            temp_file, destination, "../../lib/liblsfg-vk-layer.so", "64"
                        )
                    elif filename == JSON32_FILENAME:
                        self._copy_and_fix_json_file(
                            temp_file, destination, "../../lib32/liblsfg-vk-layer.so", "32"
                        )
                    else:
                        shutil.copy2(temp_file, destination)
                        if filename == CLI_FILENAME:
                            destination.chmod(0o755)
                    self.log.info("Installed %s to %s", filename, destination)

                if not has_32bit_library:
                    # A 64-bit-only local test package must not leave a stale
                    # 32-bit layer from an older install discoverable.
                    self._remove_if_exists(self.lib32_file)
                    self._remove_if_exists(self.json32_file)

    @staticmethod
    def _validate_layer_binary_identity(*layer_binaries: Path) -> None:
        """Reject payloads that cannot prove they are the isolated build."""
        for layer_binary in layer_binaries:
            if EXPERIMENTAL_LAYER_BUILD_MARKER not in layer_binary.read_bytes():
                raise OSError(
                    f"Experimental layer build marker is missing from {layer_binary}"
                )
    
    def _copy_and_fix_json_file(
            self, src_file: Path, dst_file: Path,
            library_path: str, library_arch: str) -> None:
        """Copy a JSON manifest and point it at the private architecture path.
        
        Args:
            src_file: Source JSON file path
            dst_file: Destination JSON file path
        """
        try:
            with src_file.open("r", encoding="utf-8") as source:
                json_data = json.load(source)
            layer = json_data.get("layer")
            if not isinstance(layer, dict) or not isinstance(layer.get("library_path"), str):
                raise ValueError("missing layer.library_path")

            layer["name"] = EXPERIMENTAL_LAYER_NAME
            layer["description"] = "Lossless Scaling experimental frame generation layer"
            layer["library_path"] = library_path
            layer["library_arch"] = library_arch
            layer["enable_environment"] = {
                EXPERIMENTAL_LAYER_ENABLE_ENV: "1",
            }
            layer["disable_environment"] = {
                EXPERIMENTAL_LAYER_DISABLE_ENV: "1",
            }
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{dst_file.name}.",
                dir=dst_file.parent,
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(file_descriptor, "w", encoding="utf-8") as output:
                    json.dump(json_data, output, indent=2)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
                temporary_path.chmod(0o644)
                temporary_path.replace(dst_file)
            finally:
                temporary_path.unlink(missing_ok=True)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
            raise OSError(f"Invalid Vulkan layer manifest {src_file}: {error}") from error

    def _register_layer_manifests(self) -> None:
        """Register gated manifests without activating the private layer globally."""
        self.user_vulkan_layer_dir.mkdir(parents=True, exist_ok=True)
        self._copy_and_fix_json_file(
            self.json_file,
            self.registered_json_file,
            str(self.lib_file),
            "64",
        )
        if self.lib32_file.exists() and self.json32_file.exists():
            self._copy_and_fix_json_file(
                self.json32_file,
                self.registered_json32_file,
                str(self.lib32_file),
                "32",
            )
        else:
            self._remove_if_exists(self.registered_json32_file)

    def remove_obsolete_hdr_meta_layer_if_needed(self) -> bool:
        """Remove the retired format-22 explicit HDR meta-layer."""
        from . import state_transaction

        layout = state_transaction.PathLayout.from_home(self.user_home)
        if not state_transaction.regular_file_exists_nofollow(
            layout.obsolete_hdr_manifest
        ):
            return False
        coordinator = state_transaction.MutationCoordinator(layout)
        recovery = coordinator.recover()
        if recovery.refresh_required:
            raise OSError("recovered interrupted state; refresh before retrying")
        result = coordinator.commit(
            "migration", replacements={}, removals=(layout.obsolete_hdr_manifest,)
        )
        if result.refresh_required or not result.committed:
            raise OSError("obsolete HDR manifest removal did not commit")
        if result.warning:
            self.log.warning(result.warning)
        return True

    def _remove_legacy_private_manifests(self) -> None:
        """Remove only obsolete manifests inside this plugin's private directory."""
        for filename in LEGACY_PRIVATE_JSON_FILENAMES:
            self._remove_if_exists(self.local_share_dir / filename)
    
    def _create_config_file(self) -> None:
        """Create or update this plugin's private TOML config with detected DLL path.
        
        If a config file already exists, preserve existing profiles and only update global settings like DLL path.
        """
        # Import here to avoid circular imports
        from .dll_detection import DllDetectionService
        
        # Try to detect DLL path
        dll_service = DllDetectionService(self.log)
        
        # Check if config file already exists
        if self.config_file_path.exists():
            try:
                # Read existing config to preserve user profiles
                content = self.config_file_path.read_text(encoding='utf-8')
                existing_profile_data = ConfigurationManager.parse_toml_content_multi_profile(content)
                self.log.info("Found existing config file, preserving user profiles")
                
                # Create merged profile data that preserves user settings but adds any new fields
                merged_profile_data = self._merge_config_with_defaults(existing_profile_data, dll_service)
                
                # Generate TOML content with merged profiles
                toml_content = ConfigurationManager.generate_toml_content_multi_profile(merged_profile_data)
                
            except Exception as e:
                self.log.warning(f"Failed to parse existing config file: {str(e)}, creating new one")
                # Fall back to creating a new config file
                config = ConfigurationManager.get_defaults_with_dll_detection(dll_service)
                toml_content = ConfigurationManager.generate_toml_content(config)
        else:
            # No existing config file, create a new one with defaults
            config = ConfigurationManager.get_defaults_with_dll_detection(dll_service)
            toml_content = ConfigurationManager.generate_toml_content(config)
            self.log.info("Creating new config file")
        
        # Write config file
        self._write_file(self.config_file_path, toml_content, 0o644)
        self.log.info(f"Created config file at {self.config_file_path}")
        
        # Log detected DLL path if found - USE GENERATED CONSTANTS
        from .config_schema_generated import DLL
        try:
            # Try to parse the written content to get the DLL path
            final_content = self.config_file_path.read_text(encoding='utf-8')
            final_config = ConfigurationManager.parse_toml_content(final_content)
            if final_config.get(DLL):
                self.log.info(f"Configured DLL path: {final_config[DLL]}")
        except (OSError, IOError, ValueError, KeyError) as e:
            # Don't fail installation if we can't log the DLL path
            self.log.debug(f"Could not log DLL path: {e}")
    
    def _create_lsfg_launch_script(self) -> None:
        """Create the isolated per-game launch script using the active profile."""
        # The configuration file is created or merged immediately before this
        # method runs. Rebuild from it rather than from defaults so an engine
        # reinstall does not silently reset the generated wrapper's settings.
        from .configuration import ConfigurationService
        config_service = ConfigurationService(logger=self.log)
        config_service.user_home = self.user_home
        config_service.local_share_dir = self.local_share_dir
        config_service.config_dir = self.config_dir
        config_service.config_file_path = self.config_file_path
        config_service.lsfg_script_path = self.lsfg_launch_script_path

        profile_data = config_service._get_profile_data()
        script_content = config_service._generate_script_content_for_profile(profile_data)
        
        # Write the script file
        self._write_file(self.lsfg_launch_script_path, script_content, 0o755)
        self.log.info(f"Created lsfg launch script at {self.lsfg_launch_script_path}")

    def _install_diagnostics_helper(self, plugin_dir: Path) -> None:
        """Install the packaged read-only diagnostic filter beside the wrapper."""
        source = self._diagnostics_helper_source(plugin_dir)
        self.diagnostics_script_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, self.diagnostics_script_path)
        self.diagnostics_script_path.chmod(0o755)
        self.log.info("Installed diagnostics helper to %s", self.diagnostics_script_path)

    @staticmethod
    def _diagnostics_helper_source(plugin_dir: Path) -> Path:
        """Resolve the release-ZIP helper, with a source-tree development fallback."""
        candidates = (
            plugin_dir / BIN_DIR / DIAGNOSTICS_HELPER_FILENAME,
            plugin_dir / "scripts" / DIAGNOSTICS_HELPER_FILENAME,
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise OSError(f"Bundled diagnostics helper not found at {candidates[0]}")

    def migrate_diagnostics_helper_if_needed(self) -> bool:
        """Install or refresh the helper without requiring an engine reinstall."""
        from . import state_transaction

        plugin_dir = Path(__file__).parent.parent.parent
        source = self._diagnostics_helper_source(plugin_dir)
        bundled = source.read_bytes()
        try:
            current = self.diagnostics_script_path.read_bytes()
            executable = bool(self.diagnostics_script_path.stat().st_mode & 0o111)
            if current == bundled and executable:
                return False
        except OSError:
            pass

        layout = state_transaction.PathLayout.from_home(self.user_home)
        if self.diagnostics_script_path != layout.diagnostics_helper:
            # Preserve the service's established injectable destination seam.
            layout = replace(
                state_transaction.PathLayout.from_home(
                    self.diagnostics_script_path.parent
                ),
                diagnostics_helper=self.diagnostics_script_path,
            )
        coordinator = state_transaction.MutationCoordinator(layout)
        with coordinator.locked("migration"):
            recovery = coordinator.recover()
            if recovery.refresh_required:
                raise OSError("recovered interrupted state; refresh before retrying")
            result = coordinator.commit(
                "migration",
                replacements={layout.diagnostics_helper: (bundled, 0o755)},
                removals=(),
            )
            if result.refresh_required:
                raise OSError("recovered interrupted state; refresh before retrying")
            if not result.committed:
                raise OSError("diagnostics helper migration did not commit")
            if result.warning:
                self.log.warning(result.warning)
        return True
    
    def get_launch_script_path(self) -> str:
        """Get the path to the lsfg launch script
        
        Returns:
            String path to the launch script file
        """
        return str(self.lsfg_launch_script_path)

    def check_installation(self) -> InstallationCheckResponse:
        """Check if lsfg-vk is already installed
        
        Returns:
            InstallationCheckResponse with installation status and file paths
        """
        from . import state_transaction

        layout = state_transaction.PathLayout.from_home(self.user_home)
        try:
            with state_transaction.read_only_guard(layout):
                inspect = self._regular_file_exists_nofollow
                lib_exists = inspect(self.lib_file)
                lib32_exists = inspect(self.lib32_file)
                json_exists = inspect(self.json_file)
                json32_exists = inspect(self.json32_file)
                registered_json_exists = inspect(self.registered_json_file)
                registered_json32_exists = inspect(self.registered_json32_file)
                script_exists = inspect(self.lsfg_launch_script_path)
                engine_state_exists = inspect(self.engine_state_file)
                installed = (
                    lib_exists and json_exists and registered_json_exists
                    and script_exists
                )
                expected = self._bundled_archive_metadata(Path(__file__).parent.parent.parent)
                expects_32bit = "32" in expected.get("architectures", ["64", "32"])
                installed = installed and (
                    not expects_32bit
                    or (lib32_exists and json32_exists and registered_json32_exists)
                )
                state = self._read_engine_state() if engine_state_exists else None
                version_known = state is not None
                installed_version = state["version"] if state else None
                update_required = installed and (
                    state is None
                    or state["version"] != expected["version"]
                    or state["sha256hash"] != expected["sha256hash"]
                )
            
            self.log.info(
                "Installation check: lib64=%s, lib32=%s, private-json64=%s, "
                "private-json32=%s, registered-json64=%s, registered-json32=%s, "
                "script=%s",
                lib_exists, lib32_exists, json_exists, json32_exists,
                registered_json_exists, registered_json32_exists,
                script_exists,
            )
            
            return {
                "status_available": True,
                "installed": installed,
                "lib_exists": lib_exists,
                "json_exists": json_exists,
                "script_exists": script_exists,
                "lib_path": str(self.lib_file),
                "json_path": str(self.registered_json_file),
                "script_path": str(self.lsfg_launch_script_path),
                "installed_engine_version": installed_version,
                "expected_engine_version": expected["version"],
                "engine_version_known": version_known,
                "engine_update_required": update_required,
                "error": None
            }

        except state_transaction.MutationBusyError as error:
            return self._unavailable_installation_status(
                "mutation_busy", str(error), retryable=True,
                recovery_pending=False, recovery_action="refresh",
            )
        except state_transaction.RecoveryPendingError as error:
            return self._unavailable_installation_status(
                "recovery_pending", str(error), retryable=False,
                recovery_pending=True, recovery_action="wait_for_recovery",
            )
        except state_transaction.MutationBlockedError as error:
            return self._unavailable_installation_status(
                "recovery_blocked", str(error), retryable=False,
                recovery_pending=True, recovery_action="repair_required",
            )
        except Exception as e:
            error_msg = f"Error checking lsfg-vk installation: {str(e)}"
            self.log.error(error_msg)
            return self._unavailable_installation_status(
                "recovery_blocked", error_msg, retryable=False,
                recovery_pending=True, recovery_action="repair_required",
            )

    def _unavailable_installation_status(
        self, error_code: str, warning: str, *, retryable: bool,
        recovery_pending: bool, recovery_action: str,
    ) -> InstallationCheckResponse:
        return {
            "status_available": False,
            "installed": True,
            "lib_exists": False,
            "json_exists": False,
            "script_exists": False,
            "lib_path": str(self.lib_file),
            "json_path": str(self.registered_json_file),
            "script_path": str(self.lsfg_launch_script_path),
            "installed_engine_version": None,
            "expected_engine_version": None,
            "engine_version_known": False,
            "engine_update_required": False,
            "error": warning,
            "error_code": error_code,
            "retryable": retryable,
            "recovery_pending": recovery_pending,
            "warning": warning,
            "recovery_action": recovery_action,
        }
    
    def uninstall(self) -> UninstallationResponse:
        """Deactivate and remove plugin-owned engine files transactionally."""
        return self._uninstall_transactionally(continue_after_recovery=False)

    def _uninstall_transactionally(
        self, *, continue_after_recovery: bool
    ) -> UninstallationResponse:
        """Recover under the uninstall lock, then optionally continue cleanup."""
        from . import state_transaction

        layout = state_transaction.PathLayout.from_home(self.user_home)
        coordinator = state_transaction.MutationCoordinator(layout)
        try:
            with coordinator.locked("uninstall"):
                recovery = coordinator.recover()
                if recovery.refresh_required and not continue_after_recovery:
                    return self._lifecycle_error(
                        UninstallationResponse,
                        "Recovered interrupted state; refresh before retrying",
                        "refresh_required",
                        removed_files=None,
                    )
                order = (
                    layout.registered_manifest64,
                    layout.registered_manifest32,
                    layout.private_library64,
                    layout.private_library32,
                    layout.private_manifest64,
                    layout.private_manifest32,
                    layout.obsolete_hdr_manifest,
                    layout.cli,
                    layout.launcher,
                    layout.diagnostics_helper,
                    *layout.legacy_private_manifests,
                    layout.engine_state,
                )
                removed = []
                steps = []
                for path in order:
                    try:
                        metadata = path.lstat()
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        raise state_transaction.MutationBlockedError(
                            f"managed target is not a regular file: {path}"
                        )
                    removed.append(str(path))
                    steps.append((path, "remove", None, 0))
                if not steps:
                    return self._success_response(
                        UninstallationResponse,
                        "No lsfg-vk files found to remove",
                        removed_files=None,
                        retryable=False,
                        recovery_pending=False,
                        recovery_action="none",
                        warning=None,
                    )
                result = coordinator.commit(
                    "uninstall", replacements={}, removals=(), ordered_steps=steps
                )
                return self._success_response(
                    UninstallationResponse,
                    f"lsfg-vk uninstalled successfully. Removed {len(removed)} files.",
                    removed_files=removed,
                    retryable=False,
                    recovery_pending=result.recovery_pending,
                    recovery_action=(
                        "wait_for_recovery" if result.recovery_pending else "none"
                    ),
                    warning=result.warning,
                    **({"error_code": "recovery_pending"} if result.recovery_pending else {}),
                )
        except state_transaction.MutationBusyError as error:
            return self._lifecycle_error(
                UninstallationResponse, error, "mutation_busy", removed_files=None
            )
        except state_transaction.MutationBlockedError as error:
            return self._lifecycle_error(
                UninstallationResponse, error, "recovery_blocked", removed_files=None
            )
        except OSError as error:
            return self._lifecycle_error(
                UninstallationResponse, error, "durability_failure", removed_files=None
            )

    def cleanup_on_uninstall(self) -> UninstallationResponse:
        """Clean up lsfg-vk files when the plugin is uninstalled
        
        Note: The config file (conf.toml) is preserved to maintain user's custom profiles
        """
        # Decky is removing the plugin itself, so there may be no later UI retry.
        # Recover a known journal and continue the uninstall while retaining the
        # same outer uninstall lock. Interactive uninstall intentionally keeps
        # its refresh barrier instead.
        result = self._uninstall_transactionally(continue_after_recovery=True)
        if result.get("success"):
            self.log.info(result.get("message", "Transactional uninstall completed"))
        else:
            self.log.error("Transactional uninstall cleanup failed: %s", result.get("error"))
        return result

    def recover_state(self) -> Dict[str, Any]:
        """Explicitly recover a pending transaction for the frontend barrier."""
        from . import state_transaction

        layout = state_transaction.PathLayout.from_home(self.user_home)
        coordinator = state_transaction.MutationCoordinator(layout)
        try:
            recovery = coordinator.recover()
            return self._success_response(
                dict,
                "State recovery completed",
                status_available=True,
                recovered=recovery.refresh_required,
                refresh_required=True,
                retryable=False,
                recovery_pending=False,
                recovery_action="refresh",
                warning=None,
            )
        except state_transaction.MutationBusyError as error:
            return self._lifecycle_error(
                dict, error, "mutation_busy", status_available=False
            )
        except state_transaction.MutationBlockedError as error:
            return self._lifecycle_error(
                dict,
                error,
                "recovery_blocked",
                status_available=False,
                recovery_pending=True,
            )
        except OSError as error:
            return self._lifecycle_error(
                dict,
                error,
                "durability_failure",
                status_available=False,
                recovery_pending=True,
                recovery_action="repair_required",
            )

    def _merge_config_with_defaults(self, existing_profile_data, dll_service):
        """Merge existing user config with current schema defaults
        
        This ensures that:
        1. User's custom profiles and values are preserved
        2. Any new fields added to the schema get their default values
        3. Global settings like DLL path are updated as needed
        
        Args:
            existing_profile_data: The user's existing ProfileData
            dll_service: DLL detection service for updating DLL path
            
        Returns:
            ProfileData with merged configuration
        """
        from .config_schema import ProfileData
        
        # Get current schema defaults
        default_config = ConfigurationManager.get_defaults_with_dll_detection(dll_service)
        default_global_config = {
            "dll": default_config.get("dll", ""),
            "allow_fp16": default_config.get("allow_fp16", True)
        }
        
        # Start with existing data
        merged_data: ProfileData = {
            "current_profile": existing_profile_data.get("current_profile", "decky-lsfg-vk"),
            "global_config": existing_profile_data.get("global_config", {}).copy(),
            "profiles": {}
        }
        
        # Merge global config: preserve user values, add missing fields, update DLL
        for key, default_value in default_global_config.items():
            if key not in merged_data["global_config"]:
                merged_data["global_config"][key] = default_value
                self.log.info(f"Added missing global field '{key}' with default value: {default_value}")
        
        # Update DLL path if detected
        dll_result = dll_service.check_lossless_scaling_dll()
        if dll_result.get("detected") and dll_result.get("path"):
            old_dll = merged_data["global_config"].get("dll")
            merged_data["global_config"]["dll"] = dll_result["path"]
            if old_dll != dll_result["path"]:
                self.log.info(f"Updated DLL path from '{old_dll}' to: {dll_result['path']}")
        elif merged_data["global_config"].get("dll") == "/games/Lossless Scaling/Lossless.dll":
            # Releases before 0.13.0-experimental.2 wrote this placeholder when
            # detection failed. Removing a nonexistent placeholder lets lsfg-vk
            # use its own automatic discovery instead.
            legacy_path = Path("/games/Lossless Scaling/Lossless.dll")
            if not legacy_path.exists():
                merged_data["global_config"]["dll"] = ""
                self.log.info("Removed obsolete Lossless.dll placeholder to enable upstream automatic discovery")
        
        # Merge each profile: preserve user values, add missing fields
        existing_profiles = existing_profile_data.get("profiles", {})
        
        for profile_name, existing_profile_config in existing_profiles.items():
            merged_profile_config = existing_profile_config.copy()
            
            # Add any missing fields from current schema with default values
            added_fields = []
            for key, default_value in default_config.items():
                if key not in merged_profile_config and key not in ["dll", "allow_fp16"]:  # Skip global fields
                    merged_profile_config[key] = default_value
                    added_fields.append(key)
            
            if added_fields:
                self.log.info(f"Profile '{profile_name}': Added missing fields {added_fields}")
            
            merged_data["profiles"][profile_name] = merged_profile_config
        
        # If no profiles exist, create the default one
        if not merged_data["profiles"]:
            merged_data["profiles"]["decky-lsfg-vk"] = {
                k: v for k, v in default_config.items() 
                if k not in ["dll", "allow_fp16"]  # Exclude global fields
            }
            merged_data["current_profile"] = "decky-lsfg-vk"
            self.log.info("No existing profiles found, created default profile")
        
        return merged_data
