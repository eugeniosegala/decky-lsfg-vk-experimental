"""RED contracts for recoverable engine installation and removal."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.state_transaction_fixtures import (
    TemporaryHome,
    snapshot_entry,
    snapshot_tree,
    write_bundled_engine,
    write_engine_archive,
)


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk import installation, state_transaction  # noqa: E402
from py_modules.lsfg_vk.constants import (  # noqa: E402
    EXPERIMENTAL_LAYER_BUILD_MARKER,
    LIB_FILENAME,
)
from py_modules.lsfg_vk.config_schema import (  # noqa: E402
    ConfigurationManager,
    DEFAULT_PROFILE_NAME,
    SCRIPT_ONLY_FIELDS,
)
from py_modules.lsfg_vk.installation import InstallationService  # noqa: E402
from py_modules.lsfg_vk.state_transaction import PathLayout  # noqa: E402


class _IndexedFailureInjector:
    def __init__(self, checkpoint: str, index: int | None = None):
        self.checkpoint = checkpoint
        self.index = index

    def hit(self, name: str, index: int | None = None) -> None:
        if name == self.checkpoint and (self.index is None or index == self.index):
            raise OSError(f"injected {name}[{index}] failure")


class _SimulatedCrash(BaseException):
    pass


class _CrashInjector:
    def __init__(self, checkpoint: str):
        self.checkpoint = checkpoint

    def hit(self, name: str, index: int | None = None) -> None:
        del index
        if name == self.checkpoint:
            raise _SimulatedCrash(f"injected crash at {name}")


class _LifecycleObserver:
    """Record externally visible lifecycle state after each durable apply step."""

    def __init__(self, layout: PathLayout):
        self.layout = layout
        self.states: list[dict[Path, bytes | None]] = []

    def hit(self, name: str, index: int | None = None) -> None:
        del index
        if name != "live_parent_fsync":
            return
        paths = (
            self.layout.registered_manifest64,
            self.layout.registered_manifest32,
            self.layout.private_library64,
            self.layout.private_library32,
            self.layout.engine_state,
        )
        self.states.append({
            path: path.read_bytes() if path.is_file() else None for path in paths
        })


class InstallationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.paths = TemporaryHome()
        self.addCleanup(self.paths.cleanup)
        self.bundle = self.paths.home / "bundle"
        write_bundled_engine(self.bundle)
        self.layout = PathLayout.from_home(self.paths.home)
        with patch.object(Path, "home", return_value=self.paths.home):
            self.service = InstallationService(logger=_Logger())
        # Make the service consume the release-like tree in this temporary home.
        self.module_file = self.bundle / "py_modules/lsfg_vk/installation.py"

    def _call_install(self):
        with patch.object(installation, "__file__", str(self.module_file)):
            return self.service.install()

    def _snapshot_without_lock(self):
        result = snapshot_tree(self.paths.home)
        result.pop(self.layout.lock_file.relative_to(self.paths.home).as_posix(), None)
        # A mutation lock is a persistent inode. Ignore its otherwise-empty
        # bootstrap directories when comparing managed/public state.
        for directory in (self.layout.config_dir, self.layout.config_dir.parent):
            key = directory.relative_to(self.paths.home).as_posix()
            if not any(name.startswith(f"{key}/") for name in result):
                result.pop(key, None)
        return result

    def _managed_public_snapshot(self):
        targets = (
            self.layout.config_file,
            self.layout.wrapper_settings,
            self.layout.launcher,
            self.layout.diagnostics_helper,
            self.layout.private_library64,
            self.layout.private_library32,
            self.layout.private_manifest64,
            self.layout.private_manifest32,
            self.layout.registered_manifest64,
            self.layout.registered_manifest32,
            self.layout.obsolete_hdr_manifest,
            self.layout.cli,
            self.layout.engine_state,
            *self.layout.legacy_private_manifests,
        )
        return {path: snapshot_entry(path) for path in targets}

    def _seed_installed_state(self) -> dict[Path, tuple[bytes, int]]:
        old = {
            self.layout.private_library64: (b"old-lib64", 0o644),
            self.layout.private_library32: (b"old-lib32", 0o644),
            self.layout.private_manifest64: (b'{"old": "private64"}\n', 0o644),
            self.layout.private_manifest32: (b'{"old": "private32"}\n', 0o644),
            self.layout.registered_manifest64: (b'{"old": "registered64"}\n', 0o644),
            self.layout.registered_manifest32: (b'{"old": "registered32"}\n', 0o644),
            self.layout.cli: (b"old-cli", 0o755),
            self.layout.launcher: (b"old-wrapper", 0o755),
            self.layout.diagnostics_helper: (b"old-helper", 0o755),
            self.layout.engine_state: (b'{"version": "old"}\n', 0o644),
        }
        for path, (content, mode) in old.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(mode)
        return old

    def _write_valid_user_state(self) -> None:
        defaults = ConfigurationManager.get_defaults()
        profile_data = {
            "current_profile": DEFAULT_PROFILE_NAME,
            "profiles": {DEFAULT_PROFILE_NAME: defaults},
            "global_config": {
                "dll": defaults.get("dll", ""),
                "allow_fp16": defaults.get("allow_fp16", True),
            },
        }
        self.layout.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.layout.config_file.write_text(
            ConfigurationManager.generate_toml_content_multi_profile(profile_data),
            encoding="utf-8",
        )
        wrapper = {field: defaults[field] for field in SCRIPT_ONLY_FIELDS}
        self.layout.wrapper_settings.write_text(json.dumps({
            "version": 1,
            "profiles": {DEFAULT_PROFILE_NAME: wrapper},
        }) + "\n", encoding="utf-8")

    def test_selector_uses_finite_lifecycle_set_and_excludes_user_state(self):
        selector = installation._select_install_or_update_locked
        lifecycle_rows = (
            self.layout.registered_manifest64,
            self.layout.registered_manifest32,
            self.layout.obsolete_hdr_manifest,
            self.layout.private_library64,
            self.layout.private_library32,
            self.layout.private_manifest64,
            self.layout.private_manifest32,
            self.layout.cli,
            self.layout.engine_state,
            *self.layout.legacy_private_manifests,
        )
        self.assertEqual(selector(self.layout), "install")
        for target in lifecycle_rows:
            with self.subTest(target=target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"partial")
                self.assertEqual(selector(self.layout), "update")
                target.unlink()
        excluded_rows = (
            self.layout.config_file,
            self.layout.wrapper_settings,
            self.layout.launcher,
            self.paths.home / ".local/share/shared-support",
            self.paths.home / ".local/share/flatpak/extension",
        )
        for target in excluded_rows:
            with self.subTest(excluded=target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"preserved")
                self.assertEqual(selector(self.layout), "install")
                target.unlink()

    def test_selector_treats_unsafe_lifecycle_type_as_update_then_install_fails_closed(self):
        self.layout.registered_manifest64.parent.mkdir(parents=True, exist_ok=True)
        self.layout.registered_manifest64.symlink_to("untrusted.json")
        before = self._snapshot_without_lock()

        self.assertEqual(
            installation._select_install_or_update_locked(self.layout), "update"
        )
        result = self._call_install()

        self.assertFalse(result["success"], result)
        self.assertEqual(self._snapshot_without_lock(), before)

    def test_duplicate_selected_archive_member_is_rejected_before_live_changes(self):
        archive = self.bundle / "bin/engine.tar.xz"
        checksum = write_engine_archive(
            archive,
            extra_members=((f"lib/{LIB_FILENAME}", b"duplicate" + EXPERIMENTAL_LAYER_BUILD_MARKER),),
        )
        manifest = json.loads((self.bundle / "package.json").read_text(encoding="utf-8"))
        manifest["remote_binary"][0]["sha256hash"] = checksum
        (self.bundle / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
        before = self._snapshot_without_lock()

        result = self._call_install()

        self.assertFalse(result["success"], result)
        self.assertRegex(result["error"], "(?i)duplicate")
        self.assertEqual(self._snapshot_without_lock(), before)

    def test_failed_fresh_install_retains_the_persistent_lock_inode(self):
        with patch.object(
            self.service,
            "_validate_archive_checksum",
            side_effect=OSError("injected validation failure"),
        ):
            result = self._call_install()

        self.assertFalse(result["success"], result)
        before = self.layout.lock_file.stat()
        coordinator = state_transaction.MutationCoordinator(self.layout)
        with coordinator.locked("configuration"):
            during = self.layout.lock_file.stat()
        after = self.layout.lock_file.stat()
        self.assertEqual((during.st_dev, during.st_ino), (before.st_dev, before.st_ino))
        self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))

    def test_archive_member_count_is_bounded_before_live_changes(self):
        archive = self.bundle / "bin/engine.tar.xz"
        checksum = write_engine_archive(
            archive,
            extra_members=tuple(
                (f"irrelevant/{index}.txt", b"") for index in range(4096)
            ),
        )
        manifest = json.loads((self.bundle / "package.json").read_text(encoding="utf-8"))
        manifest["remote_binary"][0]["sha256hash"] = checksum
        (self.bundle / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
        before = self._snapshot_without_lock()

        result = self._call_install()

        self.assertFalse(result["success"], result)
        self.assertRegex(result["error"], "(?i)(member|resource|limit|large)")
        self.assertEqual(self._snapshot_without_lock(), before)

    def test_fresh_install_writes_complete_target_set_with_expected_modes(self):
        result = self._call_install()

        self.assertTrue(result["success"], result)
        for target in (
            self.layout.private_library64, self.layout.private_library32,
            self.layout.private_manifest64, self.layout.private_manifest32,
            self.layout.registered_manifest64, self.layout.registered_manifest32,
            self.layout.cli, self.layout.launcher, self.layout.diagnostics_helper,
            self.layout.config_file, self.layout.wrapper_settings,
            self.layout.engine_state,
        ):
            with self.subTest(target=target):
                self.assertTrue(target.is_file(), target)
        self.assertEqual(snapshot_entry(self.layout.cli).mode, 0o755)
        self.assertEqual(snapshot_entry(self.layout.launcher).mode, 0o755)
        self.assertEqual(snapshot_entry(self.layout.diagnostics_helper).mode, 0o755)
        state = json.loads(self.layout.engine_state.read_text(encoding="utf-8"))
        self.assertEqual(state["version"], "test-version")
        self.assertNotIn("artifact_hashes", state)

    def test_fresh_install_publishes_registered_manifest_after_payload_and_marker_last(self):
        observer = _LifecycleObserver(self.layout)
        real_factory = state_transaction.MutationCoordinator

        def observing_factory(layout):
            return real_factory(layout, observer)

        with patch.object(state_transaction, "MutationCoordinator", side_effect=observing_factory):
            result = self._call_install()

        self.assertTrue(result["success"], result)
        manifest_visible = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.registered_manifest64] is not None
        )
        payload_visible = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.private_library64] is not None
        )
        marker_visible = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.engine_state] is not None
        )
        self.assertGreater(manifest_visible, payload_visible)
        self.assertEqual(marker_visible, len(observer.states) - 1)

    def test_fresh_install_accepts_archive_without_optional_cli(self):
        archive = self.bundle / "bin/engine.tar.xz"
        checksum = write_engine_archive(archive, include_cli=False)
        manifest = json.loads((self.bundle / "package.json").read_text(encoding="utf-8"))
        manifest["remote_binary"][0]["sha256hash"] = checksum
        (self.bundle / "package.json").write_text(json.dumps(manifest), encoding="utf-8")

        result = self._call_install()

        self.assertTrue(result["success"], result)
        self.assertFalse(self.layout.cli.exists())

    def test_existing_malformed_config_blocks_install_and_is_preserved_byte_identically(self):
        self.layout.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.layout.config_file.write_bytes(b"not = [valid toml\n")
        self.layout.config_file.chmod(0o640)
        before = self._snapshot_without_lock()

        result = self._call_install()

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_without_lock(), before)

    def test_existing_malformed_wrapper_json_blocks_install_and_preserves_all_bytes(self):
        self.layout.wrapper_settings.parent.mkdir(parents=True, exist_ok=True)
        self.layout.wrapper_settings.write_bytes(b'{"profiles": ')
        self.layout.wrapper_settings.chmod(0o600)
        before = self._snapshot_without_lock()

        result = self._call_install()

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_without_lock(), before)

    def test_missing_wrapper_json_with_existing_config_is_synthesized(self):
        self._write_valid_user_state()
        self.layout.wrapper_settings.unlink()
        config_before = self.layout.config_file.read_bytes()

        result = self._call_install()

        self.assertTrue(result["success"], result)
        self.assertEqual(self.layout.config_file.read_bytes(), config_before)
        wrapper = json.loads(self.layout.wrapper_settings.read_text(encoding="utf-8"))
        self.assertIn(DEFAULT_PROFILE_NAME, wrapper["profiles"])
        self.assertTrue(self.layout.launcher.is_file())

    def test_missing_config_with_existing_wrapper_json_is_synthesized(self):
        self._write_valid_user_state()
        self.layout.config_file.unlink()
        wrapper_before = self.layout.wrapper_settings.read_bytes()

        result = self._call_install()

        self.assertTrue(result["success"], result)
        self.assertEqual(self.layout.wrapper_settings.read_bytes(), wrapper_before)
        parsed = ConfigurationManager.parse_toml_content_multi_profile(
            self.layout.config_file.read_text(encoding="utf-8")
        )
        self.assertIn(DEFAULT_PROFILE_NAME, parsed["profiles"])
        self.assertTrue(self.layout.launcher.is_file())

    def test_future_wrapper_json_version_blocks_install_without_rewrite(self):
        self._write_valid_user_state()
        self.layout.wrapper_settings.write_bytes(b'{"version":999,"profiles":{}}\n')
        before = self._snapshot_without_lock()

        result = self._call_install()

        self.assertFalse(result["success"], result)
        self.assertEqual(result.get("error_code"), "invalid_persisted_state")
        self.assertEqual(self._snapshot_without_lock(), before)

    def test_precommit_apply_failure_restores_every_managed_file(self):
        self._seed_installed_state()
        before = self._snapshot_without_lock()
        real_factory = state_transaction.MutationCoordinator

        def failing_factory(layout):
            return real_factory(layout, _IndexedFailureInjector("live_replace", 3))

        with patch.object(state_transaction, "MutationCoordinator", side_effect=failing_factory):
            result = self._call_install()

        self.assertFalse(result["success"], result)
        self.assertEqual(self._snapshot_without_lock(), before)

    def test_update_from_dual_arch_to_64_only_removes_stale_32bit_atomically(self):
        old = self._seed_installed_state()
        write_bundled_engine(self.bundle, include_32bit=False)
        observer = _LifecycleObserver(self.layout)
        real_factory = state_transaction.MutationCoordinator

        def observing_factory(layout):
            return real_factory(layout, observer)

        with patch.object(state_transaction, "MutationCoordinator", side_effect=observing_factory):
            result = self._call_install()

        self.assertTrue(result["success"], result)
        self.assertFalse(self.layout.private_library32.exists())
        self.assertFalse(self.layout.private_manifest32.exists())
        self.assertFalse(self.layout.registered_manifest32.exists())
        deactivated = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.registered_manifest64] is None
            and state[self.layout.registered_manifest32] is None
        )
        payload_changed = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.private_library64] != old[self.layout.private_library64][0]
        )
        republished = next(
            index for index, state in enumerate(observer.states)
            if index > deactivated and state[self.layout.registered_manifest64] is not None
        )
        marker_changed = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.engine_state] != old[self.layout.engine_state][0]
        )
        self.assertLess(deactivated, payload_changed)
        self.assertLess(payload_changed, republished)
        self.assertEqual(marker_changed, len(observer.states) - 1)
        self.assertNotEqual(self.layout.registered_manifest64.read_bytes(), old[self.layout.registered_manifest64][0])

    def test_committed_install_cleanup_failure_recovers_new_state_without_reapplying(self):
        real_factory = state_transaction.MutationCoordinator

        def failing_factory(layout):
            return real_factory(layout, _IndexedFailureInjector("cleanup_journal"))

        with patch.object(state_transaction, "MutationCoordinator", side_effect=failing_factory):
            result = self._call_install()

        self.assertTrue(result["success"], result)
        self.assertTrue(result["recovery_pending"], result)
        committed = self._managed_public_snapshot()
        recovery = real_factory(self.layout).recover()
        self.assertTrue(recovery.refresh_required)
        self.assertEqual(self._managed_public_snapshot(), committed)
        self.assertFalse(self.layout.journal_file.exists())

    def test_uninstall_preserves_user_and_unrelated_state_and_is_idempotent(self):
        owned = self._seed_installed_state()
        self.layout.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.layout.config_file.write_bytes(b"user toml")
        self.layout.wrapper_settings.write_bytes(b"user json")
        unrelated = self.layout.registered_manifest64.parent / "unrelated.json"
        unrelated.write_bytes(b"external")
        extension = self.paths.home / ".local/share/flatpak/extension/shared"
        extension.parent.mkdir(parents=True, exist_ok=True)
        extension.write_bytes(b"shared")

        first = self.service.uninstall()
        second = self.service.uninstall()

        self.assertTrue(first["success"], first)
        self.assertEqual(set(first["removed_files"]), {str(path) for path in owned})
        self.assertTrue(second["success"], second)
        self.assertIsNone(second["removed_files"])
        self.assertEqual(self.layout.config_file.read_bytes(), b"user toml")
        self.assertEqual(self.layout.wrapper_settings.read_bytes(), b"user json")
        self.assertEqual(unrelated.read_bytes(), b"external")
        self.assertEqual(extension.read_bytes(), b"shared")

    def test_uninstall_precommit_failure_rolls_back_all_owned_files(self):
        self._seed_installed_state()
        before = self._snapshot_without_lock()
        real_factory = state_transaction.MutationCoordinator

        def failing_factory(layout):
            return real_factory(layout, _IndexedFailureInjector("live_replace", 2))

        with patch.object(state_transaction, "MutationCoordinator", side_effect=failing_factory):
            result = self.service.uninstall()

        self.assertFalse(result["success"], result)
        self.assertEqual(self._snapshot_without_lock(), before)

    def test_uninstall_deactivates_registered_manifests_before_payload_and_marker_last(self):
        old = self._seed_installed_state()
        observer = _LifecycleObserver(self.layout)
        real_factory = state_transaction.MutationCoordinator

        def observing_factory(layout):
            return real_factory(layout, observer)

        with patch.object(state_transaction, "MutationCoordinator", side_effect=observing_factory):
            result = self.service.uninstall()

        self.assertTrue(result["success"], result)
        deactivated = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.registered_manifest64] is None
            and state[self.layout.registered_manifest32] is None
        )
        payload_removed = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.private_library64] is None
        )
        marker_removed = next(
            index for index, state in enumerate(observer.states)
            if state[self.layout.engine_state] is None
        )
        self.assertEqual(observer.states[deactivated][self.layout.private_library64], old[self.layout.private_library64][0])
        self.assertLess(deactivated, payload_removed)
        self.assertEqual(marker_removed, len(observer.states) - 1)

    def test_committed_uninstall_cleanup_failure_recovers_absent_owned_state(self):
        owned = self._seed_installed_state()
        real_factory = state_transaction.MutationCoordinator

        def failing_factory(layout):
            return real_factory(layout, _IndexedFailureInjector("cleanup_journal"))

        with patch.object(state_transaction, "MutationCoordinator", side_effect=failing_factory):
            result = self.service.uninstall()

        self.assertTrue(result["success"], result)
        self.assertTrue(result.get("recovery_pending"), result)
        self.assertTrue(self.layout.journal_file.is_file())
        recovery = real_factory(self.layout).recover()
        self.assertTrue(recovery.refresh_required)
        self.assertFalse(self.layout.journal_file.exists())
        for path in owned:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_decky_cleanup_recovers_precommit_journal_then_removes_owned_files(self):
        owned = self._seed_installed_state()
        crashing = state_transaction.MutationCoordinator(
            self.layout, _CrashInjector("before_committed_journal_replace")
        )
        with self.assertRaises(_SimulatedCrash):
            crashing.commit(
                "configuration",
                replacements={self.layout.config_file: (b"changed config\n", 0o640)},
                removals=(),
            )

        result = self.service.cleanup_on_uninstall()

        self.assertTrue(result["success"], result)
        self.assertFalse(self.layout.journal_file.exists())
        for path in owned:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_decky_cleanup_finishes_committed_journal_then_removes_owned_files(self):
        owned = self._seed_installed_state()
        crashing = state_transaction.MutationCoordinator(
            self.layout, _CrashInjector("after_committed_journal_replace")
        )
        with self.assertRaises(_SimulatedCrash):
            crashing.commit(
                "configuration",
                replacements={self.layout.config_file: (b"committed config\n", 0o640)},
                removals=(),
            )

        result = self.service.cleanup_on_uninstall()

        self.assertTrue(result["success"], result)
        self.assertEqual(self.layout.config_file.read_bytes(), b"committed config\n")
        self.assertFalse(self.layout.journal_file.exists())
        for path in owned:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_decky_cleanup_reports_busy_without_claiming_cleanup(self):
        self._seed_installed_state()
        self.layout.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.layout.lock_file.write_bytes(b"")
        import fcntl

        descriptor = self.layout.lock_file.open("rb")
        self.addCleanup(descriptor.close)
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        result = self.service.cleanup_on_uninstall()

        self.assertFalse(result["success"], result)
        self.assertEqual(result["error_code"], "mutation_busy")

    def test_decky_cleanup_reports_blocked_and_preserves_evidence(self):
        owned = self._seed_installed_state()
        self.layout.journal_file.parent.mkdir(parents=True, exist_ok=True)
        self.layout.journal_file.write_bytes(b"invalid journal")

        result = self.service.cleanup_on_uninstall()

        self.assertFalse(result["success"], result)
        self.assertEqual(result["error_code"], "recovery_blocked")
        self.assertTrue(self.layout.journal_file.exists())
        for path in owned:
            with self.subTest(path=path):
                self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
