"""Configuration service for TOML-based lsfg configuration management."""

import json
from pathlib import Path
import shlex
from typing import Any, Callable, Dict, Tuple

from .base_service import BaseService
from .config_schema import (
    ConfigurationManager,
    CONFIG_SCHEMA,
    SCRIPT_ONLY_FIELDS,
    ProfileData,
    DEFAULT_PROFILE_NAME,
)
from .config_schema_generated import (
    ConfigurationData,
    DISABLE_HDR_EXPOSURE,
    get_script_generation_logic,
)
from .constants import (
    ARMADA_DEVICE_ENV,
    ARMADA_GAME_LAUNCH,
    EXPERIMENTAL_LAYER_ENABLE_ENV,
    FLATPAK_GAMESCOPE_IMPLICIT_LAYER_DIR,
    FLATPAK_IMPLICIT_LAYER_DIR,
    PRESENT_ACQUIRE_TIMEOUT_MS,
)
from .types import ConfigurationResponse, ProfilesResponse, ProfileResponse


class ConfigurationService(BaseService):
    """Service for managing TOML-based lsfg configuration"""

    _WRAPPER_FORMAT_MARKER = "# decky-lsfg-vk-experimental-wrapper-format: 27"
    _WRAPPER_PROFILE_SETTINGS_VERSION = 1
    _REQUIRED_WRAPPER_EXPORTS = (
        "export LSFGVK_PRESENT_ACQUIRE_TIMEOUT_MS=",
        f"export {EXPERIMENTAL_LAYER_ENABLE_ENV}=1",
        "export DISABLE_LSFGVK=1",
        "export DISABLE_LSFG=1",
        "lsfgvk_diagnostics_default=",
    )
    _OBSOLETE_WRAPPER_EXPORTS = (
        "PROTON_USE_WOW64",
        "LSFGVK_PRESENT_RECOVERY_RECREATE",
        "LSFGVK_EXPERIMENTAL_HDR",
        "VK_INSTANCE_LAYERS",
        "VK_LAYER_DECKY_LSFGVK_experimental_hdr_stack_x86_64",
    )

    @staticmethod
    def _wrapper_settings_defaults() -> Dict[str, Any]:
        return {
            field_name: CONFIG_SCHEMA[field_name].default
            for field_name in SCRIPT_ONLY_FIELDS
        }

    @staticmethod
    def _normalize_wrapper_settings(raw_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Decky-only wrapper settings without polluting engine TOML."""
        candidate = ConfigurationManager.get_defaults()
        candidate.update({
            field_name: raw_settings[field_name]
            for field_name in SCRIPT_ONLY_FIELDS
            if field_name in raw_settings
        })
        validated = ConfigurationManager.validate_config(candidate)
        # HDR remains an engine foundation in this release, not a supported
        # Decky launch mode. Override old per-profile opt-ins as well as new UI
        # writes so the generated wrapper always retains the proven SDR path.
        validated[DISABLE_HDR_EXPOSURE] = True
        return {
            field_name: validated[field_name]
            for field_name in SCRIPT_ONLY_FIELDS
        }

    def _read_wrapper_profile_settings(self) -> Dict[str, Dict[str, Any]]:
        """Read persisted per-profile launcher settings, falling back safely."""
        try:
            content = self._read_managed_text(self.wrapper_profile_settings_path)
        except FileNotFoundError:
            return {}

        try:
            raw_data = json.loads(content)
            if not isinstance(raw_data, dict):
                raise ValueError("wrapper settings must be a JSON object")
            raw_profiles = raw_data.get("profiles", {})
            if not isinstance(raw_profiles, dict):
                raise ValueError("wrapper settings profiles must be an object")
            settings: Dict[str, Dict[str, Any]] = {}
            for profile_name, raw_settings in raw_profiles.items():
                if isinstance(profile_name, str) and isinstance(raw_settings, dict):
                    settings[profile_name] = self._normalize_wrapper_settings(raw_settings)
            return settings
        except (OSError, IOError, ValueError, TypeError, json.JSONDecodeError) as error:
            self.log.warning(
                "Ignoring invalid per-profile wrapper settings at %s: %s",
                self.wrapper_profile_settings_path,
                error,
            )
            return {}

    def _read_wrapper_profile_settings_strict(self) -> Dict[str, Dict[str, Any]]:
        """Read mutation input without repairing or defaulting invalid state."""
        try:
            content = self._read_managed_text(self.wrapper_profile_settings_path)
        except FileNotFoundError:
            return {}

        raw_data = json.loads(content)
        if not isinstance(raw_data, dict):
            raise ValueError("wrapper settings must be a JSON object")
        unknown_document_keys = set(raw_data) - {"version", "profiles"}
        if unknown_document_keys:
            raise ValueError("wrapper settings contain unknown document fields")
        version = raw_data.get("version")
        if (
            type(version) is not int
            or version != self._WRAPPER_PROFILE_SETTINGS_VERSION
        ):
            raise ValueError("unsupported wrapper settings version")
        raw_profiles = raw_data.get("profiles")
        if not isinstance(raw_profiles, dict):
            raise ValueError("wrapper settings profiles must be an object")

        settings: Dict[str, Dict[str, Any]] = {}
        for profile_name, raw_settings in raw_profiles.items():
            if not isinstance(profile_name, str) or not isinstance(raw_settings, dict):
                raise ValueError("wrapper settings contain an invalid profile entry")
            unknown_fields = set(raw_settings) - SCRIPT_ONLY_FIELDS
            if unknown_fields:
                raise ValueError("wrapper settings contain unknown profile fields")
            for field_name, value in raw_settings.items():
                expected_type = type(CONFIG_SCHEMA[field_name].default)
                if type(value) is not expected_type:
                    raise ValueError(
                        f"wrapper setting '{field_name}' has the wrong primitive type"
                    )
            settings[profile_name] = self._normalize_wrapper_settings(raw_settings)
        return settings

    def _write_wrapper_profile_settings(
            self, profile_settings: Dict[str, Dict[str, Any]]) -> None:
        normalized_profiles = {
            profile_name: self._normalize_wrapper_settings(settings)
            for profile_name, settings in profile_settings.items()
        }
        payload = {
            "version": self._WRAPPER_PROFILE_SETTINGS_VERSION,
            "profiles": normalized_profiles,
        }
        self._commit_managed_replacements(
            "migration",
            {
                self.wrapper_profile_settings_path: (
                    (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
                    0o644,
                )
            },
        )

    @staticmethod
    def _read_managed_text(path: Path) -> str:
        from .state_transaction import read_bytes_nofollow

        return read_bytes_nofollow(path).decode("utf-8")

    def _commit_managed_replacements(
            self,
            operation: str,
            replacements: Dict[Path, Tuple[bytes, int]],
    ) -> Any:
        """Apply a partial legacy/migration writer through the coordinator."""
        from .state_transaction import MutationCoordinator, PathLayout

        coordinator = MutationCoordinator(PathLayout.from_home(self.user_home))
        recovery = coordinator.recover()
        if recovery.refresh_required:
            raise OSError("recovered interrupted state; refresh before retrying")
        result = coordinator.commit(operation, replacements=replacements, removals=())
        if result.refresh_required:
            raise OSError("recovered interrupted state; refresh before retrying")
        if not result.committed:
            raise OSError("managed state replacement did not commit")
        if result.warning:
            self.log.warning(result.warning)
        return result

    def _wrapper_settings_for_profile(
            self,
            profile_name: str,
            profile_settings: Dict[str, Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        settings = self._wrapper_settings_defaults()
        settings_by_profile = (
            profile_settings
            if profile_settings is not None
            else self._read_wrapper_profile_settings()
        )
        stored_settings = settings_by_profile.get(profile_name)
        if stored_settings:
            settings.update(stored_settings)
        return self._normalize_wrapper_settings(settings)

    def _config_for_profile(
            self,
            profile_data: ProfileData,
            profile_name: str,
            profile_settings: Dict[str, Dict[str, Any]] = None,
    ) -> ConfigurationData:
        """Merge lsfg-vk TOML, global, and Decky wrapper fields for one profile."""
        config = dict(
            profile_data["profiles"].get(
                profile_name, ConfigurationManager.get_defaults()
            )
        )
        config.update(profile_data["global_config"])
        config.update(self._wrapper_settings_for_profile(profile_name, profile_settings))
        return ConfigurationManager.validate_config(config)

    def _load_effective_state_strict(
            self) -> Tuple[ProfileData, Dict[str, Dict[str, Any]]]:
        """Load every persisted mutation input strictly, without side effects."""
        profile_data = self._get_profile_data()
        profile_settings = self._read_wrapper_profile_settings_strict()
        self._validate_wrapper_profile_set(profile_data, profile_settings)
        return profile_data, profile_settings

    def _validate_wrapper_profile_set(
            self,
            profile_data: ProfileData,
            profile_settings: Dict[str, Dict[str, Any]],
    ) -> None:
        """Require an existing wrapper document to cover exactly the TOML profiles."""
        from .state_transaction import regular_file_exists_nofollow

        if regular_file_exists_nofollow(self.wrapper_profile_settings_path):
            configured_profiles = set(profile_data["profiles"])
            wrapper_profiles = set(profile_settings)
            if wrapper_profiles != configured_profiles:
                raise ValueError(
                    "wrapper settings profile set does not match configuration profiles"
                )

    def _render_effective_state(
            self,
            profile_data: ProfileData,
            profile_settings: Dict[str, Dict[str, Any]],
    ) -> Dict[Path, Tuple[bytes, int]]:
        """Render the complete logical configuration snapshot before applying it."""
        normalized_settings = {
            profile_name: self._wrapper_settings_for_profile(
                profile_name, profile_settings
            )
            for profile_name in profile_data["profiles"]
        }
        wrapper_payload = {
            "version": self._WRAPPER_PROFILE_SETTINGS_VERSION,
            "profiles": normalized_settings,
        }
        toml_content = ConfigurationManager.generate_toml_content_multi_profile(
            profile_data
        )
        wrapper_content = json.dumps(
            wrapper_payload, indent=2, sort_keys=True
        ) + "\n"
        launcher_content = self._generate_script_content_for_profile(
            profile_data, normalized_settings
        )
        return {
            self.config_file_path: (toml_content.encode("utf-8"), 0o644),
            self.wrapper_profile_settings_path: (
                wrapper_content.encode("utf-8"), 0o644
            ),
            self.lsfg_script_path: (launcher_content.encode("utf-8"), 0o755),
        }

    def _configuration_error(
            self,
            response_type: type,
            error: Exception | str,
            error_code: str,
            **kwargs: Any,
    ) -> Any:
        return self._error_response(
            response_type,
            str(error),
            error_code=error_code,
            retryable=error_code == "mutation_busy",
            recovery_pending=error_code == "recovery_blocked",
            recovery_action=self._recovery_action_for_error(error_code),
            warning=None,
            **kwargs,
        )

    def _commit_effective_state(
            self,
            response_type: type,
            transform: Callable[
                [ProfileData, Dict[str, Dict[str, Any]]], Dict[str, Any]
            ],
            success_message: Callable[[Dict[str, Any]], str],
            failure_kwargs: Dict[str, Any],
    ) -> Any:
        """Serialize one strict full-snapshot profile mutation."""
        from .state_transaction import (
            MutationBlockedError,
            MutationBusyError,
            MutationCoordinator,
            PathLayout,
        )

        coordinator = MutationCoordinator(PathLayout.from_home(self.user_home))
        try:
            with coordinator.locked("configuration"):
                recovery = coordinator.recover()
                if recovery.refresh_required:
                    return self._configuration_error(
                        response_type,
                        "Recovered interrupted state; refresh before retrying",
                        "refresh_required",
                        **failure_kwargs,
                    )

                try:
                    profile_data, profile_settings = (
                        self._load_effective_state_strict()
                    )
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                    return self._configuration_error(
                        response_type,
                        error,
                        "invalid_persisted_state",
                        **failure_kwargs,
                    )

                try:
                    response_values = transform(profile_data, profile_settings)
                except ValueError as error:
                    return self._error_response(
                        response_type, str(error), **failure_kwargs
                    )

                try:
                    replacements = self._render_effective_state(
                        profile_data, profile_settings
                    )
                except Exception as error:
                    return self._configuration_error(
                        response_type,
                        error,
                        "durability_failure",
                        **failure_kwargs,
                    )

                result = coordinator.commit(
                    "configuration", replacements=replacements, removals=()
                )
                if result.refresh_required or not result.committed:
                    return self._configuration_error(
                        response_type,
                        "Recovered interrupted state; refresh before retrying",
                        "refresh_required",
                        **failure_kwargs,
                    )
                recovery_metadata = {
                    "retryable": False,
                    "recovery_pending": result.recovery_pending,
                    "warning": result.warning,
                    "recovery_action": (
                        "wait_for_recovery"
                        if result.recovery_pending
                        else "none"
                    ),
                }
                if result.recovery_pending:
                    recovery_metadata["error_code"] = "recovery_pending"
                return self._success_response(
                    response_type,
                    success_message(response_values),
                    **response_values,
                    **recovery_metadata,
                )
        except MutationBusyError as error:
            return self._configuration_error(
                response_type, error, "mutation_busy", **failure_kwargs
            )
        except MutationBlockedError as error:
            return self._configuration_error(
                response_type, error, "recovery_blocked", **failure_kwargs
            )
        except Exception as error:
            return self._configuration_error(
                response_type, error, "durability_failure", **failure_kwargs
            )

    def migrate_wrapper_profile_settings_if_needed(self) -> bool:
        """Preserve old current-wrapper compatibility settings on first upgrade.

        Older releases stored these values only in the generated launcher. Import
        them for the selected profile and give every other existing profile the
        documented wrapper defaults so the migrated snapshot is complete.
        """
        try:
            self._read_managed_text(self.wrapper_profile_settings_path)
            return False
        except FileNotFoundError:
            pass

        try:
            current_script = self._read_managed_text(self.lsfg_script_path)
        except FileNotFoundError:
            return False

        try:
            script_values = ConfigurationManager.parse_script_content(
                current_script
            )
            profile_data = self._get_profile_data()
            profile_settings = {
                profile_name: self._wrapper_settings_defaults()
                for profile_name in profile_data["profiles"]
            }
            profile_settings[profile_data["current_profile"]] = (
                self._normalize_wrapper_settings(script_values)
            )
            self._write_wrapper_profile_settings(profile_settings)
            self.log.info(
                "Migrated wrapper-only settings into profile '%s'",
                profile_data["current_profile"],
            )
            return True
        except (OSError, IOError, ValueError, TypeError) as error:
            self.log.warning("Could not migrate wrapper-only profile settings: %s", error)
            return False

    @staticmethod
    def _has_active_in(config: ConfigurationData) -> bool:
        """Return whether an engine profile can select itself by process name."""
        active_in = config.get("active_in", "")
        if isinstance(active_in, (list, tuple)):
            return bool(active_in)
        return bool(str(active_in).strip())

    @classmethod
    def _profile_selection_lines(
            cls,
            profile_name: str,
            config: ConfigurationData,
            automatic_matching_enabled: bool = None,
    ) -> list[str]:
        """Choose between Decky's selected profile and automatic matching.

        ``LSFGVK_PROFILE`` deliberately overrides lsfg-vk's ``active_in`` matching.
        Keep Decky's selected-profile behaviour for profiles without activation rules,
        but let lsfg-vk perform its native automatic selection when rules are present.
        """
        if automatic_matching_enabled is None:
            automatic_matching_enabled = cls._has_active_in(config)

        if automatic_matching_enabled:
            return [
                "# An active_in profile is configured; lsfg-vk will select a matching profile automatically.",
            ]
        return [f"export LSFGVK_PROFILE={shlex.quote(profile_name)}"]
    
    def get_config(self) -> ConfigurationResponse:
        """Read current TOML configuration merged with launch script environment variables
        
        Returns:
            ConfigurationResponse with current configuration or error
        """
        from . import state_transaction

        layout = state_transaction.PathLayout.from_home(self.user_home)
        try:
            with state_transaction.read_only_guard(layout):
                profile_data, profile_settings = self._load_effective_state_strict()
                config = self._config_for_profile(
                    profile_data,
                    profile_data["current_profile"],
                    profile_settings,
                )
            
            return self._success_response(
                ConfigurationResponse, config=config, status_available=True
            )
            
        except state_transaction.MutationBusyError as e:
            return self._unavailable_read(
                ConfigurationResponse, "mutation_busy", str(e),
                retryable=True, pending=False, action="refresh", config=None,
            )
        except state_transaction.RecoveryPendingError as e:
            return self._unavailable_read(
                ConfigurationResponse, "recovery_pending", str(e),
                retryable=False, pending=True, action="wait_for_recovery", config=None,
            )
        except state_transaction.MutationBlockedError as e:
            return self._unavailable_read(
                ConfigurationResponse, "recovery_blocked", str(e),
                retryable=False, pending=True, action="repair_required", config=None,
            )
        except (OSError, IOError) as e:
            error_msg = f"Error reading lsfg config: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(ConfigurationResponse, str(e), config=None)
        except Exception as e:
            error_msg = f"Error parsing config file: {str(e)}"
            self.log.error(error_msg)
            from .dll_detection import DllDetectionService
            dll_service = DllDetectionService(self.log)
            config = ConfigurationManager.get_defaults_with_dll_detection(dll_service)
            return self._success_response(ConfigurationResponse, 
                                        f"Using default configuration due to parse error: {str(e)}", 
                                        config=config,
                                        error_code="invalid_persisted_state",
                                        retryable=False,
                                        recovery_pending=False,
                                        recovery_action="repair_required",
                                        warning=error_msg,
                                        status_available=True)

    def _unavailable_read(
        self, response_type: type, error_code: str, warning: str, *,
        retryable: bool, pending: bool, action: str, **payload: Any,
    ) -> Any:
        return self._error_response(
            response_type,
            warning,
            status_available=False,
            error_code=error_code,
            retryable=retryable,
            recovery_pending=pending,
            recovery_action=action,
            warning=warning,
            **payload,
        )
    
    def update_config_from_dict(self, config: ConfigurationData) -> ConfigurationResponse:
        """Update TOML configuration from configuration dictionary (eliminates parameter duplication)
        
        Args:
            config: Complete configuration data dictionary
            
        Returns:
            ConfigurationResponse with success status
        """
        return self.update_profile_config(None, config)
    
    def update_lsfg_script(self, config: ConfigurationData) -> ConfigurationResponse:
        """Update the isolated per-game launch script with current configuration
        
        Args:
            config: Configuration data to apply to the script
            
        Returns:
            ConfigurationResponse indicating success or failure
        """
        try:
            script_content = self._generate_script_content(config)
            self._commit_managed_replacements(
                "configuration",
                {self.lsfg_script_path: (script_content.encode(), 0o755)},
            )
            
            self.log.info(f"Updated lsfg launch script at {self.lsfg_script_path}")
            
            return self._success_response(ConfigurationResponse,
                                        "Launch script updated successfully",
                                        config=config)
            
        except Exception as e:
            error_msg = f"Error updating launch script: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(ConfigurationResponse, str(e), config=None)

    def remove_legacy_vkbasalt_exports(self) -> bool:
        """Remove obsolete plugin-managed vkBasalt exports.

        Layer discovery is now preserved, so a separately configured vkBasalt
        installation can work normally. Older plugin versions managed these
        variables directly; remove those stale exports during migration.
        """
        try:
            existing_content = self._read_managed_text(self.lsfg_script_path)
        except FileNotFoundError:
            return False

        legacy_exports = {"DISABLE_VKBASALT", "ENABLE_VKBASALT"}
        existing_lines = existing_content.splitlines()
        cleaned_lines = []
        removed = False

        for line in existing_lines:
            stripped = line.strip()
            if stripped.startswith("export "):
                variable = stripped[len("export "):].split("=", 1)[0].strip()
                if variable in legacy_exports:
                    removed = True
                    continue
            cleaned_lines.append(line)

        if removed:
            self._commit_managed_replacements(
                "migration",
                {
                    self.lsfg_script_path: (
                        ("\n".join(cleaned_lines) + "\n").encode(), 0o755
                    )
                },
            )
        return removed
    
    def _generate_script_content(self, config: ConfigurationData) -> str:
        """Generate the content for the isolated per-game launch script
        
        Args:
            config: Configuration data to apply to the script
            
        Returns:
            The complete script content as a string
        """
        lines = [
            "#!/bin/bash",
            self._WRAPPER_FORMAT_MARKER,
            "# lsfg-vk launch script generated by decky-lsfg-vk-experimental plugin",
            "# This script sets up the environment for lsfg-vk to work with the plugin configuration",
        ]
        
        generate_script_lines = get_script_generation_logic()
        lines.extend(generate_script_lines(config))
        lines.extend(self._experimental_hdr_activation_lines(config))
        lines.extend(self._generate_layer_environment_lines())
        lines.extend(self._profile_selection_lines(DEFAULT_PROFILE_NAME, config))
        lines.extend(self._generate_game_launch_lines())
        
        return "\n".join(lines) + "\n"
    
    def _generate_script_content_for_profile(
            self,
            profile_data: ProfileData,
            profile_settings: Dict[str, Dict[str, Any]] = None,
    ) -> str:
        """Generate the isolated per-game launch script with profile support
        
        Args:
            profile_data: Profile data containing current profile and configurations
            
        Returns:
            The complete script content as a string
        """
        current_profile = profile_data["current_profile"]
        merged_config = self._config_for_profile(
            profile_data, current_profile, profile_settings
        )
        automatic_matching_enabled = any(
            self._has_active_in(profile_config)
            for profile_config in profile_data["profiles"].values()
        )
        
        lines = [
            "#!/bin/bash",
            self._WRAPPER_FORMAT_MARKER,
            f"# Current profile: {current_profile}",
        ]
        
        generate_script_lines = get_script_generation_logic()
        lines.extend(generate_script_lines(merged_config))
        lines.extend(self._experimental_hdr_activation_lines(merged_config))
        lines.extend(self._generate_layer_environment_lines())
        # Never export LSFGVK_PROFILE once any profile uses Active In: the
        # environment override takes precedence over upstream's executable
        # detection and would otherwise make profiles depend on the UI's last
        # selected entry.
        lines.extend(self._profile_selection_lines(
            current_profile,
            merged_config,
            automatic_matching_enabled,
        ))
        lines.extend(self._generate_game_launch_lines())
        
        return "\n".join(lines) + "\n"

    @staticmethod
    def _experimental_hdr_activation_lines(config: Dict[str, Any]) -> list[str]:
        """Keep the packaged Decky launcher on its proven SDR contract.

        The engine contains HDR colour-pipeline groundwork, but cross-game HDR
        activation and presentation are not release-ready. Ignore stale profile
        opt-ins until a later Decky release deliberately unlocks this boundary.
        """
        del config
        return [
            "export LSFGVK_DISABLE_HDR_EXPOSURE=1",
            # Absence is DXVK's established SDR default. Do not replace the
            # launcher's normal Gamescope WSI contract while blocking LSFG's
            # unfinished HDR path.
            "unset DXVK_HDR",
        ]

    def _generate_layer_environment_lines(self) -> list[str]:
        """Activate only the registered experimental layer for this game.

        The same wrapper is used in Steam launch options and as Heroic's
        per-game wrapper command. Host launches use the uniquely named, gated
        manifest installed in Vulkan's normal per-user directory so Pressure
        Vessel can register it before this wrapper starts. Heroic's UMU launch
        path rebuilds the child's Vulkan manifest search from an explicit
        override; use the mounted Flatpak extension as that override so the
        experimental layer survives into the game process. The HDR exposure
        boundary is enforced separately.
        """
        diagnostics_log_path = self.config_dir / "present-diagnostics.log"
        return [
            f'export LSFGVK_PRESENT_ACQUIRE_TIMEOUT_MS="${{LSFGVK_PRESENT_ACQUIRE_TIMEOUT_MS:-{PRESENT_ACQUIRE_TIMEOUT_MS}}}"',
            f"export {EXPERIMENTAL_LAYER_ENABLE_ENV}=1",
            "export DISABLE_LSFGVK=1",
            "export DISABLE_LSFG=1",
            f"if [ -d {shlex.quote(FLATPAK_IMPLICIT_LAYER_DIR)} ]; then",
            f"    lsfgvk_implicit_layer_path={shlex.quote(FLATPAK_IMPLICIT_LAYER_DIR)}",
            f"    if [ -d {shlex.quote(FLATPAK_GAMESCOPE_IMPLICIT_LAYER_DIR)} ]; then",
            "        # Gamescope must stay above LSFG in Heroic's Vulkan chain.",
            f"        lsfgvk_implicit_layer_path={shlex.quote(FLATPAK_GAMESCOPE_IMPLICIT_LAYER_DIR)}:\"$lsfgvk_implicit_layer_path\"",
            "    fi",
            'elif [ "${LSFGVK_DISABLE_HDR_EXPOSURE:-0}" != "0" ]; then',
            f"    lsfgvk_implicit_layer_path={shlex.quote(str(self.local_share_dir))}",
            "else",
            '    lsfgvk_implicit_layer_path=""',
            "fi",
            'if [ "${LSFGVK_DISABLE_HDR_EXPOSURE:-0}" != "0" ]; then',
            '    export VK_IMPLICIT_LAYER_PATH="$lsfgvk_implicit_layer_path"',
            '    unset VK_ADD_IMPLICIT_LAYER_PATH',
            'elif [ -z "$lsfgvk_implicit_layer_path" ]; then',
            "    : # Host manifest is registered before Pressure Vessel starts.",
            'elif [ -n "${VK_IMPLICIT_LAYER_PATH:-}" ]; then',
            '    export VK_IMPLICIT_LAYER_PATH="$lsfgvk_implicit_layer_path:$VK_IMPLICIT_LAYER_PATH"',
            'elif [ -n "${VK_ADD_IMPLICIT_LAYER_PATH:-}" ]; then',
            '    export VK_ADD_IMPLICIT_LAYER_PATH="$lsfgvk_implicit_layer_path:$VK_ADD_IMPLICIT_LAYER_PATH"',
            "else",
            '    export VK_ADD_IMPLICIT_LAYER_PATH="$lsfgvk_implicit_layer_path"',
            "fi",
            f"export LSFGVK_CONFIG={shlex.quote(str(self.config_file_path))}",
            "# Heroic can discard a game's stderr. Capture opt-in engine diagnostics here instead.",
            f"lsfgvk_diagnostics_default={shlex.quote(str(diagnostics_log_path))}",
            'if [ "${LSFGVK_PRESENT_DIAGNOSTICS:-0}" != "0" ]; then',
            '    lsfgvk_diagnostics_log="${LSFGVK_PRESENT_DIAGNOSTICS_LOG:-$lsfgvk_diagnostics_default}"',
            '    if : > "$lsfgvk_diagnostics_log" 2>/dev/null; then',
            '        exec 2>> "$lsfgvk_diagnostics_log"',
            "    fi",
            "fi",
        ]

    def migrate_launch_script_if_needed(self) -> bool:
        """Upgrade an installed generated wrapper without touching user data.

        Wrapper format 27 keeps Heroic's Gamescope WSI manifest and activation
        contract while using the explicit Flatpak search path required to carry
        LSFG through UMU. Format 26 restored LSFG attachment but still removed
        Gamescope from ordinary SDR launches. Format 25 used
        VK_ADD_IMPLICIT_LAYER_PATH, but Heroic's UMU child did not retain that
        addition and frame generation never loaded. HDR remains blocked by the
        separate restart-time SDR boundary.
        Formats 19 to 22
        attempted to order components through VK_INSTANCE_LAYERS or a Vulkan
        meta-layer and could leave Gamescope or LSFG unattached.
        Format 15 forced only LSFG and could break Wine swapchain dispatch;
        marker validation therefore still regenerates it. Formats 16 through
        18 returned to implicit discovery, which worked only when the loader
        happened to choose the required Gamescope -> LSFG order. Format 14
        activated a uniquely named, wrapper-scoped experimental
        manifest from Vulkan's normal per-user registry. It disables both
        public LSFG layer identities for this game and no longer relies on
        additive search ordering that Pressure Vessel resolves before the
        wrapper starts. Format 13 removed the obsolete PROTON_USE_WOW64 export
        now
        that the engine ships architecture-matched Vulkan layers. Format 12
        added an opt-in legacy-isolation recovery path for
        games that cannot start when Gamescope advertises HDR. Format 11 added
        the private experimental manifest ahead of the normal implicit-layer
        search path instead of replacing that path. Format 14 supersedes that
        ordering-based selection while preserving Gamescope WSI discovery for
        HDR-capable games. It
        Format 17 retains format 10's automatic Active In matching, selected-profile
        compatibility settings, plugin-private diagnostics log, in-place
        presentation recovery, explicit caller overrides, validated 50 ms
        acquisition timeout, and experimental Flatpak manifest selection.
        Format 17 removes the obsolete layer-initiated swapchain-recreation
        export. Validate the required exports as well as the marker so an
        intermediate locally generated wrapper cannot be mistaken for the
        completed format.
        """
        try:
            current_content = self._read_managed_text(self.lsfg_script_path)
        except FileNotFoundError:
            return False

        try:
            wrapper_is_current = (
                self._WRAPPER_FORMAT_MARKER in current_content
                and all(
                    export in current_content
                    for export in self._REQUIRED_WRAPPER_EXPORTS
                )
                and not any(
                    export in current_content
                    for export in self._OBSOLETE_WRAPPER_EXPORTS
                )
            )
            if wrapper_is_current:
                return False

            profile_data = self._get_profile_data()
            result = self.update_lsfg_script_from_profile_data(profile_data)
            if not result["success"]:
                raise OSError(result.get("error") or "could not refresh launch wrapper")

            self.log.info("Upgraded installed lsfg-vk experimental launch wrapper to format 27")
            return True
        except OSError:
            raise
        except Exception as error:
            raise OSError(f"Could not upgrade lsfg-vk experimental launch wrapper: {error}") from error

    @staticmethod
    def _generate_game_launch_lines() -> list[str]:
        """Preserve Armada's required host launcher when running under FEX.

        This is intentionally host-gated, so ordinary SteamOS installs retain
        the normal direct ``exec`` path.  The argument scan also avoids adding
        the wrapper twice when a user already has it in Steam launch options.
        """
        device_env = ARMADA_DEVICE_ENV.as_posix()
        game_launch = ARMADA_GAME_LAUNCH.as_posix()
        return [
            f'armada_game_launch="{game_launch}"',
            'for argument in "$@"; do',
            '    if [ "$argument" = "$armada_game_launch" ]; then',
            '        exec "$@"',
            "    fi",
            "done",
            f'if [ -f "{device_env}" ] && [ -x "$armada_game_launch" ]; then',
            '    exec "$armada_game_launch" "$@"',
            "fi",
            'exec "$@"',
        ]
    
    def _get_profile_data(self) -> ProfileData:
        """Get current profile data from config file"""
        try:
            content = self._read_managed_text(self.config_file_path)
        except FileNotFoundError:
            from .dll_detection import DllDetectionService
            dll_service = DllDetectionService(self.log)
            default_config = ConfigurationManager.get_defaults_with_dll_detection(dll_service)
            return ProfileData(
                current_profile=DEFAULT_PROFILE_NAME,
                profiles={DEFAULT_PROFILE_NAME: default_config},
                global_config={
                    "dll": default_config.get("dll", ""),
                    "allow_fp16": default_config.get("allow_fp16", True)
                }
            )
        
        return ConfigurationManager.parse_toml_content_multi_profile(content)
    
    def _save_profile_data(self, profile_data: ProfileData) -> None:
        """Save profile data to config file"""
        toml_content = ConfigurationManager.generate_toml_content_multi_profile(profile_data)
        
        self._commit_managed_replacements(
            "configuration",
            {self.config_file_path: (toml_content.encode(), 0o644)},
        )
    
    def get_profiles(self) -> ProfilesResponse:
        """Get list of all profiles and current profile
        
        Returns:
            ProfilesResponse with profile list and current profile
        """
        from . import state_transaction

        layout = state_transaction.PathLayout.from_home(self.user_home)
        try:
            with state_transaction.read_only_guard(layout):
                profile_data, _profile_settings = self._load_effective_state_strict()
            
            return self._success_response(ProfilesResponse,
                                        "Profiles retrieved successfully",
                                        profiles=list(profile_data["profiles"].keys()),
                                        current_profile=profile_data["current_profile"],
                                        status_available=True)
            
        except state_transaction.MutationBusyError as e:
            return self._unavailable_read(
                ProfilesResponse, "mutation_busy", str(e), retryable=True,
                pending=False, action="refresh", profiles=None, current_profile=None,
            )
        except state_transaction.RecoveryPendingError as e:
            return self._unavailable_read(
                ProfilesResponse, "recovery_pending", str(e), retryable=False,
                pending=True, action="wait_for_recovery", profiles=None,
                current_profile=None,
            )
        except state_transaction.MutationBlockedError as e:
            return self._unavailable_read(
                ProfilesResponse, "recovery_blocked", str(e), retryable=False,
                pending=True, action="repair_required", profiles=None,
                current_profile=None,
            )
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            error_msg = f"Invalid persisted profile state: {str(e)}"
            self.log.error(error_msg)
            return self._unavailable_read(
                ProfilesResponse, "invalid_persisted_state", error_msg,
                retryable=False, pending=False, action="repair_required",
                profiles=None, current_profile=None,
            )
        except Exception as e:
            error_msg = f"Error getting profiles: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(ProfilesResponse, str(e), 
                                       profiles=None, current_profile=None)
    
    def create_profile(self, profile_name: str, source_profile: str = None) -> ProfileResponse:
        """Create a new profile
        
        Args:
            profile_name: Name for the new profile (spaces will be converted to dashes)
            source_profile: Optional source profile to copy from (default: current profile)
            
        Returns:
            ProfileResponse with success status and the normalized profile name
        """
        def transform(profile_data, profile_settings):
            selected_source = source_profile or profile_data["current_profile"]
            normalized_name = ConfigurationManager.normalize_profile_name(profile_name)
            updated = ConfigurationManager.create_profile(
                profile_data, profile_name, selected_source
            )
            profile_data.clear()
            profile_data.update(updated)
            profile_settings[normalized_name] = dict(
                self._wrapper_settings_for_profile(
                    selected_source, profile_settings
                )
            )
            return {"profile_name": normalized_name}

        return self._commit_effective_state(
            ProfileResponse,
            transform,
            lambda values: (
                f"Profile '{values['profile_name']}' created successfully"
            ),
            {"profile_name": None},
        )
    
    def delete_profile(self, profile_name: str) -> ProfileResponse:
        """Delete a profile
        
        Args:
            profile_name: Name of the profile to delete
            
        Returns:
            ProfileResponse with success status
        """
        def transform(profile_data, profile_settings):
            updated = ConfigurationManager.delete_profile(profile_data, profile_name)
            profile_data.clear()
            profile_data.update(updated)
            profile_settings.pop(profile_name, None)
            return {"profile_name": profile_name}

        return self._commit_effective_state(
            ProfileResponse,
            transform,
            lambda values: (
                f"Profile '{values['profile_name']}' deleted successfully"
            ),
            {"profile_name": None},
        )
    
    def rename_profile(self, old_name: str, new_name: str) -> ProfileResponse:
        """Rename a profile
        
        Args:
            old_name: Current profile name
            new_name: New profile name (spaces will be converted to dashes)
            
        Returns:
            ProfileResponse with success status and the normalized profile name
        """
        def transform(profile_data, profile_settings):
            normalized_name = ConfigurationManager.normalize_profile_name(new_name)
            updated = ConfigurationManager.rename_profile(
                profile_data, old_name, new_name
            )
            profile_data.clear()
            profile_data.update(updated)
            if old_name in profile_settings:
                profile_settings[normalized_name] = profile_settings.pop(old_name)
            return {"profile_name": normalized_name}

        return self._commit_effective_state(
            ProfileResponse,
            transform,
            lambda values: (
                f"Profile renamed from '{old_name}' to "
                f"'{values['profile_name']}' successfully"
            ),
            {"profile_name": None},
        )
    
    def set_current_profile(self, profile_name: str) -> ProfileResponse:
        """Set the current active profile
        
        Args:
            profile_name: Name of the profile to set as current
            
        Returns:
            ProfileResponse with success status
        """
        def transform(profile_data, _profile_settings):
            updated = ConfigurationManager.set_current_profile(
                profile_data, profile_name
            )
            profile_data.clear()
            profile_data.update(updated)
            return {"profile_name": profile_name}

        return self._commit_effective_state(
            ProfileResponse,
            transform,
            lambda values: (
                f"Current profile set to '{values['profile_name']}' successfully"
            ),
            {"profile_name": None},
        )
    
    def update_profile_config(
            self,
            profile_name: str | None,
            config: ConfigurationData,
    ) -> ConfigurationResponse:
        """Update configuration for a specific profile
        
        Args:
            profile_name: Name of the profile to update
            config: Configuration data to apply
            
        Returns:
            ConfigurationResponse with success status
        """
        selected_profile = {"name": profile_name}

        def transform(profile_data, profile_settings):
            name = profile_name or profile_data["current_profile"]
            selected_profile["name"] = name
            if name not in profile_data["profiles"]:
                raise ValueError(f"Profile '{name}' does not exist")
            validated_config = ConfigurationManager.validate_config(config)
            profile_data["profiles"][name] = validated_config
            for field_name in ("dll", "allow_fp16"):
                if field_name in validated_config:
                    profile_data["global_config"][field_name] = validated_config[field_name]
            profile_settings[name] = self._normalize_wrapper_settings(
                validated_config
            )
            return {"config": validated_config}

        return self._commit_effective_state(
            ConfigurationResponse,
            transform,
            lambda _values: (
                f"Profile '{selected_profile['name']}' configuration updated successfully"
            ),
            {"config": None},
        )
    
    def update_lsfg_script_from_profile_data(self, profile_data: ProfileData) -> ConfigurationResponse:
        """Update the isolated per-game launch script from profile data
        
        Args:
            profile_data: Profile data to apply to the script
            
        Returns:
            ConfigurationResponse indicating success or failure
        """
        try:
            script_content = self._generate_script_content_for_profile(profile_data)
            
            self._commit_managed_replacements(
                "configuration",
                {self.lsfg_script_path: (script_content.encode(), 0o755)},
            )
            
            self.log.info(f"Updated lsfg launch script at {self.lsfg_script_path} for profile '{profile_data['current_profile']}'")
            
            # Get current profile config for response
            current_config = self._config_for_profile(
                profile_data, profile_data["current_profile"]
            )
            
            return self._success_response(ConfigurationResponse,
                                        "Launch script updated successfully",
                                        config=current_config)
            
        except Exception as e:
            error_msg = f"Error updating launch script: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(ConfigurationResponse, str(e), config=None)
