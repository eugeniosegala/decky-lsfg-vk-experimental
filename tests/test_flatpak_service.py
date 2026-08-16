"""Regression contract for truthful Flatpak override mutations.

The tests deliberately mock every Flatpak call.  They describe the response at
the Decky boundary rather than relying on a host Flatpak installation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk.flatpak_service import FlatpakService  # noqa: E402
from py_modules.lsfg_vk.constants import FLATPAK_IMPLICIT_LAYER_DIR  # noqa: E402
from py_modules.lsfg_vk.plugin import Plugin  # noqa: E402


APP_ID = "com.example.Game"
CONFIG_PATH = "/home/deck/.config/lsfg-vk"
DLL_PATH = "/home/deck/.local/share/Steam/steamapps/common"
WRAPPER_PATH = "/home/deck/.local/bin/lsfg-vk-wrapper"
ENV_NAMES = (
    "LSFGVK_CONFIG",
    "VK_IMPLICIT_LAYER_PATH",
    "VK_ADD_IMPLICIT_LAYER_PATH",
)
OBSERVED_KEYS = {
    "config_filesystem",
    "dll_filesystem",
    "wrapper_filesystem",
    "config_filesystem_ready",
    "dll_filesystem_ready",
    "wrapper_filesystem_ready",
    "lsfg_config_env",
    "vk_implicit_layer_path_env",
    "vk_add_implicit_layer_path_env",
}


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["flatpak"], returncode, stdout, stderr)


def _override_output(
    *,
    config=False,
    dll=False,
    wrapper=False,
    env=(),
    config_mode="rw",
    dll_mode="ro",
    wrapper_mode="ro",
):
    filesystems = []
    if config:
        filesystems.append(f"{CONFIG_PATH}:{config_mode}")
    if dll:
        filesystems.append(f"{DLL_PATH}:{dll_mode}")
    if wrapper:
        filesystems.append(f"{WRAPPER_PATH}:{wrapper_mode}")
    environment = {
        "LSFGVK_CONFIG": f"{CONFIG_PATH}/conf.toml",
        "VK_IMPLICIT_LAYER_PATH": FLATPAK_IMPLICIT_LAYER_DIR,
        "VK_ADD_IMPLICIT_LAYER_PATH": FLATPAK_IMPLICIT_LAYER_DIR,
    }
    return "\n".join(
        ["[Context]", f"filesystems={';'.join(filesystems)};", "[Environment]"]
        + [f"{name}={environment[name]}" for name in env]
    )


class FlatpakOverrideContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = FlatpakService(logger=_Logger())
        self.service.user_home = Path("/home/deck")
        self.service.config_dir = Path(CONFIG_PATH)
        self.service.config_file_path = Path(self.temp.name) / "missing-conf.toml"
        self.service.lsfg_launch_script_path = Path(WRAPPER_PATH)

        self.available = patch.object(self.service, "check_flatpak_available", return_value=True)
        self.runtime = patch.object(self.service, "_get_app_runtime_version", return_value="24.08")
        self.extension = patch.object(self.service, "_is_extension_installed", return_value=True)
        self.wrapper = patch.object(Path, "is_file", return_value=True)
        self.paths = patch.object(
            self.service, "_get_lsfg_paths", return_value=(CONFIG_PATH, DLL_PATH)
        )
        for mocked in (self.available, self.runtime, self.extension, self.wrapper, self.paths):
            mocked.start()
            self.addCleanup(mocked.stop)

    def _run(
        self,
        operation,
        observation,
        *,
        initial_observation=None,
        mutation_returncode=0,
        mutation_stderr="",
    ):
        calls = []
        observations = iter([
            initial_observation or _completed(stdout=_override_output(
                config=True,
                dll=True,
                wrapper=True,
                env=ENV_NAMES,
            )),
            observation,
        ])

        def command(args, **_kwargs):
            calls.append(args)
            if args[:3] == ["override", "--user", "--show"]:
                return next(observations)
            return _completed(mutation_returncode, stderr=mutation_stderr)

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = getattr(self.service, f"{operation}_app_override")(APP_ID)
        return result, calls

    def test_set_uses_one_command_and_reports_presence_readiness_and_environment(self):
        result, calls = self._run(
            "set",
            _completed(stdout=_override_output(config=True, dll=True, wrapper=True)),
        )

        self.assertEqual(calls, [
            ["override", "--user", "--show", APP_ID],
            [
            "override", "--user",
            f"--filesystem={CONFIG_PATH}:rw",
            f"--filesystem={DLL_PATH}:ro",
            f"--filesystem={WRAPPER_PATH}:ro",
            *[f"--unset-env={name}" for name in ENV_NAMES],
            APP_ID,
            ],
            ["override", "--user", "--show", APP_ID],
        ])
        self.assertEqual(set(result["observed_state"]), OBSERVED_KEYS)
        self.assertEqual(result["observed_state"], {
            "config_filesystem": True,
            "dll_filesystem": True,
            "wrapper_filesystem": True,
            "config_filesystem_ready": True,
            "dll_filesystem_ready": True,
            "wrapper_filesystem_ready": True,
            "lsfg_config_env": False,
            "vk_implicit_layer_path_env": False,
            "vk_add_implicit_layer_path_env": False,
        })
        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))

    def test_remove_uses_one_multi_option_command_and_reports_complete(self):
        result, calls = self._run("remove", _completed(stdout=_override_output()))

        self.assertEqual(calls, [
            ["override", "--user", "--show", APP_ID],
            [
            "override", "--user",
            f"--nofilesystem={DLL_PATH}",
            f"--nofilesystem={CONFIG_PATH}",
            f"--nofilesystem={WRAPPER_PATH}",
            *[f"--unset-env={name}" for name in ENV_NAMES],
            APP_ID,
            ],
            ["override", "--user", "--show", APP_ID],
        ])
        self.assertEqual(result["observed_state"], {key: False for key in OBSERVED_KEYS})
        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))

    def test_set_partial_state_is_retryable_partial_failure(self):
        result, _ = self._run(
            "set", _completed(stdout=_override_output(config=True, dll=True, wrapper=False))
        )
        self.assertEqual(
            (result["success"], result["outcome"], result["error_code"], result["retryable"]),
            (False, "partial", "partial_failure", True),
        )

    def test_remove_partial_state_is_retryable_partial_failure(self):
        result, _ = self._run(
            "remove", _completed(stdout=_override_output(config=True))
        )
        self.assertEqual(
            (result["success"], result["outcome"], result["error_code"]),
            (False, "partial", "partial_failure"),
        )

    def test_remove_with_all_six_overrides_remaining_is_observed_failure(self):
        result, _ = self._run(
            "remove",
            _completed(stdout=_override_output(
                config=True,
                dll=True,
                wrapper=True,
                env=ENV_NAMES,
            )),
        )
        self.assertEqual(
            (result["success"], result["outcome"], result["error_code"]),
            (False, "failed", "operation_failed"),
        )

    def test_zero_exit_with_no_set_predicates_is_observed_failure(self):
        result, _ = self._run(
            "set",
            _completed(stdout=_override_output(env=ENV_NAMES)),
        )
        self.assertEqual(
            (result["success"], result["outcome"], result["error_code"]),
            (False, "failed", "operation_failed"),
        )

    def test_each_legacy_environment_value_prevents_complete_set_outcome(self):
        for environment_name in ENV_NAMES:
            with self.subTest(environment_name=environment_name):
                result, _ = self._run(
                    "set",
                    _completed(stdout=_override_output(
                        config=True,
                        dll=True,
                        wrapper=True,
                        env=(environment_name,),
                    )),
                )
                self.assertEqual(
                    (result["success"], result["outcome"], result["error_code"]),
                    (False, "partial", "partial_failure"),
                )

    def test_nonzero_exit_with_complete_observation_is_success_with_warning(self):
        result, _ = self._run(
            "set",
            _completed(stdout=_override_output(config=True, dll=True, wrapper=True)),
            mutation_returncode=1,
            mutation_stderr="aggregate command failed",
        )
        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))
        self.assertIsNone(result["error"])
        self.assertTrue(result["warning"])
        self.assertEqual(result["failed_steps"], ["apply_override"])

    def test_wrong_filesystem_mode_cannot_be_reported_as_complete(self):
        result, _ = self._run(
            "set",
            _completed(stdout=_override_output(
                config=True,
                dll=True,
                wrapper=True,
                config_mode="ro",
            )),
            mutation_returncode=1,
            mutation_stderr="Flatpak left the config read-only",
        )

        self.assertTrue(result["observed_state"]["config_filesystem"])
        self.assertFalse(result["observed_state"]["config_filesystem_ready"])
        self.assertEqual(
            (result["success"], result["outcome"], result["error_code"]),
            (False, "partial", "partial_failure"),
        )

    def test_remove_targets_exact_paths_even_when_access_modes_are_wrong(self):
        result, calls = self._run(
            "remove",
            _completed(stdout=_override_output()),
            initial_observation=_completed(stdout=_override_output(
                config=True,
                dll=True,
                wrapper=True,
                config_mode="ro",
                dll_mode="rw",
                wrapper_mode="rw",
            )),
        )

        self.assertEqual(calls[1], [
            "override",
            "--user",
            f"--nofilesystem={DLL_PATH}",
            f"--nofilesystem={CONFIG_PATH}",
            f"--nofilesystem={WRAPPER_PATH}",
            APP_ID,
        ])
        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))

    def test_status_probe_failure_is_unverified_without_observed_state(self):
        result, _ = self._run(
            "remove", _completed(returncode=1, stderr="cannot read overrides")
        )
        self.assertEqual(
            (
                result["success"], result["outcome"], result["status_available"],
                result["error_code"], result["retryable"],
            ),
            (False, "unverified", False, "status_unavailable", True),
        )
        self.assertNotIn("observed_state", result)

    def test_thrown_mutation_still_performs_strict_observation(self):
        calls = []
        show_count = 0

        def command(args, **_kwargs):
            nonlocal show_count
            calls.append(args)
            if args[:3] == ["override", "--user", "--show"]:
                show_count += 1
                if show_count == 1:
                    return _completed(stdout=_override_output(
                        config=True, dll=True, wrapper=True, env=ENV_NAMES
                    ))
                return _completed(stdout=_override_output())
            raise OSError("spawn failed")

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.remove_app_override(APP_ID)

        self.assertEqual(calls[-1], ["override", "--user", "--show", APP_ID])
        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))
        self.assertEqual(result["failed_steps"], ["apply_override"])

    def test_empty_environment_values_are_not_active_legacy_overrides(self):
        output = _override_output(config=True, dll=True, wrapper=True)
        output += "\n" + "\n".join(f"{name}=" for name in ENV_NAMES)
        with patch.object(
            self.service,
            "_run_flatpak_command",
            return_value=_completed(stdout=output),
        ):
            observed, error = self.service._observe_app_override_status(APP_ID)

        self.assertIsNone(error)
        self.assertIsNotNone(observed)
        for field in (
            "lsfg_config_env",
            "vk_implicit_layer_path_env",
            "vk_add_implicit_layer_path_env",
        ):
            self.assertFalse(observed[field])

    def test_unrelated_environment_values_are_not_treated_as_plugin_owned(self):
        output = _override_output(config=True, dll=True, wrapper=True)
        output += "\nVK_IMPLICIT_LAYER_PATH=/user/custom/layers"
        with patch.object(
            self.service,
            "_run_flatpak_command",
            return_value=_completed(stdout=output),
        ):
            observed, error = self.service._observe_app_override_status(APP_ID)

        self.assertIsNone(error)
        self.assertIsNotNone(observed)
        self.assertFalse(observed["vk_implicit_layer_path_env"])

    def test_invalid_app_id_is_rejected_before_any_flatpak_command(self):
        for operation in ("set", "remove"):
            for app_id in ("--reset", "bad/id", "x" * 256):
                with self.subTest(operation=operation, app_id=app_id), patch.object(
                    self.service, "_run_flatpak_command"
                ) as command:
                    result = getattr(self.service, f"{operation}_app_override")(app_id)

                command.assert_not_called()
                self.assertEqual(
                    (result["outcome"], result["error_code"], result["retryable"]),
                    ("rejected", "precondition_failed", False),
                )

    def test_remove_noop_does_not_create_negative_overrides(self):
        calls = []

        def command(args, **_kwargs):
            calls.append(args)
            return _completed(stdout=_override_output())

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.remove_app_override(APP_ID)

        self.assertEqual(calls, [["override", "--user", "--show", APP_ID]])
        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))

    def test_clean_set_does_not_create_environment_unset_overrides(self):
        result, calls = self._run(
            "set",
            _completed(stdout=_override_output(config=True, dll=True, wrapper=True)),
            initial_observation=_completed(stdout=_override_output()),
        )

        mutation = calls[1]
        self.assertFalse(any(argument.startswith("--unset-env=") for argument in mutation))
        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))

    def test_remove_targets_only_current_exact_lsfg_state(self):
        result, calls = self._run(
            "remove",
            _completed(stdout=_override_output()),
            initial_observation=_completed(stdout=_override_output(config=True)),
        )

        self.assertEqual(calls[1], [
            "override",
            "--user",
            f"--nofilesystem={CONFIG_PATH}",
            APP_ID,
        ])
        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))

    def test_pre_mutation_status_failure_changes_nothing(self):
        calls = []

        def command(args, **_kwargs):
            calls.append(args)
            return _completed(returncode=1, stderr="status denied")

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.remove_app_override(APP_ID)

        self.assertEqual(calls, [["override", "--user", "--show", APP_ID]])
        self.assertEqual(
            (result["success"], result["outcome"], result["error_code"]),
            (False, "unverified", "status_unavailable"),
        )
        self.assertIn("No settings were changed", result["error"])

    def test_backend_lock_spans_mutation_and_strict_readback(self):
        nested_results = []
        show_count = 0

        def command(args, **_kwargs):
            nonlocal show_count
            if args[:3] == ["override", "--user", "--show"]:
                show_count += 1
                if show_count == 2:
                    nested_results.append(self.service.remove_app_override("com.example.Other"))
                    return _completed(stdout=_override_output())
                return _completed(stdout=_override_output(config=True))
            return _completed()

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.remove_app_override(APP_ID)

        self.assertEqual((result["success"], result["outcome"]), (True, "complete"))
        self.assertEqual(len(nested_results), 1)
        self.assertEqual(
            (nested_results[0]["outcome"], nested_results[0]["error_code"]),
            ("unverified", "operation_busy"),
        )

    def test_diagnostics_are_bounded_sanitized_and_use_stable_step_ids(self):
        result, _ = self._run(
            "set",
            _completed(stdout=_override_output(config=True)),
            mutation_returncode=1,
            mutation_stderr="secret\x00\n\r\t\u202e" + "x" * 5000,
        )
        self.assertEqual(result["failed_steps"], ["apply_override"])
        for field in ("error", "warning"):
            diagnostic = result.get(field)
            if diagnostic:
                self.assertLessEqual(len(diagnostic), 512)
                self.assertNotIn("\u202e", diagnostic)
                self.assertFalse(any(ord(character) < 32 for character in diagnostic))

    def test_precondition_rejection_runs_no_mutation_or_observation(self):
        with patch.object(self.service, "check_flatpak_available", return_value=False), patch.object(
            self.service, "_run_flatpak_command"
        ) as command:
            result = self.service.set_app_override(APP_ID)

        command.assert_not_called()
        self.assertEqual(
            (
                result["success"], result["outcome"], result["status_available"],
                result["error_code"], result["retryable"],
            ),
            (False, "rejected", False, "precondition_failed", False),
        )
        self.assertNotIn("observed_state", result)

    def test_set_prerequisite_exception_returns_unverified_without_mutation(self):
        with patch.object(
            self.service,
            "_get_app_runtime_version",
            side_effect=OSError("runtime probe failed\nwith noisy detail"),
        ), patch.object(self.service, "_run_flatpak_command") as command:
            result = self.service.set_app_override(APP_ID)

        self.assertEqual(
            (
                result["success"], result["outcome"], result["status_available"],
                result["error_code"], result["retryable"],
            ),
            (False, "unverified", False, "status_unavailable", True),
        )
        self.assertIn("No settings were changed", result["error"])
        self.assertNotIn("\n", result["error"])
        self.assertLessEqual(len(result["error"]), 512)
        command.assert_not_called()

    def test_remove_prerequisite_exception_returns_unverified_without_mutation(self):
        with patch.object(
            self.service,
            "_get_lsfg_paths",
            side_effect=PermissionError("cannot inspect paths"),
        ), patch.object(self.service, "_run_flatpak_command") as command:
            result = self.service.remove_app_override(APP_ID)

        self.assertEqual(
            (
                result["success"], result["outcome"], result["status_available"],
                result["error_code"], result["retryable"],
            ),
            (False, "unverified", False, "status_unavailable", True),
        )
        self.assertIn("No settings were changed", result["error"])
        self.assertLessEqual(len(result["error"]), 512)
        command.assert_not_called()

    def test_unexpected_post_mutation_error_never_claims_nothing_changed(self):
        observed = {key: False for key in OBSERVED_KEYS}
        with patch.object(
            self.service,
            "_observe_before_mutation",
            return_value=(observed, None),
        ), patch.object(
            self.service,
            "_apply_and_observe_override",
            side_effect=RuntimeError("classifier failed"),
        ):
            result = self.service.set_app_override(APP_ID)

        self.assertEqual(
            (result["outcome"], result["error_code"], result["failed_steps"]),
            ("unverified", "status_unavailable", ["apply_override"]),
        )
        self.assertIn("may have changed", result["error"])
        self.assertNotIn("No settings were changed", result["error"])

    def test_app_list_error_is_bounded_and_sanitized(self):
        error = subprocess.CalledProcessError(
            1,
            ["flatpak", "list"],
            stderr="list failed\u202e\n" + "x" * 5000,
        )
        with patch.object(self.service, "_run_flatpak_command", side_effect=error):
            result = self.service.get_flatpak_apps()

        self.assertFalse(result["success"])
        self.assertLessEqual(len(result["error"]), 512)
        self.assertNotIn("\u202e", result["error"])
        self.assertNotIn("\n", result["error"])

    def test_app_list_marks_only_unobservable_app_status_unavailable(self):
        def command(args, **_kwargs):
            if args == ["list", "--app"]:
                return _completed(stdout="Good\tcom.example.Good\nBad\tcom.example.Bad\n")
            if args[-1] == "com.example.Good":
                return _completed(stdout=_override_output(config=True, dll=True, wrapper=True))
            return _completed(returncode=1, stderr="status denied")

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.get_flatpak_apps()

        good, bad = result["apps"]
        self.assertTrue(good["status_available"])
        self.assertTrue(OBSERVED_KEYS.issubset(good))
        self.assertFalse(bad["status_available"])
        self.assertEqual(bad["status_error_code"], "status_unavailable")
        for field in (*OBSERVED_KEYS, "has_filesystem_override", "has_wrapper_override", "has_env_override"):
            self.assertNotIn(field, bad)


class FlatpakFacadeContractTests(unittest.TestCase):
    def test_facade_preserves_complete_serializable_contract_shape(self):
        observed = {key: False for key in OBSERVED_KEYS}
        response = {
            "success": True,
            "outcome": "complete",
            "status_available": True,
            "app_id": APP_ID,
            "operation": "remove",
            "message": "removed",
            "error": None,
            "warning": None,
            "retryable": False,
            "failed_steps": [],
            "observed_state": observed,
        }
        plugin = Plugin.__new__(Plugin)
        plugin.flatpak_service = SimpleNamespace(remove_app_override=lambda _app_id: response)

        actual = asyncio.run(plugin.remove_flatpak_app_override(APP_ID))

        self.assertEqual(actual, response)
        self.assertEqual(set(actual), {
            "success", "outcome", "status_available", "app_id", "operation",
            "message", "error", "warning", "retryable", "failed_steps", "observed_state",
        })


if __name__ == "__main__":
    unittest.main()
