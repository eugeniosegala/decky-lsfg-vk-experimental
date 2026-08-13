"""Deterministic tests for the generated Vulkan-layer search environment."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk.configuration import ConfigurationService  # noqa: E402
from py_modules.lsfg_vk.config_schema_generated import (  # noqa: E402
    ALL_FIELDS,
    get_script_generation_logic,
)


class WrapperEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.service = ConfigurationService(logger=_Logger())
        self.service.local_share_dir = Path("/private/lsfg/implicit_layer.d")

    def _evaluate(self, extra_environment=None):
        lines = self.service._generate_layer_environment_lines()
        script = "\n".join(lines + [
            'printf "ADD=%s\\n" "${VK_ADD_IMPLICIT_LAYER_PATH:-}"',
            'printf "IMPLICIT=%s\\n" "${VK_IMPLICIT_LAYER_PATH:-}"',
        ])
        environment = {
            "PATH": os.environ.get("PATH", ""),
            **(extra_environment or {}),
        }
        result = subprocess.run(
            ["bash", "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        return dict(line.split("=", 1) for line in result.stdout.splitlines())

    def test_private_layer_is_added_before_standard_discovery(self):
        values = self._evaluate()
        self.assertEqual(values["ADD"], "/private/lsfg/implicit_layer.d")
        self.assertEqual(values["IMPLICIT"], "")

    def test_existing_additional_paths_are_preserved_after_private_layer(self):
        values = self._evaluate({
            "VK_ADD_IMPLICIT_LAYER_PATH": "/caller/one:/caller/two",
        })
        self.assertEqual(
            values["ADD"],
            "/private/lsfg/implicit_layer.d:/caller/one:/caller/two",
        )

    def test_caller_override_path_is_extended_when_add_path_would_be_ignored(self):
        values = self._evaluate({
            "VK_IMPLICIT_LAYER_PATH": "/caller/override",
            "VK_ADD_IMPLICIT_LAYER_PATH": "/ignored/by/loader",
        })
        self.assertEqual(
            values["IMPLICIT"],
            "/private/lsfg/implicit_layer.d:/caller/override",
        )
        self.assertEqual(values["ADD"], "/ignored/by/loader")

    def test_hdr_recovery_uses_legacy_isolation(self):
        values = self._evaluate({
            "LSFGVK_DISABLE_HDR_EXPOSURE": "1",
            "VK_IMPLICIT_LAYER_PATH": "/caller/override",
            "VK_ADD_IMPLICIT_LAYER_PATH": "/caller/additional",
        })
        self.assertEqual(values["IMPLICIT"], "/private/lsfg/implicit_layer.d")
        self.assertEqual(values["ADD"], "")

    def test_hdr_recovery_profile_generates_wrapper_export(self):
        lines = get_script_generation_logic()({"disable_hdr_exposure": True})
        self.assertIn("export LSFGVK_DISABLE_HDR_EXPOSURE=1", lines)

    def test_wrapper_never_exports_obsolete_wow64_workaround(self):
        self.assertNotIn("enable_wow64", ALL_FIELDS)
        lines = get_script_generation_logic()({"enable_wow64": True})
        self.assertNotIn("export PROTON_USE_WOW64=1", lines)

    def test_obsolete_wow64_profile_setting_is_discarded(self):
        settings = self.service._normalize_wrapper_settings({
            "enable_wow64": True,
            "disable_hdr_exposure": True,
        })
        self.assertNotIn("enable_wow64", settings)
        self.assertTrue(settings["disable_hdr_exposure"])

    def test_current_marker_with_obsolete_wow64_export_is_regenerated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.service.lsfg_script_path = Path(temp_dir) / "wrapper"
            self.service.lsfg_script_path.write_text(
                "\n".join([
                    self.service._WRAPPER_FORMAT_MARKER,
                    *self.service._REQUIRED_WRAPPER_EXPORTS,
                    "export PROTON_USE_WOW64=1",
                ]),
                encoding="utf-8",
            )
            self.service._get_profile_data = lambda: {}
            self.service.update_lsfg_script_from_profile_data = (
                lambda _profile_data: {"success": True}
            )

            self.assertTrue(self.service.migrate_launch_script_if_needed())


if __name__ == "__main__":
    unittest.main()
