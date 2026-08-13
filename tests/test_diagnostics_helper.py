"""Deterministic tests for the installed diagnostics preset helper."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


PROJECT_DIR = Path(__file__).resolve().parent.parent
HELPER = PROJECT_DIR / "scripts" / "lsfg-vk-experimental-diagnostics"


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk.installation import InstallationService  # noqa: E402

FIXTURE = """\
[Vulkan Loader] Loading VK_LAYER_LSFGVK_frame_generation
[Gamescope WSI] HDR output available
lsfg-vk: swapchain colour pipeline: format=64; color-space=1000104008; mode=hdr10-pq; frame-generation=supported
lsfg-vk: present diagnostics: operation=swapchain-context-create context=1
lsfg-vk: present diagnostics: operation=adaptive-ramp context=1 old_limit=0 new_limit=1
lsfg-vk: present diagnostics: operation=acquire-generated-image context=1 duration_ms=50 result=VK_TIMEOUT
lsfg-vk: present diagnostics: operation=skip-generated-frames context=1 reason=initial-timeout
lsfg-vk: LSFG frame-generation initialization failed; native presentation retained: test failure
unrelated application output
"""


class DiagnosticsHelperTests(unittest.TestCase):
    def _run(self, *arguments, environment=None):
        return subprocess.run(
            ["bash", str(HELPER), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def _fixture_path(self, directory: Path) -> Path:
        path = directory / "diagnostics.log"
        path.write_text(FIXTURE, encoding="utf-8")
        return path

    def test_hdr_preset_excludes_adaptive_policy(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._fixture_path(Path(temporary_directory))
            result = self._run("--log", str(path), "hdr")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mode=hdr10-pq", result.stdout)
        self.assertIn("initialization failed", result.stdout)
        self.assertNotIn("adaptive-ramp", result.stdout)

    def test_multiple_presets_combine_recovery_and_adaptive(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._fixture_path(Path(temporary_directory))
            result = self._run("--log", str(path), "adaptive", "recovery")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("adaptive-ramp", result.stdout)
        self.assertIn("skip-generated-frames", result.stdout)
        self.assertNotIn("mode=hdr10-pq", result.stdout)

    def test_startup_includes_loader_gamescope_context_and_hdr(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._fixture_path(Path(temporary_directory))
            result = self._run("--log", str(path), "startup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Vulkan Loader", result.stdout)
        self.assertIn("Gamescope WSI", result.stdout)
        self.assertIn("swapchain-context-create", result.stdout)
        self.assertIn("mode=hdr10-pq", result.stdout)

    def test_private_log_is_selected_from_home(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            path = home / ".config/decky-lsfg-vk-experimental/present-diagnostics.log"
            path.parent.mkdir(parents=True)
            path.write_text(FIXTURE, encoding="utf-8")
            environment = {**os.environ, "HOME": str(home)}
            environment.pop("LSFGVK_PRESENT_DIAGNOSTICS_LOG", None)
            result = self._run("errors", environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VK_TIMEOUT", result.stdout)
        self.assertIn("initialization failed", result.stdout)
        self.assertIn(str(path), result.stderr)

    def test_invalid_preset_and_line_count_fail_clearly(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._fixture_path(Path(temporary_directory))
            invalid_preset = self._run("--log", str(path), "not-a-preset")
            invalid_lines = self._run(
                "--log", str(path), "--lines", "0", "all"
            )
        self.assertEqual(invalid_preset.returncode, 2)
        self.assertIn("Unknown preset", invalid_preset.stderr)
        self.assertEqual(invalid_lines.returncode, 2)
        self.assertIn("positive integer", invalid_lines.stderr)

    def test_plugin_migration_installs_and_refreshes_executable_helper(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "lsfg-vk-experimental-diagnostics"
            service = InstallationService(logger=_Logger())
            service.diagnostics_script_path = destination

            self.assertTrue(service.migrate_diagnostics_helper_if_needed())
            self.assertEqual(destination.read_bytes(), HELPER.read_bytes())
            self.assertTrue(destination.stat().st_mode & 0o111)
            self.assertFalse(service.migrate_diagnostics_helper_if_needed())

            destination.write_text("outdated\n", encoding="utf-8")
            self.assertTrue(service.migrate_diagnostics_helper_if_needed())
            self.assertEqual(destination.read_bytes(), HELPER.read_bytes())


if __name__ == "__main__":
    unittest.main()
