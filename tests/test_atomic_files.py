"""TDD contracts for the filesystem transaction primitive."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, patch

from tests.state_transaction_fixtures import (
    TemporaryHome,
    snapshot_entry,
    snapshot_tree,
)


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk.base_service import BaseService  # noqa: E402


PRECOMMIT_FAULT_CHECKPOINTS = (
    "journal_temp_create",
    "journal_temp_write",
    "journal_temp_file_fsync",
    "journal_replace",
    "journal_parent_fsync",
    "stage_create",
    "stage_write",
    "stage_chmod",
    "stage_file_fsync",
    "stage_parent_fsync",
    "backup_create",
    "backup_write",
    "backup_file_fsync",
    "backup_parent_fsync",
    "prepared",
    "old_identity_revalidation",
    "live_replace",
    "live_parent_fsync",
    "new_identity_verification",
    "progress_journal_rewrite",
    "full_new_state_verification",
    "before_committed_journal_replace",
)


def _transaction_api():
    """Import lazily so unrelated characterization tests still run in RED."""
    from py_modules.lsfg_vk.state_transaction import (  # type: ignore[import-not-found]
        FaultInjector,
        MutationBlockedError,
        MutationCoordinator,
        PathLayout,
    )

    return FaultInjector, MutationBlockedError, MutationCoordinator, PathLayout


class InjectedFailure(OSError):
    pass


class SimulatedCrash(BaseException):
    pass


class CheckpointInjector:
    """Small fault seam matching the plan's ``FaultInjector.hit`` contract."""

    def __init__(self, checkpoint: str, exception: BaseException):
        self.checkpoint = checkpoint
        self.exception = exception
        self.hits: list[tuple[str, int | None]] = []

    def hit(self, name: str, index: int | None = None) -> None:
        self.hits.append((name, index))
        if name == self.checkpoint:
            raise self.exception


class OccurrenceInjector:
    def __init__(self, checkpoint: str, occurrence: int, action):
        self.checkpoint = checkpoint
        self.occurrence = occurrence
        self.action = action
        self.count = 0

    def hit(self, name: str, index: int | None = None) -> None:
        if name != self.checkpoint:
            return
        self.count += 1
        if self.count == self.occurrence:
            if isinstance(self.action, BaseException):
                raise self.action
            self.action(index)


