"""Transactional consistency contracts for configuration/profile mutations."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.state_transaction_fixtures import TemporaryHome, snapshot_tree


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk.config_schema import (  # noqa: E402
    ConfigurationManager,
    DEFAULT_PROFILE_NAME,
    SCRIPT_ONLY_FIELDS,
)
from py_modules.lsfg_vk.configuration import ConfigurationService  # noqa: E402
from py_modules.lsfg_vk import state_transaction  # noqa: E402


class _IndexedFailureInjector:
    def __init__(self, checkpoint: str, index: int):
        self.checkpoint = checkpoint
        self.index = index

    def hit(self, name: str, index: int | None = None) -> None:
        if name == self.checkpoint and index == self.index:
            raise OSError(f"injected {name}[{index}] failure")


class ConfigurationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.paths = TemporaryHome()
        self.addCleanup(self.paths.cleanup)
        self.service = ConfigurationService(logger=_Logger())
        self.service.user_home = self.paths.home
        self.service.config_dir = self.paths.config_dir
        self.service.config_file_path = self.paths.toml
        self.service.wrapper_profile_settings_path = self.paths.wrapper_json
        self.service.lsfg_script_path = self.paths.launcher
        self.service.lsfg_launch_script_path = self.paths.launcher
        self.service.local_share_dir = self.paths.home / ".local/share/private-layer"

    def _write_valid_initial_state(self) -> None:
        defaults = ConfigurationManager.get_defaults()
        profile_data = {
            "current_profile": DEFAULT_PROFILE_NAME,
            "profiles": {DEFAULT_PROFILE_NAME: defaults},
            "global_config": {
                "dll": defaults.get("dll", ""),
                "allow_fp16": defaults.get("allow_fp16", True),
            },
        }
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.toml.write_text(
            ConfigurationManager.generate_toml_content_multi_profile(profile_data),
            encoding="utf-8",
        )
        wrapper_settings = {
            field: defaults[field] for field in SCRIPT_ONLY_FIELDS
        }
        self.paths.wrapper_json.write_text(
            json.dumps({
                "version": 1,
                "profiles": {DEFAULT_PROFILE_NAME: wrapper_settings},
            }, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.paths.launcher.parent.mkdir(parents=True, exist_ok=True)
        result = self.service.update_lsfg_script_from_profile_data(profile_data)
        self.assertTrue(result["success"], result)

    def _logical_state(self):
        toml = ConfigurationManager.parse_toml_content_multi_profile(
            self.paths.toml.read_text(encoding="utf-8")
        )
        wrapper = json.loads(self.paths.wrapper_json.read_text(encoding="utf-8"))
        script = self.paths.launcher.read_text(encoding="utf-8")
        return toml, wrapper, script

    def _snapshot_user_tree(self):
        """Ignore the coordinator's intentionally persistent advisory lock."""
        snapshot = snapshot_tree(self.paths.home)
        snapshot.pop(self.paths.lock.relative_to(self.paths.home).as_posix(), None)
        return snapshot

    def test_create_profile_creates_complete_consistent_triplet_from_absence(self):
        result = self.service.create_profile("Gaming")

        self.assertTrue(result["success"], result)
        self.assertTrue(self.paths.launcher.is_file())
        toml, wrapper, script = self._logical_state()
        self.assertIn("Gaming", toml["profiles"])
        self.assertIn("Gaming", wrapper["profiles"])
        self.assertIn(f"# Current profile: {DEFAULT_PROFILE_NAME}", script)

    def test_delete_profile_removes_it_from_toml_json_and_launcher_projection(self):
        self._write_valid_initial_state()
        self.assertTrue(self.service.create_profile("Gaming")["success"])
        self.assertTrue(self.service.set_current_profile("Gaming")["success"])

        result = self.service.delete_profile("Gaming")

        self.assertTrue(result["success"], result)
        toml, wrapper, script = self._logical_state()
        self.assertNotIn("Gaming", toml["profiles"])
        self.assertNotIn("Gaming", wrapper["profiles"])
        self.assertIn(f"# Current profile: {DEFAULT_PROFILE_NAME}", script)

    def test_rename_profile_updates_toml_json_and_current_launcher_together(self):
        self._write_valid_initial_state()
        self.assertTrue(self.service.create_profile("Gaming")["success"])
        self.assertTrue(self.service.set_current_profile("Gaming")["success"])

        result = self.service.rename_profile("Gaming", "Handheld")

        self.assertTrue(result["success"], result)
        toml, wrapper, script = self._logical_state()
        self.assertNotIn("Gaming", toml["profiles"])
        self.assertNotIn("Gaming", wrapper["profiles"])
        self.assertIn("Handheld", toml["profiles"])
        self.assertIn("Handheld", wrapper["profiles"])
        self.assertEqual(toml["current_profile"], "Handheld")
        self.assertIn("# Current profile: Handheld", script)

    def test_set_current_profile_updates_toml_and_launcher_from_same_snapshot(self):
        self._write_valid_initial_state()
        self.assertTrue(self.service.create_profile("Gaming")["success"])

        result = self.service.set_current_profile("Gaming")

        self.assertTrue(result["success"], result)
        toml, wrapper, script = self._logical_state()
        self.assertEqual(toml["current_profile"], "Gaming")
        self.assertIn("Gaming", wrapper["profiles"])
        self.assertIn("# Current profile: Gaming", script)

    def test_update_current_profile_updates_all_three_representations(self):
        self._write_valid_initial_state()
        updated = ConfigurationManager.get_defaults()
        updated["multiplier"] = 3
        updated["target_fps"] = 90
        updated["disable_lsfgvk"] = True

        result = self.service.update_profile_config(DEFAULT_PROFILE_NAME, updated)

        self.assertTrue(result["success"], result)
        toml, wrapper, script = self._logical_state()
        self.assertEqual(toml["profiles"][DEFAULT_PROFILE_NAME]["multiplier"], 3)
        self.assertTrue(
            wrapper["profiles"][DEFAULT_PROFILE_NAME]["disable_lsfgvk"]
        )
        parsed_script = ConfigurationManager.parse_script_content(script)
        self.assertTrue(parsed_script["disable_lsfgvk"])

    def test_malformed_toml_blocks_mutation_and_preserves_every_byte(self):
        self.paths.write_triplet(toml=b"not = [valid toml\n")
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_malformed_wrapper_json_blocks_mutation_and_preserves_every_byte(self):
        self._write_valid_initial_state()
        self.paths.wrapper_json.write_bytes(b'{"version": 1, "profiles": ')
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_duplicate_wrapper_document_key_blocks_mutation_and_preserves_bytes(self):
        self._write_valid_initial_state()
        content = b'{"version":1,"version":1,"profiles":{"Default":{}}}\n'
        self.paths.wrapper_json.write_bytes(content)
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self.paths.wrapper_json.read_bytes(), content)
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_duplicate_wrapper_profile_key_blocks_mutation_and_preserves_bytes(self):
        self._write_valid_initial_state()
        content = b'{"version":1,"profiles":{"Default":{},"Default":{}}}\n'
        self.paths.wrapper_json.write_bytes(content)
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self.paths.wrapper_json.read_bytes(), content)
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_duplicate_wrapper_field_key_blocks_mutation_and_preserves_bytes(self):
        self._write_valid_initial_state()
        content = (
            b'{"version":1,"profiles":{"Default":'
            b'{"disable_lsfgvk":false,"disable_lsfgvk":true}}}\n'
        )
        self.paths.wrapper_json.write_bytes(content)
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self.paths.wrapper_json.read_bytes(), content)
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_future_wrapper_settings_version_blocks_mutation_without_rewrite(self):
        self._write_valid_initial_state()
        self.paths.wrapper_json.write_text(
            '{"version": 999, "profiles": {}}\n', encoding="utf-8"
        )
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_missing_wrapper_settings_version_blocks_mutation_without_rewrite(self):
        self._write_valid_initial_state()
        self.paths.wrapper_json.write_text(
            '{"profiles": {}}\n', encoding="utf-8"
        )
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_unknown_wrapper_setting_blocks_mutation_without_rewrite(self):
        self._write_valid_initial_state()
        payload = json.loads(self.paths.wrapper_json.read_text(encoding="utf-8"))
        payload["profiles"][DEFAULT_PROFILE_NAME]["future_toggle"] = True
        self.paths.wrapper_json.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_unknown_wrapper_document_key_blocks_mutation_without_rewrite(self):
        self._write_valid_initial_state()
        payload = json.loads(self.paths.wrapper_json.read_text(encoding="utf-8"))
        payload["metadata"] = {"producer": "future-version"}
        self.paths.wrapper_json.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_wrong_wrapper_primitive_type_blocks_mutation_without_rewrite(self):
        self._write_valid_initial_state()
        payload = json.loads(self.paths.wrapper_json.read_text(encoding="utf-8"))
        payload["profiles"][DEFAULT_PROFILE_NAME]["disable_lsfgvk"] = "false"
        self.paths.wrapper_json.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_wrapper_profile_set_mismatch_blocks_mutation_without_data_loss(self):
        self._write_valid_initial_state()
        payload = json.loads(self.paths.wrapper_json.read_text(encoding="utf-8"))
        payload["profiles"]["Orphan"] = dict(
            payload["profiles"][DEFAULT_PROFILE_NAME]
        )
        self.paths.wrapper_json.write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
        before = self._snapshot_user_tree()

        result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_legacy_multi_profile_migration_creates_complete_wrapper_state(self):
        self._write_valid_initial_state()
        self.assertTrue(self.service.create_profile("Gaming")["success"])
        self.paths.wrapper_json.unlink()

        migrated = self.service.migrate_wrapper_profile_settings_if_needed()
        wrapper = json.loads(self.paths.wrapper_json.read_text(encoding="utf-8"))
        profile_data = ConfigurationManager.parse_toml_content_multi_profile(
            self.paths.toml.read_text(encoding="utf-8")
        )

        self.assertTrue(migrated)
        self.assertEqual(set(wrapper["profiles"]), set(profile_data["profiles"]))
        result = self.service.create_profile("Handheld")
        self.assertTrue(result["success"], result)

    def test_profile_set_mismatch_is_visible_on_config_and_profile_reads(self):
        self._write_valid_initial_state()
        self.assertTrue(self.service.create_profile("Gaming")["success"])
        complete = json.loads(self.paths.wrapper_json.read_text(encoding="utf-8"))
        mismatches = {
            "missing": {
                "version": complete["version"],
                "profiles": {
                    DEFAULT_PROFILE_NAME: complete["profiles"][DEFAULT_PROFILE_NAME]
                },
            },
            "extra": {
                "version": complete["version"],
                "profiles": {
                    **complete["profiles"],
                    "Orphan": dict(complete["profiles"][DEFAULT_PROFILE_NAME]),
                },
            },
        }

        for mismatch, payload in mismatches.items():
            with self.subTest(mismatch=mismatch):
                self.paths.wrapper_json.write_text(
                    json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
                )
                before = self._snapshot_user_tree()

                config_result = self.service.get_config()
                profiles_result = self.service.get_profiles()

                self.assertEqual(
                    config_result.get("error_code"), "invalid_persisted_state"
                )
                self.assertTrue(config_result.get("warning"))
                self.assertEqual(
                    profiles_result.get("error_code"), "invalid_persisted_state"
                )
                self.assertIs(profiles_result.get("status_available"), False)
                self.assertEqual(self._snapshot_user_tree(), before)

    def test_get_config_does_not_migrate_or_write_missing_wrapper_settings(self):
        self._write_valid_initial_state()
        self.paths.wrapper_json.unlink()
        self.paths.launcher.write_text(
            "#!/bin/sh\nexport LSFGVK_DISABLE_HDR_EXPOSURE=1\nexec \"$@\"\n",
            encoding="utf-8",
        )
        before = self._snapshot_user_tree()

        result = self.service.get_config()

        self.assertTrue(result["success"], result)
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_launcher_render_failure_returns_failure_and_preserves_triplet(self):
        self._write_valid_initial_state()
        before = self._snapshot_user_tree()

        with patch.object(
            self.service,
            "_generate_script_content_for_profile",
            side_effect=ValueError("cannot render launcher"),
        ):
            result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "durability_failure")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_launcher_apply_failure_returns_failure_instead_of_warning_success(self):
        self._write_valid_initial_state()
        self.assertTrue(self.service.create_profile("Gaming")["success"])
        before = self._snapshot_user_tree()
        real_coordinator = state_transaction.MutationCoordinator

        def failing_coordinator(layout):
            return real_coordinator(
                layout,
                _IndexedFailureInjector("live_replace", 2),
            )

        with patch.object(
            state_transaction,
            "MutationCoordinator",
            side_effect=failing_coordinator,
        ):
            result = self.service.set_current_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "durability_failure")
        self.assertEqual(self._snapshot_user_tree(), before)

    def test_commit_refresh_required_is_a_failure_not_success(self):
        self._write_valid_initial_state()
        before = self._snapshot_user_tree()

        with patch.object(
            state_transaction.MutationCoordinator,
            "commit",
            return_value=state_transaction.TransactionResult(refresh_required=True),
        ):
            result = self.service.create_profile("Gaming")

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "refresh_required")
        self.assertEqual(result.get("recovery_action"), "refresh")
        self.assertEqual(self._snapshot_user_tree(), before)


if __name__ == "__main__":
    unittest.main()
