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
[Vulkan Loader] Loading VK_LAYER_LSFGVK_experimental_frame_generation
[Gamescope WSI] HDR output available
lsfg-vk: experimental layer active; identity=VK_LAYER_LSFGVK_experimental_frame_generation; build=2.0.0-dev28-experimental.25
lsfg-vk: swapchain colour pipeline: format=64; color-space=1000104008; mode=hdr10-pq; frame-generation=supported
lsfg-vk: Gamescope application HDR feedback stabilized: active=1; contexts_pending_recreation=1
lsfg-vk: present diagnostics: operation=swapchain-context-create context=1
lsfg-vk: present diagnostics: operation=runtime-transition-pending context=1 state_revision=2 reason=profile-resources action=wait-for-natural-swapchain-recreation
lsfg-vk: present diagnostics: operation=runtime-state-applied context=2 state_revision=2 adaptive=1 target_fps=110 hdr=1
lsfg-vk: present diagnostics: operation=adaptive-ramp context=1 old_limit=0 new_limit=1
lsfg-vk: present diagnostics: operation=fixed-plan context=2 base_fps=61.2 multiplier=2 generated_per_real=1 observed_output_fps=122.4 generated_presented=61 generated_skipped=0 configured_adaptive_target_fps=110 target_applies=0
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
        self.assertIn("experimental layer active", result.stdout)
        self.assertNotIn("adaptive-ramp", result.stdout)

    def test_multiple_presets_combine_recovery_and_adaptive(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._fixture_path(Path(temporary_directory))
            result = self._run("--log", str(path), "adaptive", "recovery")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("adaptive-ramp", result.stdout)
        self.assertIn("runtime-state-applied", result.stdout)
        self.assertIn("skip-generated-frames", result.stdout)
        self.assertIn("experimental layer active", result.stdout)
        self.assertNotIn("mode=hdr10-pq", result.stdout)

    def test_every_preset_keeps_the_authoritative_build_marker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._fixture_path(Path(temporary_directory))
            for preset in (
                "hdr", "config", "adaptive", "recovery", "performance", "lifecycle",
                "startup", "layers", "errors", "all",
            ):
                with self.subTest(preset=preset):
                    result = self._run("--log", str(path), preset)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("experimental layer active", result.stdout)

    def test_config_preset_correlates_requested_and_applied_state(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._fixture_path(Path(temporary_directory))
            result = self._run("--log", str(path), "config")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("runtime-transition-pending", result.stdout)
        self.assertIn("wait-for-natural-swapchain-recreation", result.stdout)
        self.assertIn("runtime-state-applied", result.stdout)
        self.assertNotIn("runtime-transition-recreation-requested", result.stdout)
        self.assertNotIn("adaptive-ramp", result.stdout)

    def test_performance_preset_includes_fixed_multiplier_telemetry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._fixture_path(Path(temporary_directory))
            result = self._run("--log", str(path), "performance")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("operation=fixed-plan", result.stdout)
        self.assertIn("generated_skipped=0", result.stdout)
        self.assertNotIn("adaptive-ramp", result.stdout)

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
