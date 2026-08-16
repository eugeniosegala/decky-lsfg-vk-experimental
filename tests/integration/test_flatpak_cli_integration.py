"""Real Flatpak CLI integration tests for per-app override ownership.

These tests intentionally run only in the dedicated Linux CI job. Unit tests
cover every state-machine branch with deterministic mocks; this suite verifies
that the same production service can mutate and parse a real Flatpak user
override keyfile without touching the runner's normal user state.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk.flatpak_service import FlatpakService  # noqa: E402


RUN_REAL_FLATPAK = os.environ.get("RUN_FLATPAK_INTEGRATION") == "1"
REAL_FLATPAK = shutil.which("flatpak")


@unittest.skipUnless(
    RUN_REAL_FLATPAK and sys.platform.startswith("linux") and REAL_FLATPAK,
    "requires RUN_FLATPAK_INTEGRATION=1 and a Linux Flatpak installation",
)
class RealFlatpakOverrideIntegrationTests(unittest.TestCase):
    """Exercise production ownership logic against isolated real overrides."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="lsfg-flatpak-integration-", dir=os.environ["HOME"]
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.xdg_data_home = self.root / "xdg-data"
        self.xdg_config_home = self.root / "xdg-config"
        self.xdg_state_home = self.root / "xdg-state"
        self.xdg_runtime_dir = self.root / "xdg-runtime"
        for directory in (
            self.home,
            self.xdg_data_home,
            self.xdg_config_home,
            self.xdg_state_home,
            self.xdg_runtime_dir,
        ):
            directory.mkdir(parents=True)
        self.xdg_runtime_dir.chmod(0o700)

        self.environment = patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "XDG_DATA_HOME": str(self.xdg_data_home),
                "XDG_CONFIG_HOME": str(self.xdg_config_home),
                "XDG_STATE_HOME": str(self.xdg_state_home),
                "XDG_RUNTIME_DIR": str(self.xdg_runtime_dir),
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.config_path = self.home / ".config" / "lsfg-vk"
        self.dll_a = self.home / "payload-a"
        self.dll_b = self.home / "payload-b"
        self.wrapper_path = self.home / ".local" / "bin" / "lsfg-vk-wrapper"
        for directory in (
            self.config_path,
            self.dll_a,
            self.dll_b,
            self.wrapper_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.wrapper_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.wrapper_path.chmod(0o755)

        self.fault_wrapper = self.root / "flatpak-fault-wrapper"
        self.fault_wrapper.write_text(
            """#!/usr/bin/env python3
import os
import subprocess
import sys

real = os.environ["LSFG_TEST_REAL_FLATPAK"]
args = sys.argv[1:]
marker = os.environ.get("LSFG_TEST_FAILURE_MARKER")
if (
    os.environ.get("LSFG_TEST_FAILURE_MODE") == "remove-readback"
    and args[:3] == ["override", "--user", "--show"]
    and marker
    and os.path.exists(marker)
):
    os.unlink(marker)
    print("injected failure while verifying a completed remove", file=sys.stderr)
    raise SystemExit(43)
if (
    os.environ.get("LSFG_TEST_FAILURE_MODE") == "partial-set"
    and args[:2] == ["override", "--user"]
    and "--show" not in args
    and any(arg.startswith("--filesystem=") for arg in args)
):
    app_id = args[-1]
    config_path = os.environ["LSFG_TEST_CONFIG_PATH"]
    completed = subprocess.run(
        [
            real,
            "override",
            "--user",
            f"--filesystem={config_path}:rw",
            app_id,
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    print("injected failure after applying only the config grant", file=sys.stderr)
    raise SystemExit(42)
if (
    os.environ.get("LSFG_TEST_FAILURE_MODE") == "remove-readback"
    and args[:3] == ["override", "--user", "--reset"]
):
    completed = subprocess.run([real, *args], check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    if not marker:
        raise SystemExit("LSFG_TEST_FAILURE_MARKER is required")
    with open(marker, "w", encoding="utf-8") as destination:
        destination.write("fail-next-readback\n")
    raise SystemExit(42)

os.execvpe(real, [real, *args], os.environ.copy())
""",
            encoding="utf-8",
        )
        self.fault_wrapper.chmod(0o755)

    def _app_id(self, scenario: str) -> str:
        return f"com.example.Lsfg{scenario}{uuid.uuid4().hex}"

    def _service(self, *, command: Path | str | None = None) -> FlatpakService:
        service = FlatpakService(logger=_Logger())
        service.user_home = self.home
        service.config_dir = self.config_path
        service.config_file_path = self.config_path / "conf.toml"
        service.lsfg_launch_script_path = self.wrapper_path
        service.flatpak_command = str(command or REAL_FLATPAK)
        return service

    @contextmanager
    def _ready_service(self, service: FlatpakService, dll_path: Path):
        with (
            patch.object(service, "check_flatpak_available", return_value=True),
            patch.object(service, "_get_app_runtime_version", return_value="24.08"),
            patch.object(service, "_is_extension_installed", return_value=True),
            patch.object(
                service,
                "_get_lsfg_paths",
                return_value=(str(self.config_path), str(dll_path)),
            ),
        ):
            yield

    def _flatpak(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(REAL_FLATPAK), *args],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )

    def _exact_states(
        self, service: FlatpakService, app_id: str, dll_path: Path
    ) -> dict[str, str]:
        with self._ready_service(service, dll_path):
            observed, error, exact_states = service._observe_app_override_snapshot(
                app_id
            )
        self.assertIsNotNone(observed, error)
        return exact_states

    def test_clean_add_readback_and_remove_round_trip(self):
        app_id = self._app_id("RoundTrip")
        service = self._service()

        with self._ready_service(service, self.dll_a):
            prepared = service.set_app_override(app_id)
        self.assertTrue(prepared["success"], prepared)
        self.assertEqual(prepared["outcome"], "complete")
        self.assertEqual(prepared["ownership_status"], "managed")

        states = self._exact_states(service, app_id, self.dll_a)
        self.assertEqual(states[str(self.config_path)], "grant_rw")
        self.assertEqual(states[str(self.dll_a)], "grant_ro")
        self.assertEqual(states[str(self.wrapper_path)], "grant_ro")
        ledger_mode = stat.S_IMODE(service._flatpak_ownership_path.stat().st_mode)
        self.assertEqual(ledger_mode, 0o600)

        with self._ready_service(service, self.dll_a):
            removed = service.remove_app_override(app_id)
        self.assertTrue(removed["success"], removed)
        self.assertEqual(removed["outcome"], "complete")
        self.assertEqual(removed["ownership_status"], "unmanaged")

        states = self._exact_states(service, app_id, self.dll_a)
        self.assertEqual(states.get(str(self.config_path), "absent"), "absent")
        self.assertEqual(states.get(str(self.dll_a), "absent"), "absent")
        self.assertEqual(states.get(str(self.wrapper_path), "absent"), "absent")

    def test_preexisting_user_grant_is_preserved_by_refusing_automation(self):
        app_id = self._app_id("Preexisting")
        self._flatpak(
            "override",
            "--user",
            f"--filesystem={self.config_path}:rw",
            app_id,
        )
        service = self._service()

        with self._ready_service(service, self.dll_a):
            prepared = service.set_app_override(app_id)
        self.assertFalse(prepared["success"], prepared)
        self.assertEqual(prepared["ownership_status"], "unknown")
        self.assertFalse(service._flatpak_ownership_path.exists())

        states = self._exact_states(service, app_id, self.dll_a)
        self.assertEqual(states[str(self.config_path)], "grant_rw")
        self.assertEqual(set(states), {str(self.config_path)})

    def test_wrong_mode_fails_closed_without_claiming_ownership(self):
        app_id = self._app_id("WrongMode")
        self._flatpak(
            "override",
            "--user",
            f"--filesystem={self.config_path}:ro",
            app_id,
        )
        service = self._service()

        with self._ready_service(service, self.dll_a):
            result = service.set_app_override(app_id)
        self.assertFalse(result["success"], result)
        self.assertEqual(result["ownership_status"], "unknown")
        self.assertFalse(service._flatpak_ownership_path.exists())

        states = self._exact_states(service, app_id, self.dll_a)
        self.assertEqual(states[str(self.config_path)], "grant_ro")
        self.assertEqual(states.get(str(self.dll_a), "absent"), "absent")
        self.assertEqual(states.get(str(self.wrapper_path), "absent"), "absent")

    def test_unrelated_socket_override_is_preserved_and_blocks_automation(self):
        app_id = self._app_id("Socket")
        self._flatpak("override", "--user", "--socket=wayland", app_id)
        service = self._service()

        with self._ready_service(service, self.dll_a):
            result = service.set_app_override(app_id)
        self.assertFalse(result["success"], result)
        self.assertEqual(result["ownership_status"], "unknown")
        self.assertFalse(service._flatpak_ownership_path.exists())

        output = self._flatpak("override", "--user", "--show", app_id).stdout
        self.assertIn("sockets=wayland;", output)
        self.assertNotIn(str(self.config_path), output)
        self.assertNotIn(str(self.dll_a), output)

    def test_interrupted_remove_readback_reconciles_after_service_restart(self):
        app_id = self._app_id("RemoveRecovery")
        service = self._service()
        with self._ready_service(service, self.dll_a):
            prepared = service.set_app_override(app_id)
        self.assertTrue(prepared["success"], prepared)

        marker = self.root / "fail-next-remove-readback"
        service.flatpak_command = str(self.fault_wrapper)
        with patch.dict(
            os.environ,
            {
                "LSFG_TEST_REAL_FLATPAK": str(REAL_FLATPAK),
                "LSFG_TEST_FAILURE_MODE": "remove-readback",
                "LSFG_TEST_FAILURE_MARKER": str(marker),
            },
        ):
            with self._ready_service(service, self.dll_a):
                interrupted = service.remove_app_override(app_id)

        self.assertFalse(interrupted["success"], interrupted)
        self.assertEqual(interrupted["outcome"], "unverified")
        self.assertEqual(interrupted["ownership_status"], "pending")

        restarted = self._service()
        with self._ready_service(restarted, self.dll_a):
            reconciled = restarted.remove_app_override(app_id)
        self.assertTrue(reconciled["success"], reconciled)
        self.assertEqual(reconciled["outcome"], "complete")
        self.assertEqual(reconciled["ownership_status"], "unmanaged")
        self.assertFalse(restarted._flatpak_ownership_path.exists())

    def test_partial_real_mutation_is_detected_and_retry_reconciles_it(self):
        app_id = self._app_id("Partial")
        service = self._service(command=self.fault_wrapper)
        with patch.dict(
            os.environ,
            {
                "LSFG_TEST_REAL_FLATPAK": str(REAL_FLATPAK),
                "LSFG_TEST_FAILURE_MODE": "partial-set",
                "LSFG_TEST_CONFIG_PATH": str(self.config_path),
            },
        ):
            with self._ready_service(service, self.dll_a):
                partial = service.set_app_override(app_id)

        self.assertFalse(partial["success"], partial)
        self.assertEqual(partial["outcome"], "partial")
        self.assertEqual(partial["ownership_status"], "pending")
        pending = json.loads(
            service._flatpak_ownership_path.read_text(encoding="utf-8")
        )
        self.assertEqual(pending["apps"][app_id]["status"], "pending")

        service.flatpak_command = str(REAL_FLATPAK)
        with self._ready_service(service, self.dll_a):
            reconciled = service.set_app_override(app_id)
        self.assertTrue(reconciled["success"], reconciled)
        self.assertEqual(reconciled["outcome"], "complete")
        self.assertEqual(reconciled["ownership_status"], "managed")

        states = self._exact_states(service, app_id, self.dll_a)
        self.assertEqual(states[str(self.config_path)], "grant_rw")
        self.assertEqual(states[str(self.dll_a)], "grant_ro")
        self.assertEqual(states[str(self.wrapper_path)], "grant_ro")

    def test_external_mode_change_blocks_destructive_remove(self):
        app_id = self._app_id("ExternalDrift")
        service = self._service()
        with self._ready_service(service, self.dll_a):
            prepared = service.set_app_override(app_id)
        self.assertTrue(prepared["success"], prepared)

        self._flatpak(
            "override",
            "--user",
            f"--filesystem={self.config_path}:ro",
            app_id,
        )
        with self._ready_service(service, self.dll_a):
            refused = service.remove_app_override(app_id)
        self.assertFalse(refused["success"], refused)
        self.assertEqual(refused["ownership_status"], "blocked")

        states = self._exact_states(service, app_id, self.dll_a)
        self.assertEqual(states[str(self.config_path)], "grant_ro")
        self.assertEqual(states[str(self.dll_a)], "grant_ro")
        self.assertEqual(states[str(self.wrapper_path)], "grant_ro")

    def test_dll_path_change_requires_safe_remove_before_reenable(self):
        app_id = self._app_id("PathCycle")
        service = self._service()

        with self._ready_service(service, self.dll_a):
            first = service.set_app_override(app_id)
        self.assertTrue(first["success"], first)

        with self._ready_service(service, self.dll_b):
            refused = service.set_app_override(app_id)
        self.assertFalse(refused["success"], refused)
        self.assertEqual(refused["ownership_status"], "blocked")

        with self._ready_service(service, self.dll_a):
            removed = service.remove_app_override(app_id)
        self.assertTrue(removed["success"], removed)

        with self._ready_service(service, self.dll_b):
            second = service.set_app_override(app_id)
        self.assertTrue(second["success"], second)

        states = self._exact_states(service, app_id, self.dll_b)
        self.assertEqual(states[str(self.dll_b)], "grant_ro")
        self.assertEqual(states.get(str(self.dll_a), "absent"), "absent")
        ledger = json.loads(service._flatpak_ownership_path.read_text(encoding="utf-8"))
        record = ledger["apps"][app_id]
        self.assertEqual(record["retired_paths"], [])