class AtomicFileTests(unittest.TestCase):
    def setUp(self):
        self.paths = TemporaryHome()
        self.addCleanup(self.paths.cleanup)

    def _coordinator(self, injector=None):
        _, _, coordinator_type, layout_type = _transaction_api()
        return coordinator_type(layout_type.from_home(self.paths.home), injector)

    @staticmethod
    def _prime_lock(coordinator) -> None:
        """Make the persistent lock file part of the test's initial state."""
        with coordinator.locked("configuration"):
            pass

    def test_direct_write_failure_does_not_destroy_existing_file(self):
        target = self.paths.toml
        target.parent.mkdir(parents=True)
        target.write_bytes(b"valuable old config\n")
        target.chmod(0o640)
        before = snapshot_entry(target)
        service = BaseService(logger=_Logger())

        with (
            patch.object(os, "fsync", side_effect=OSError("simulated disk failure")),
            self.assertRaises(OSError),
        ):
            service._write_file(target, "replacement config\n", 0o644)

        self.assertEqual(snapshot_entry(target), before)

    def test_direct_write_parent_fsync_failure_restores_existing_file(self):
        target = self.paths.toml
        target.parent.mkdir(parents=True)
        target.write_bytes(b"valuable old config\n")
        target.chmod(0o640)
        before = snapshot_entry(target)
        service = BaseService(logger=_Logger())
        calls = 0
        real_fsync = os.fsync

        def fail_second_fsync(descriptor):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated parent fsync failure")
            return real_fsync(descriptor)

        with (
            patch.object(os, "fsync", side_effect=fail_second_fsync),
            self.assertRaises(OSError),
        ):
            service._write_file(target, "replacement config\n", 0o644)

        self.assertEqual(snapshot_entry(target), before)

    def test_stage_failure_preserves_old_content_type_mode_and_unrelated_file(self):
        self.paths.write_triplet()
        unrelated = self.paths.config_dir / "user-note"
        unrelated.write_bytes(b"never touch me")
        unrelated.chmod(0o604)
        coordinator = self._coordinator(
            CheckpointInjector("stage_file_fsync", InjectedFailure("disk full"))
        )
        self._prime_lock(coordinator)
        before = snapshot_tree(self.paths.home)

        with self.assertRaises(InjectedFailure):
            coordinator.commit(
                "configuration",
                replacements={self.paths.toml: (b"new toml\n", 0o644)},
                removals=(),
            )

        self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_each_precommit_fault_restores_complete_old_snapshot(self):
        for checkpoint in PRECOMMIT_FAULT_CHECKPOINTS:
            with self.subTest(checkpoint=checkpoint):
                self.paths.cleanup()
                self.paths = TemporaryHome()
                self.addCleanup(self.paths.cleanup)
                self.paths.write_triplet()
                unrelated = self.paths.home / "unrelated-sentinel"
                unrelated.write_bytes(b"preserve me")
                injector = CheckpointInjector(
                    checkpoint, InjectedFailure(f"failure at {checkpoint}")
                )
                coordinator = self._coordinator(injector)
                self._prime_lock(coordinator)
                before = snapshot_tree(self.paths.home)

                with self.assertRaises(InjectedFailure):
                    coordinator.commit(
                        "configuration",
                        replacements={
                            self.paths.toml: (b"new toml\n", 0o644),
                            self.paths.wrapper_json: (
                                b'{"version":1,"profiles":{}}\n',
                                0o644,
                            ),
                        },
                        removals=(self.paths.launcher,),
                    )

                self.assertIn((checkpoint, ANY), injector.hits)
                self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_snapshot_rejects_symlink_instead_of_following_it(self):
        _, blocked_error, coordinator_type, layout_type = _transaction_api()
        outside = self.paths.home / "outside"
        outside.write_bytes(b"outside")
        self.paths.toml.parent.mkdir(parents=True)
        self.paths.toml.symlink_to(outside)
        coordinator = coordinator_type(layout_type.from_home(self.paths.home))
        self._prime_lock(coordinator)
        before = snapshot_tree(self.paths.home)

        with self.assertRaises(blocked_error):
            coordinator.commit(
                "configuration",
                replacements={self.paths.toml: (b"replacement", 0o644)},
                removals=(),
            )

        self.assertEqual(snapshot_tree(self.paths.home), before)
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_directory_bootstrap_rejects_managed_home_symlink_without_outside_writes(self):
        _, blocked_error, coordinator_type, layout_type = _transaction_api()
        with tempfile.TemporaryDirectory() as outside_name:
            outside = Path(outside_name)
            sentinel = outside / "sentinel"
            sentinel.write_bytes(b"outside must remain unchanged")
            (self.paths.home / ".config").mkdir()
            self.paths.config_dir.symlink_to(outside, target_is_directory=True)
            coordinator = coordinator_type(layout_type.from_home(self.paths.home))

            with self.assertRaises(blocked_error):
                coordinator.commit(
                    "configuration",
                    replacements={self.paths.toml: (b"forbidden", 0o644)},
                    removals=(),
                )

            self.assertEqual(sentinel.read_bytes(), b"outside must remain unchanged")
            self.assertFalse((outside / self.paths.lock.name).exists())
            self.assertFalse((outside / self.paths.journal.name).exists())

    def test_snapshot_rejects_directory_at_regular_file_target(self):
        _, blocked_error, coordinator_type, layout_type = _transaction_api()
        self.paths.toml.mkdir(parents=True)
        coordinator = coordinator_type(layout_type.from_home(self.paths.home))
        self._prime_lock(coordinator)
        before = snapshot_tree(self.paths.home)

        with self.assertRaises(blocked_error):
            coordinator.commit(
                "configuration",
                replacements={self.paths.toml: (b"replacement", 0o644)},
                removals=(),
            )

        self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_successful_replacement_applies_requested_permission_mode(self):
        self.paths.write_triplet()
        coordinator = self._coordinator()

        result = coordinator.commit(
            "configuration",
            replacements={self.paths.toml: (b"new toml\n", 0o600)},
            removals=(),
        )

        self.assertTrue(result.committed)
        self.assertFalse(result.recovery_pending)
        self.assertEqual(snapshot_entry(self.paths.toml).content, b"new toml\n")
        self.assertEqual(snapshot_entry(self.paths.toml).mode, 0o600)

    def test_commit_rejects_target_outside_operation_allowlist(self):
        _, blocked_error, coordinator_type, layout_type = _transaction_api()
        outside = self.paths.home / "not-managed"
        coordinator = coordinator_type(layout_type.from_home(self.paths.home))

        with self.assertRaises(blocked_error):
            coordinator.commit(
                "configuration",
                replacements={outside: (b"forbidden", 0o644)},
                removals=(),
            )

        self.assertEqual(snapshot_entry(outside).kind, "absent")
        self.assertFalse(self.paths.journal.exists())

    def test_precommit_crash_recovers_exact_old_bytes_and_modes(self):
        self.paths.write_triplet()
        before = {path: snapshot_entry(path) for path in self.paths.managed_paths()}
        crashing = self._coordinator(
            CheckpointInjector(
                "before_committed_journal_replace", SimulatedCrash("power loss")
            )
        )

        with self.assertRaises(SimulatedCrash):
            crashing.commit(
                "configuration",
                replacements={
                    self.paths.toml: (b"new toml\n", 0o644),
                    self.paths.wrapper_json: (b'{"version":1,"profiles":{}}\n', 0o644),
                    self.paths.launcher: (b"#!/bin/sh\nexit 0\n", 0o755),
                },
                removals=(),
            )

        recovered = self._coordinator().recover()

        self.assertTrue(recovered.refresh_required)
        self.assertEqual(
            {path: snapshot_entry(path) for path in self.paths.managed_paths()}, before
        )
        self.assertFalse(self.paths.journal.exists())

    def test_update_duplicate_chain_recovers_before_first_apply_and_is_idempotent(self):
        _, _, _, layout_type = _transaction_api()
        layout = layout_type.from_home(self.paths.home)
        old = {
            layout.registered_manifest64: (b"old registered\n", 0o640),
            layout.private_library64: (b"old library\n", 0o600),
            layout.engine_state: (b"old marker\n", 0o644),
        }
        for path, (content, mode) in old.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(mode)
        crashing = self._coordinator(
            OccurrenceInjector("stage_create", 1, SimulatedCrash("power loss"))
        )

        with self.assertRaises(SimulatedCrash):
            crashing.commit(
                "update",
                replacements={},
                removals=(),
                ordered_steps=(
                    (layout.registered_manifest64, "remove", None, 0),
                    (layout.private_library64, "replace", b"new library\n", 0o644),
                    (layout.registered_manifest64, "replace", b"new registered\n", 0o644),
                    (layout.engine_state, "replace", b"new marker\n", 0o644),
                ),
            )

        first = self._coordinator().recover()
        second = self._coordinator().recover()

        self.assertTrue(first.refresh_required)
        self.assertFalse(second.refresh_required)
        for path, (content, mode) in old.items():
            self.assertEqual(snapshot_entry(path).content, content)
            self.assertEqual(snapshot_entry(path).mode, mode)
        self.assertFalse(self.paths.journal.exists())

    def test_commit_rejects_invalid_lifecycle_order_for_each_operation(self):
        _, blocked_error, _, layout_type = _transaction_api()
        layout = layout_type.from_home(self.paths.home)
        cases = {
            "install": (
                (layout.registered_manifest64, "replace", b"manifest", 0o644),
                (layout.private_library64, "replace", b"library", 0o644),
                (layout.engine_state, "replace", b"marker", 0o644),
            ),
            "update": (
                (layout.private_library64, "replace", b"library", 0o644),
                (layout.registered_manifest64, "remove", None, 0),
                (layout.registered_manifest64, "replace", b"manifest", 0o644),
                (layout.engine_state, "replace", b"marker", 0o644),
            ),
            "uninstall": (
                (layout.private_library64, "remove", None, 0),
                (layout.registered_manifest64, "remove", None, 0),
                (layout.engine_state, "remove", None, 0),
            ),
        }
        for operation, steps in cases.items():
            with self.subTest(operation=operation), self.assertRaises(blocked_error):
                self._coordinator().commit(
                    operation,
                    replacements={},
                    removals=(),
                    ordered_steps=steps,
                )
        self.assertFalse(self.paths.journal.exists())

    def test_recovery_rejects_journal_that_violates_recorded_update_order(self):
        _, blocked_error, _, layout_type = _transaction_api()
        layout = layout_type.from_home(self.paths.home)
        for path, content in (
            (layout.registered_manifest64, b"old manifest"),
            (layout.private_library64, b"old library"),
            (layout.engine_state, b"old marker"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        crashing = self._coordinator(
            CheckpointInjector("prepared", SimulatedCrash("power loss"))
        )
        with self.assertRaises(SimulatedCrash):
            crashing.commit(
                "update",
                replacements={},
                removals=(),
                ordered_steps=(
                    (layout.registered_manifest64, "remove", None, 0),
                    (layout.private_library64, "replace", b"new library", 0o644),
                    (layout.registered_manifest64, "replace", b"new manifest", 0o644),
                    (layout.engine_state, "replace", b"new marker", 0o644),
                ),
            )
        before = {
            path: snapshot_entry(path)
            for path in (
                layout.registered_manifest64,
                layout.private_library64,
                layout.engine_state,
            )
        }
        journal = json.loads(self.paths.journal.read_text(encoding="utf-8"))
        journal["entries"][0], journal["entries"][1] = (
            journal["entries"][1], journal["entries"][0]
        )
        for index, entry in enumerate(journal["entries"]):
            target = Path(entry["target"])
            if entry["stage"] is not None:
                entry["stage"] = str(
                    target.with_name(f".{target.name}.{journal['tx_id']}.{index}.stage")
                )
            if entry["backup"] is not None:
                entry["backup"] = str(
                    target.with_name(f".{target.name}.{journal['tx_id']}.{index}.backup")
                )
        unsigned = {key: value for key, value in journal.items() if key != "checksum"}
        canonical = json.dumps(
            unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        journal["checksum"] = hashlib.sha256(canonical).hexdigest()
        self.paths.journal.write_text(
            json.dumps(journal, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )

        with self.assertRaises(blocked_error):
            self._coordinator().recover()

        self.assertEqual(
            {path: snapshot_entry(path) for path in before}, before
        )
        self.assertTrue(self.paths.journal.exists())

    def test_lock_and_hot_journal_use_private_permission_modes(self):
        self.paths.write_triplet()
        crashing = self._coordinator(
            CheckpointInjector("prepared", SimulatedCrash("power loss"))
        )

        with self.assertRaises(SimulatedCrash):
            crashing.commit(
                "configuration",
                replacements={self.paths.toml: (b"new toml\n", 0o644)},
                removals=(),
            )

        self.assertEqual(snapshot_entry(self.paths.lock).mode, 0o600)
        self.assertEqual(snapshot_entry(self.paths.journal).mode, 0o600)

    def test_committed_crash_keeps_new_state_and_only_finishes_cleanup(self):
        self.paths.write_triplet()
        replacements = {
            self.paths.toml: (b"new toml\n", 0o644),
            self.paths.wrapper_json: (b'{"version": 1, "profiles": {}}\n', 0o640),
            self.paths.launcher: (b"#!/bin/sh\nexit 0\n", 0o755),
        }
        crashing = self._coordinator(
            CheckpointInjector(
                "after_committed_journal_replace", SimulatedCrash("power loss")
            )
        )

        with self.assertRaises(SimulatedCrash):
            crashing.commit(
                "configuration", replacements=replacements, removals=()
            )

        recovered = self._coordinator().recover()

        self.assertTrue(recovered.refresh_required)
        for path, (content, mode) in replacements.items():
            self.assertEqual(snapshot_entry(path).content, content)
            self.assertEqual(snapshot_entry(path).mode, mode)
        self.assertFalse(self.paths.journal.exists())

    def test_committed_cleanup_failure_returns_success_with_recovery_warning(self):
        self.paths.write_triplet()
        coordinator = self._coordinator(
            CheckpointInjector("cleanup_backup", InjectedFailure("cleanup failed"))
        )

        result = coordinator.commit(
            "configuration",
            replacements={self.paths.toml: (b"committed\n", 0o644)},
            removals=(),
        )

        self.assertTrue(result.committed)
        self.assertTrue(result.recovery_pending)
        self.assertTrue(result.warning)
        self.assertEqual(self.paths.toml.read_bytes(), b"committed\n")
        self.assertTrue(self.paths.journal.exists())

    def test_committed_journal_parent_fsync_failure_rolls_back(self):
        self.paths.write_triplet()
        self._prime_lock(self._coordinator())
        before = snapshot_tree(self.paths.home)
        coordinator = self._coordinator(
            OccurrenceInjector(
                "journal_parent_fsync",
                5,
                InjectedFailure("committed journal was not durable"),
            )
        )

        with self.assertRaises(InjectedFailure):
            coordinator.commit(
                "configuration",
                replacements={self.paths.toml: (b"not committed\n", 0o644)},
                removals=(),
            )

        self.assertEqual(snapshot_tree(self.paths.home), before)
        self.assertFalse(self.paths.journal.exists())

    def test_stage_swap_before_application_is_blocked_without_following_symlink(self):
        self.paths.write_triplet()
        outside = self.paths.home / "outside"
        outside.write_bytes(b"outside must remain unchanged")
        old_target = snapshot_entry(self.paths.toml)

        def swap_stage(_index):
            stages = list(
                self.paths.toml.parent.glob(f".{self.paths.toml.name}.*.0.stage")
            )
            self.assertEqual(len(stages), 1)
            stages[0].unlink()
            stages[0].symlink_to(outside)

        _, blocked_error, _, _ = _transaction_api()
        coordinator = self._coordinator(
            OccurrenceInjector("live_replace", 1, swap_stage)
        )

        with self.assertRaises(blocked_error):
            coordinator.commit(
                "configuration",
                replacements={self.paths.toml: (b"attacker selected bytes", 0o644)},
                removals=(),
            )

        self.assertEqual(snapshot_entry(self.paths.toml), old_target)
        self.assertEqual(outside.read_bytes(), b"outside must remain unchanged")

    def test_recovery_blocks_unknown_journal_operation_without_touching_files(self):
        self.paths.write_triplet()
        crashing = self._coordinator(
            CheckpointInjector("prepared", SimulatedCrash("power loss"))
        )
        with self.assertRaises(SimulatedCrash):
            crashing.commit(
                "configuration",
                replacements={self.paths.toml: (b"new toml\n", 0o644)},
                removals=(),
            )
        before = snapshot_tree(self.paths.home)
        journal = json.loads(self.paths.journal.read_text(encoding="utf-8"))
        journal["operation"] = "unknown-operation"
        unsigned = {key: value for key, value in journal.items() if key != "checksum"}
        canonical = json.dumps(
            unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        journal["checksum"] = hashlib.sha256(canonical).hexdigest()
        self.paths.journal.write_text(
            json.dumps(journal, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        before[self.paths.journal.relative_to(self.paths.home).as_posix()] = snapshot_entry(
            self.paths.journal
        )
        _, blocked_error, _, _ = _transaction_api()

        with self.assertRaises(blocked_error):
            self._coordinator().recover()

        self.assertEqual(snapshot_tree(self.paths.home), before)


if __name__ == "__main__":
    unittest.main()
