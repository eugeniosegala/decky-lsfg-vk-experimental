"""Regression contract for truthful Flatpak override mutations.

The tests deliberately mock every Flatpak call.  They describe the response at
the Decky boundary rather than relying on a host Flatpak installation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk.flatpak_service import (  # noqa: E402
    FLATPAK_OWNERSHIP_MAX_BYTES,
    FlatpakService,
)
from py_modules.lsfg_vk.constants import FLATPAK_IMPLICIT_LAYER_DIR  # noqa: E402
from py_modules.lsfg_vk.plugin import Plugin  # noqa: E402
from py_modules.lsfg_vk.state_transaction import read_bytes_nofollow  # noqa: E402


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
    extra_filesystems=(),
    unset_env=(),
):
    filesystems = []
    if config:
        filesystems.append(f"{CONFIG_PATH}:{config_mode}")
    if dll:
        filesystems.append(f"{DLL_PATH}:{dll_mode}")
    if wrapper:
        filesystems.append(f"{WRAPPER_PATH}:{wrapper_mode}")
    filesystems.extend(extra_filesystems)
    environment = {
        "LSFGVK_CONFIG": f"{CONFIG_PATH}/conf.toml",
        "VK_IMPLICIT_LAYER_PATH": FLATPAK_IMPLICIT_LAYER_DIR,
        "VK_ADD_IMPLICIT_LAYER_PATH": FLATPAK_IMPLICIT_LAYER_DIR,
    }
    return "\n".join(
        [
            "[Context]",
            f"filesystems={';'.join(filesystems)};",
            f"unset-environment={';'.join(unset_env)};",
            "[Environment]",
        ]
        + [f"{name}={environment[name]}" for name in env]
    )


class FlatpakOverrideContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = FlatpakService(logger=_Logger())
        self.service.user_home = Path("/home/deck")
        self.service.config_dir = Path(self.temp.name) / "config"
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
        if operation == "remove":
            self._write_active_ownership()
        observations = iter([
            initial_observation or _completed(stdout=_override_output(
                config=operation == "remove",
                dll=operation == "remove",
                wrapper=operation == "remove",
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

    def _write_active_ownership(self, *, owned=True, dll_path=DLL_PATH):
        path = self.service._flatpak_ownership_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": 1,
            "apps": {
                APP_ID: {
                    "status": "active",
                    "paths": {
                        "config": {"path": CONFIG_PATH, "owned": owned, "present": True},
                        "dll": {"path": dll_path, "owned": owned, "present": True},
                        "wrapper": {"path": WRAPPER_PATH, "owned": owned, "present": True},
                    },
                    "retired_paths": [],
                }
            },
        }), encoding="utf-8")

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
            f"--nofilesystem={CONFIG_PATH}",
            f"--nofilesystem={DLL_PATH}",
            f"--nofilesystem={WRAPPER_PATH}",
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
        self.assertIn("current Flatpak override state", result["error"])
        self.assertNotIn("applied only part", result["error"])

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

    def test_each_legacy_environment_value_rejects_set_before_intent(self):
        for environment_name in ENV_NAMES:
            with self.subTest(environment_name=environment_name):
                result, calls = self._run(
                    "set",
                    _completed(stdout=_override_output()),
                    initial_observation=_completed(
                        stdout=_override_output(env=(environment_name,))
                    ),
                )
                self.assertEqual(
                    (result["success"], result["outcome"], result["error_code"]),
                    (False, "unverified", "ownership_unknown"),
                )
                self.assertEqual(calls, [["override", "--user", "--show", APP_ID]])

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

    def test_set_never_accepts_readiness_without_path_presence(self):
        contradictory = {key: False for key in OBSERVED_KEYS}
        contradictory.update({
            "config_filesystem_ready": True,
            "dll_filesystem_ready": True,
            "wrapper_filesystem_ready": True,
        })

        result = self.service._classify_override_result(
            APP_ID, "set", contradictory, command_error=None
        )

        self.assertFalse(result["success"])
        self.assertEqual((result["outcome"], result["error_code"]), (
            "partial", "partial_failure"
        ))

    def test_remove_rejects_tracked_paths_with_wrong_modes(self):
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

        self.assertEqual(calls, [["override", "--user", "--show", APP_ID]])
        self.assertEqual((result["outcome"], result["error_code"]), (
            "unverified", "ownership_blocked"
        ))

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
        self._write_active_ownership()
        calls = []
        show_count = 0

        def command(args, **_kwargs):
            nonlocal show_count
            calls.append(args)
            if args[:3] == ["override", "--user", "--show"]:
                show_count += 1
                if show_count == 1:
                    return _completed(stdout=_override_output(
                        config=True, dll=True, wrapper=True
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

    def test_remove_without_ledger_fails_closed_and_runs_no_mutation(self):
        calls = []
        def command(args, **_kwargs):
            calls.append(args)
            return _completed(stdout=_override_output(config=True))
        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.remove_app_override(APP_ID)
        self.assertEqual(calls, [["override", "--user", "--show", APP_ID]])
        self.assertEqual((result["outcome"], result["error_code"]), (
            "unverified", "ownership_unknown"
        ))

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
        self._write_active_ownership()
        nested_results = []
        show_count = 0

        def command(args, **_kwargs):
            nonlocal show_count
            if args[:3] == ["override", "--user", "--show"]:
                show_count += 1
                if show_count == 2:
                    nested_results.append(self.service.remove_app_override("com.example.Other"))
                    return _completed(stdout=_override_output())
                return _completed(stdout=_override_output(
                    config=True, dll=True, wrapper=True
                ))
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

    def test_corrupt_ownership_ledger_blocks_remove_without_flatpak_command(self):
        self.service._flatpak_ownership_path.parent.mkdir(parents=True, exist_ok=True)
        self.service._flatpak_ownership_path.write_text("{broken", encoding="utf-8")
        with patch.object(self.service, "_run_flatpak_command") as command:
            result = self.service.remove_app_override(APP_ID)

        self.assertEqual(
            (
                result["success"], result["outcome"], result["status_available"],
                result["error_code"], result["retryable"],
            ),
            (False, "unverified", False, "ownership_blocked", True),
        )
        self.assertIn("No settings were changed", result["error"])
        self.assertLessEqual(len(result["error"]), 512)
        command.assert_not_called()

    def test_pending_ownership_intent_reconciles_before_retry(self):
        active = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        baseline = {
            "status": "baseline",
            "paths": {
                role: {
                    "path": entry["path"],
                    "owned": False,
                    "present": False,
                }
                for role, entry in active["paths"].items()
            },
            "retired_paths": [],
        }
        path = self.service._flatpak_ownership_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 1, "apps": {APP_ID: {
            "status": "pending",
            "operation": "remove",
            "before": active,
            "after": baseline,
        }}}), encoding="utf-8")
        observations = iter((
            _completed(stdout=_override_output(config=True, dll=True, wrapper=True)),
            _completed(stdout=_override_output(config=True, dll=True, wrapper=True)),
            _completed(stdout=_override_output()),
        ))
        def run(args, **_kwargs):
            return next(observations) if args[:3] == ["override", "--user", "--show"] else _completed()
        with patch.object(self.service, "_run_flatpak_command", side_effect=run) as command:
            result = self.service.remove_app_override(APP_ID)
        self.assertEqual(command.call_count, 4)
        self.assertTrue(result["success"])
        ledger = json.loads(self.service._flatpak_ownership_path.read_text())
        self.assertEqual(ledger["apps"][APP_ID]["status"], "baseline")

    def test_set_intent_is_durable_0600_before_flatpak_mutation(self):
        calls = []
        def command(args, **_kwargs):
            calls.append(args)
            if args[:3] == ["override", "--user", "--show"]:
                return _completed(stdout=_override_output(
                    config=len(calls) > 2, dll=len(calls) > 2, wrapper=len(calls) > 2
                ))
            ledger = json.loads(self.service._flatpak_ownership_path.read_text())
            self.assertEqual(ledger["apps"][APP_ID]["status"], "pending")
            self.assertEqual(self.service._flatpak_ownership_path.stat().st_mode & 0o777, 0o600)
            return _completed()
        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.set_app_override(APP_ID)
        self.assertEqual((result["outcome"], result["ownership_status"]), (
            "complete", "managed"
        ))
        self.assertEqual(json.loads(
            self.service._flatpak_ownership_path.read_text()
        )["apps"][APP_ID]["status"], "active")

    def test_preexisting_correct_grants_are_tracked_but_never_owned_or_removed(self):
        calls = []
        def command(args, **_kwargs):
            calls.append(args)
            return _completed(stdout=_override_output(config=True, dll=True, wrapper=True))
        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.set_app_override(APP_ID)
        self.assertTrue(result["success"])
        self.assertEqual(calls, [["override", "--user", "--show", APP_ID]])
        record = json.loads(self.service._flatpak_ownership_path.read_text())["apps"][APP_ID]
        self.assertFalse(any(entry["owned"] for entry in record["paths"].values()))
        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            removed = self.service.remove_app_override(APP_ID)
        self.assertEqual(removed["outcome"], "complete")
        self.assertEqual(calls[-1], ["override", "--user", "--show", APP_ID])
        baseline = json.loads(
            self.service._flatpak_ownership_path.read_text()
        )["apps"][APP_ID]
        self.assertEqual(baseline["status"], "baseline")
        output = _override_output(config=True, dll=True, wrapper=True)
        states = self.service._parse_override_exact_states(
            output,
            f"filesystems={CONFIG_PATH}:rw;{DLL_PATH}:ro;{WRAPPER_PATH}:ro;",
        )
        self.assertEqual(
            self.service._flatpak_ownership_status(
                APP_ID,
                removed["observed_state"],
                {"schema": 1, "apps": {APP_ID: baseline}},
                states,
            ),
            "unmanaged",
        )

    def test_explicit_deny_wins_over_duplicate_allow_in_any_order(self):
        for entries in (
            (f"{CONFIG_PATH}:rw", f"!{CONFIG_PATH}"),
            (f"!{CONFIG_PATH}", f"{CONFIG_PATH}:rw"),
        ):
            with self.subTest(entries=entries):
                output = _override_output(extra_filesystems=entries)
                states = self.service._parse_override_exact_states(
                    output,
                    f"filesystems={';'.join(entries)};",
                )
                self.assertEqual(states[CONFIG_PATH], "deny")

    def test_wrong_mode_or_deny_rejects_set_before_intent(self):
        for output in (
            _override_output(config=True, config_mode="ro"),
            _override_output(extra_filesystems=(f"!{CONFIG_PATH}",)),
        ):
            with self.subTest(output=output), patch.object(
                self.service, "_run_flatpak_command", return_value=_completed(stdout=output)
            ) as command:
                result = self.service.set_app_override(APP_ID)
            self.assertEqual(command.call_count, 1)
            self.assertEqual(result["error_code"], "ownership_unknown")
            self.assertFalse(self.service._flatpak_ownership_path.exists())

    def test_legacy_unset_environment_rejects_set_before_intent(self):
        output = _override_output(unset_env=("LSFGVK_CONFIG",))
        with patch.object(
            self.service, "_run_flatpak_command", return_value=_completed(stdout=output)
        ) as command:
            result = self.service.set_app_override(APP_ID)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(result["error_code"], "ownership_unknown")

    def test_partial_set_leaves_pending_and_incompatible_retry_is_blocked(self):
        result, _calls = self._run(
            "set", _completed(stdout=_override_output(config=True))
        )
        self.assertEqual(result["ownership_status"], "pending")
        ledger = json.loads(self.service._flatpak_ownership_path.read_text())
        self.assertEqual(ledger["apps"][APP_ID]["status"], "pending")
        with patch.object(
            self.service,
            "_run_flatpak_command",
            return_value=_completed(stdout=_override_output(config=True, config_mode="ro")),
        ) as command:
            retry = self.service.set_app_override(APP_ID)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(retry["error_code"], "ownership_blocked")

    def test_pending_set_retry_applies_only_compatible_missing_transitions(self):
        active = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        path = self.service._flatpak_ownership_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": 1,
            "apps": {APP_ID: {
                "status": "pending",
                "operation": "set",
                "before": None,
                "after": active,
            }},
        }), encoding="utf-8")
        granted_paths = {CONFIG_PATH}
        mutations = []

        def output():
            return _override_output(
                config=CONFIG_PATH in granted_paths,
                dll=DLL_PATH in granted_paths,
                wrapper=WRAPPER_PATH in granted_paths,
            )

        def command(args, **_kwargs):
            if args[:3] == ["override", "--user", "--show"]:
                return _completed(stdout=output())
            mutations.append(args)
            for argument in args:
                if argument.startswith("--filesystem="):
                    granted_paths.add(
                        argument.removeprefix("--filesystem=").rsplit(":", 1)[0]
                    )
            return _completed()

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.set_app_override(APP_ID)

        self.assertEqual(
            (result["success"], result["outcome"], result["ownership_status"]),
            (True, "complete", "managed"),
        )
        self.assertEqual(len(mutations), 1)
        self.assertNotIn(f"--filesystem={CONFIG_PATH}:rw", mutations[0])
        self.assertIn(f"--filesystem={DLL_PATH}:ro", mutations[0])
        self.assertIn(f"--filesystem={WRAPPER_PATH}:ro", mutations[0])
        record = json.loads(path.read_text(encoding="utf-8"))["apps"][APP_ID]
        self.assertEqual(record, active)

    def test_pending_set_path_change_preserves_preexisting_unowned_grant(self):
        replacement_config = "/home/deck/.config/lsfg-vk-new"
        before = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": False, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        after = {
            "status": "active",
            "paths": {
                "config": {
                    "path": replacement_config,
                    "owned": True,
                    "present": True,
                },
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        ownership_path = self.service._flatpak_ownership_path
        ownership_path.parent.mkdir(parents=True, exist_ok=True)
        ownership_path.write_text(json.dumps({
            "schema": 1,
            "apps": {APP_ID: {
                "status": "pending",
                "operation": "set",
                "before": before,
                "after": after,
            }},
        }), encoding="utf-8")
        self.paths.stop()
        replacement_paths = patch.object(
            self.service,
            "_get_lsfg_paths",
            return_value=(replacement_config, DLL_PATH),
        )
        replacement_paths.start()
        self.addCleanup(replacement_paths.stop)
        granted_paths = {CONFIG_PATH, DLL_PATH, WRAPPER_PATH}
        mutations = []

        def output():
            extra_filesystems = [
                f"{path}:{'rw' if path in {CONFIG_PATH, replacement_config} else 'ro'}"
                for path in sorted(granted_paths)
            ]
            return _override_output(extra_filesystems=extra_filesystems)

        def command(args, **_kwargs):
            if args[:3] == ["override", "--user", "--show"]:
                return _completed(stdout=output())
            mutations.append(args)
            for argument in args:
                if argument.startswith("--filesystem="):
                    granted_paths.add(
                        argument.removeprefix("--filesystem=").rsplit(":", 1)[0]
                    )
                elif argument.startswith("--nofilesystem="):
                    granted_paths.discard(argument.removeprefix("--nofilesystem="))
            return _completed()

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.set_app_override(APP_ID)

        self.assertEqual(
            (result["success"], result["outcome"], result["ownership_status"]),
            (True, "complete", "managed"),
        )
        self.assertEqual(len(mutations), 1)
        self.assertIn(f"--filesystem={replacement_config}:rw", mutations[0])
        self.assertNotIn(f"--nofilesystem={CONFIG_PATH}", mutations[0])
        self.assertIn(CONFIG_PATH, granted_paths)
        record = json.loads(
            ownership_path.read_text(encoding="utf-8")
        )["apps"][APP_ID]
        self.assertEqual(record, after)

    def test_pending_remove_retry_applies_only_compatible_remaining_transitions(self):
        active = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        baseline = {
            "status": "baseline",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": False, "present": False},
                "dll": {"path": DLL_PATH, "owned": False, "present": False},
                "wrapper": {"path": WRAPPER_PATH, "owned": False, "present": False},
            },
            "retired_paths": [],
        }
        path = self.service._flatpak_ownership_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": 1,
            "apps": {APP_ID: {
                "status": "pending",
                "operation": "remove",
                "before": active,
                "after": baseline,
            }},
        }), encoding="utf-8")
        granted_paths = {CONFIG_PATH}
        mutations = []

        def output():
            return _override_output(
                config=CONFIG_PATH in granted_paths,
                dll=DLL_PATH in granted_paths,
                wrapper=WRAPPER_PATH in granted_paths,
            )

        def command(args, **_kwargs):
            if args[:3] == ["override", "--user", "--show"]:
                return _completed(stdout=output())
            mutations.append(args)
            for argument in args:
                if argument.startswith("--nofilesystem="):
                    granted_paths.discard(argument.removeprefix("--nofilesystem="))
            return _completed()

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.remove_app_override(APP_ID)

        self.assertEqual(
            (result["success"], result["outcome"], result["ownership_status"]),
            (True, "complete", "unmanaged"),
        )
        self.assertEqual(len(mutations), 1)
        self.assertEqual(
            mutations[0],
            ["override", "--user", f"--nofilesystem={CONFIG_PATH}", APP_ID],
        )
        record = json.loads(path.read_text(encoding="utf-8"))["apps"][APP_ID]
        self.assertEqual(record, baseline)

    def test_remove_deny_readback_is_not_success_and_leaves_pending(self):
        self._write_active_ownership()
        observations = iter((
            _completed(stdout=_override_output(config=True, dll=True, wrapper=True)),
            _completed(stdout=_override_output(extra_filesystems=(f"!{CONFIG_PATH}",))),
        ))
        def command(args, **_kwargs):
            return next(observations) if args[:3] == ["override", "--user", "--show"] else _completed()
        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.remove_app_override(APP_ID)
        self.assertFalse(result["success"])
        self.assertEqual(result["ownership_status"], "pending")

    def test_changing_dll_path_retires_the_old_owned_grant(self):
        dll_b = "/home/deck/Games/Lossless"
        current_dll = DLL_PATH
        self.paths.stop()
        dynamic_paths = patch.object(
            self.service, "_get_lsfg_paths", side_effect=lambda: (CONFIG_PATH, current_dll)
        )
        dynamic_paths.start()
        self.addCleanup(dynamic_paths.stop)
        state = "empty"
        mutations = []

        def output():
            if state == "empty":
                return _override_output()
            if state == "a":
                return _override_output(config=True, dll=True, wrapper=True)
            return _override_output(
                config=True,
                wrapper=True,
                extra_filesystems=(f"{dll_b}:ro",),
            )

        def command(args, **_kwargs):
            nonlocal state
            if args[:3] == ["override", "--user", "--show"]:
                return _completed(stdout=output())
            mutations.append(args)
            state = "a" if current_dll == DLL_PATH else "b"
            return _completed()

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            first = self.service.set_app_override(APP_ID)
            self.assertTrue(first["success"])
            current_dll = dll_b
            second = self.service.set_app_override(APP_ID)
        self.assertTrue(second["success"])
        self.assertIn(f"--nofilesystem={DLL_PATH}", mutations[1])
        self.assertIn(f"--filesystem={dll_b}:ro", mutations[1])
        record = json.loads(self.service._flatpak_ownership_path.read_text())["apps"][APP_ID]
        self.assertEqual(record["paths"]["dll"]["path"], dll_b)
        self.assertIn(DLL_PATH, record["retired_paths"])

    def test_returning_to_a_retired_dll_path_restores_managed_complete_state(self):
        dll_b = "/home/deck/Games/Lossless"
        current_dll = DLL_PATH
        granted_paths: set[str] = set()
        mutations = []
        self.paths.stop()
        dynamic_paths = patch.object(
            self.service, "_get_lsfg_paths", side_effect=lambda: (CONFIG_PATH, current_dll)
        )
        dynamic_paths.start()
        self.addCleanup(dynamic_paths.stop)

        def output():
            return _override_output(
                config=CONFIG_PATH in granted_paths,
                dll=DLL_PATH in granted_paths,
                wrapper=WRAPPER_PATH in granted_paths,
                extra_filesystems=(
                    (f"{dll_b}:ro",) if dll_b in granted_paths else ()
                ),
            )

        def command(args, **_kwargs):
            if args[:3] == ["override", "--user", "--show"]:
                return _completed(stdout=output())
            mutations.append(args)
            for argument in args:
                if argument.startswith("--nofilesystem="):
                    granted_paths.discard(argument.removeprefix("--nofilesystem="))
                elif argument.startswith("--filesystem="):
                    path_and_mode = argument.removeprefix("--filesystem=")
                    granted_paths.add(path_and_mode.rsplit(":", 1)[0])
            return _completed()

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            first = self.service.set_app_override(APP_ID)
            current_dll = dll_b
            second = self.service.set_app_override(APP_ID)
            current_dll = DLL_PATH
            third = self.service.set_app_override(APP_ID)

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertEqual(
            (third["success"], third["outcome"], third["ownership_status"]),
            (True, "complete", "managed"),
        )
        self.assertEqual(len(mutations), 3)
        record = json.loads(
            self.service._flatpak_ownership_path.read_text(encoding="utf-8")
        )["apps"][APP_ID]
        self.assertEqual(record["paths"]["dll"]["path"], DLL_PATH)
        self.assertNotIn(DLL_PATH, record["retired_paths"])
        self.assertIn(dll_b, record["retired_paths"])

    def test_nonabsolute_configured_dll_path_fails_closed_before_mutation(self):
        self.paths.stop()
        self.service.config_file_path = Path(self.temp.name) / "conf.toml"

        for configured_dll in (
            "relative/Lossless.dll",
            "~/Games/Lossless Scaling/Lossless.dll",
        ):
            with self.subTest(configured_dll=configured_dll):
                if self.service._flatpak_ownership_path.exists():
                    self.service._flatpak_ownership_path.unlink()
                self.service.config_file_path.write_text(
                    f'[global]\ndll = "{configured_dll}"\n', encoding="utf-8"
                )
                calls = []

                def command(args, **_kwargs):
                    calls.append(args)
                    return _completed(stdout=_override_output())

                with patch.object(
                    self.service, "_run_flatpak_command", side_effect=command
                ):
                    result = self.service.set_app_override(APP_ID)

                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "status_unavailable")
                self.assertFalse(any(args[:2] == ["override", "--user"] and args[2] != "--show" for args in calls))
                self.assertFalse(self.service._flatpak_ownership_path.exists())

    def test_malformed_existing_config_fails_closed_before_flatpak_mutation(self):
        self.paths.stop()
        self.service.config_file_path = Path(self.temp.name) / "conf.toml"
        self.service.config_file_path.write_text("[global\ndll = broken", encoding="utf-8")
        calls = []

        def command(args, **_kwargs):
            calls.append(args)
            return _completed(stdout=_override_output())

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.set_app_override(APP_ID)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "status_unavailable")
        self.assertFalse(any(
            args[:2] == ["override", "--user"] and args[2] != "--show"
            for args in calls
        ))
        self.assertFalse(self.service._flatpak_ownership_path.exists())

    def test_unreadable_existing_config_fails_closed_before_flatpak_mutation(self):
        self.paths.stop()
        self.service.config_file_path = Path(self.temp.name) / "conf.toml"
        self.service.config_file_path.write_text("[global]\n", encoding="utf-8")
        calls = []

        def read(path):
            if Path(path) == self.service.config_file_path:
                raise PermissionError("config is unreadable")
            return read_bytes_nofollow(path)

        def command(args, **_kwargs):
            calls.append(args)
            return _completed(stdout=_override_output())

        with patch(
            "py_modules.lsfg_vk.flatpak_service.read_bytes_nofollow", side_effect=read
        ), patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.set_app_override(APP_ID)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "status_unavailable")
        self.assertFalse(any(
            args[:2] == ["override", "--user"] and args[2] != "--show"
            for args in calls
        ))
        self.assertFalse(self.service._flatpak_ownership_path.exists())

    def test_final_ledger_commit_failure_keeps_durable_pending_intent(self):
        original_write = self.service._write_flatpak_ownership
        writes = 0

        def write(coordinator, document):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("final ledger fsync failed")
            return original_write(coordinator, document)

        observations = iter((
            _completed(stdout=_override_output()),
            _completed(stdout=_override_output(config=True, dll=True, wrapper=True)),
        ))
        def command(args, **_kwargs):
            return next(observations) if args[:3] == ["override", "--user", "--show"] else _completed()

        with patch.object(
            self.service, "_write_flatpak_ownership", side_effect=write
        ), patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.set_app_override(APP_ID)

        self.assertEqual(result["outcome"], "unverified")
        self.assertIn("may have changed", result["error"])
        ledger = json.loads(self.service._flatpak_ownership_path.read_text())
        self.assertEqual(ledger["apps"][APP_ID]["status"], "pending")
        with patch.object(
            self.service,
            "_run_flatpak_command",
            return_value=_completed(stdout=_override_output(config=True, dll=True, wrapper=True)),
        ):
            retry = self.service.set_app_override(APP_ID)
        self.assertTrue(retry["success"])
        self.assertEqual(json.loads(
            self.service._flatpak_ownership_path.read_text()
        )["apps"][APP_ID]["status"], "active")

    def test_ownership_validator_rejects_nonabsolute_paths_and_nonbool_owned(self):
        valid = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        for field, value in (("path", "relative"), ("owned", 1)):
            record = json.loads(json.dumps(valid))
            record["paths"]["config"][field] = value
            with self.subTest(field=field), self.assertRaises(Exception):
                self.service._validate_flatpak_active_record(record)

    def test_ownership_validator_rejects_active_path_in_retired_history(self):
        record = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [DLL_PATH],
        }

        with self.assertRaises(Exception):
            self.service._validate_flatpak_active_record(record)

    def test_ownership_validator_rejects_invalid_stable_record_semantics(self):
        active = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        invalid_records = {}

        active_with_absent_path = json.loads(json.dumps(active))
        active_with_absent_path["paths"]["config"].update({
            "owned": False,
            "present": False,
        })
        invalid_records["active path marked absent"] = active_with_absent_path

        baseline_with_owned_path = json.loads(json.dumps(active))
        baseline_with_owned_path["status"] = "baseline"
        invalid_records["baseline path marked owned"] = baseline_with_owned_path

        duplicate_role_paths = json.loads(json.dumps(active))
        duplicate_role_paths["paths"]["wrapper"]["path"] = DLL_PATH
        invalid_records["duplicate role paths"] = duplicate_role_paths

        for reason, record in invalid_records.items():
            with self.subTest(reason=reason), self.assertRaises(Exception):
                self.service._validate_flatpak_active_record(record)

    def test_tampered_pending_set_cannot_remove_a_nonowned_grant(self):
        replacement_config = "/home/deck/.config/lsfg-vk-new"
        before = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": False, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        after = {
            "status": "active",
            "paths": {
                "config": {
                    "path": replacement_config,
                    "owned": True,
                    "present": True,
                },
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [CONFIG_PATH],
        }
        path = self.service._flatpak_ownership_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": 1,
            "apps": {APP_ID: {
                "status": "pending",
                "operation": "set",
                "before": before,
                "after": after,
            }},
        }), encoding="utf-8")

        with patch.object(self.service, "_run_flatpak_command") as command:
            result = self.service.set_app_override(APP_ID)

        command.assert_not_called()
        self.assertEqual(
            (result["success"], result["error_code"], result["ownership_status"]),
            (False, "ownership_blocked", "blocked"),
        )

    def test_tampered_pending_remove_requires_exact_baseline_transform(self):
        before = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        invalid_after = {
            "status": "baseline",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": False, "present": False},
                "dll": {"path": DLL_PATH, "owned": False, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": False, "present": False},
            },
            "retired_paths": [],
        }
        path = self.service._flatpak_ownership_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": 1,
            "apps": {APP_ID: {
                "status": "pending",
                "operation": "remove",
                "before": before,
                "after": invalid_after,
            }},
        }), encoding="utf-8")

        with patch.object(self.service, "_run_flatpak_command") as command:
            result = self.service.remove_app_override(APP_ID)

        command.assert_not_called()
        self.assertEqual(
            (result["success"], result["error_code"], result["ownership_status"]),
            (False, "ownership_blocked", "blocked"),
        )

    def test_ownership_writer_rejects_oversized_document_before_commit(self):
        active = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        document = {
            "schema": 1,
            "apps": {
                f"com.example.Game{index}": active
                for index in range(4_000)
            },
        }
        self.assertGreater(
            len(json.dumps(document, separators=(",", ":")).encode("utf-8")),
            FLATPAK_OWNERSHIP_MAX_BYTES,
        )
        coordinator = SimpleNamespace(commit=Mock())

        with self.assertRaisesRegex(Exception, "too large"):
            self.service._write_flatpak_ownership(coordinator, document)

        coordinator.commit.assert_not_called()

    def test_app_list_exposes_bounded_pending_operation_metadata(self):
        active = {
            "status": "active",
            "paths": {
                "config": {"path": CONFIG_PATH, "owned": True, "present": True},
                "dll": {"path": DLL_PATH, "owned": True, "present": True},
                "wrapper": {"path": WRAPPER_PATH, "owned": True, "present": True},
            },
            "retired_paths": [],
        }
        ownership_path = self.service._flatpak_ownership_path
        ownership_path.parent.mkdir(parents=True, exist_ok=True)
        ownership_path.write_text(json.dumps({
            "schema": 1,
            "apps": {
                APP_ID: {
                    "status": "pending",
                    "operation": "set",
                    "before": None,
                    "after": active,
                }
            },
        }), encoding="utf-8")

        def command(args, **_kwargs):
            if args == ["list", "--app"]:
                return _completed(stdout=f"Game\t{APP_ID}\n")
            return _completed(stdout=_override_output())

        with patch.object(self.service, "_run_flatpak_command", side_effect=command):
            result = self.service.get_flatpak_apps()

        app = result["apps"][0]
        self.assertEqual(app["ownership_status"], "pending")
        self.assertEqual(app["ownership_operation"], "set")
        self.assertEqual(app["ownership_error_code"], "ownership_pending")
        self.assertNotIn("ownership_detail", app)

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
