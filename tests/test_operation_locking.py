"""Deterministic thread, process, and fork tests for the mutation lock."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from tests.state_transaction_fixtures import TemporaryHome, snapshot_tree


def _api():
    from py_modules.lsfg_vk import state_transaction

    return state_transaction


def _process_lock_contender(home: str, connection) -> None:
    """Attempt twice when commanded; top-level for spawn compatibility."""
    api = _api()
    coordinator = api.MutationCoordinator(api.PathLayout.from_home(Path(home)))
    for _ in range(2):
        command = connection.recv()
        if command != "acquire":
            return
        try:
            with coordinator.locked("configuration"):
                connection.send("acquired")
        except api.MutationBusyError:
            connection.send("busy")


class _NestedCommitInjector:
    def __init__(self, coordinator, nested_target: Path, before_tree):
        self.coordinator = coordinator
        self.nested_target = nested_target
        self.before_tree = before_tree
        self.error = None
        self.side_effect_free = False

    def hit(self, name: str, index: int | None = None) -> None:
        if name != "transaction_reserved" or self.error is not None:
            return
        try:
            self.coordinator.commit(
                "configuration",
                replacements={self.nested_target: (b"nested", 0o644)},
                removals=(),
            )
        except BaseException as error:  # assertion below checks the exact domain type
            self.error = error
            self.side_effect_free = (
                snapshot_tree(self.nested_target.parents[2]) == self.before_tree
            )


class OperationLockingTests(unittest.TestCase):
    def setUp(self):
        self.paths = TemporaryHome()
        self.addCleanup(self.paths.cleanup)

    def _coordinator(self, injector=None):
        api = _api()
        return api.MutationCoordinator(api.PathLayout.from_home(self.paths.home), injector)

    def test_same_thread_nested_lock_opens_one_noninheritable_descriptor(self):
        api = _api()
        coordinator = self._coordinator()
        real_open = api.os.open
        opened_lock_fds: list[int] = []

        def recording_open(path, flags, mode=0o777, *, dir_fd=None):
            descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
            if Path(path) == self.paths.lock:
                opened_lock_fds.append(descriptor)
                self.assertFalse(os.get_inheritable(descriptor))
            return descriptor

        with patch.object(api.os, "open", side_effect=recording_open):
            with coordinator.locked("configuration"):
                with coordinator.locked("configuration"):
                    self.assertEqual(len(opened_lock_fds), 1)

        self.assertEqual(len(opened_lock_fds), 1)
        with self.assertRaises(OSError):
            os.fstat(opened_lock_fds[0])

    def test_second_thread_is_fail_fast_busy_without_entering_body(self):
        api = _api()
        coordinator = self._coordinator()
        owner_acquired = threading.Event()
        contender_finished = threading.Event()
        release_owner = threading.Event()
        observations: list[str] = []

        def owner():
            with coordinator.locked("configuration"):
                owner_acquired.set()
                self.assertTrue(release_owner.wait(timeout=5))

        def contender():
            self.assertTrue(owner_acquired.wait(timeout=5))
            try:
                with coordinator.locked("configuration"):
                    observations.append("entered")
            except api.MutationBusyError:
                observations.append("busy")
            finally:
                contender_finished.set()

        owner_thread = threading.Thread(target=owner)
        contender_thread = threading.Thread(target=contender)
        owner_thread.start()
        contender_thread.start()
        self.assertTrue(contender_finished.wait(timeout=5))
        release_owner.set()
        owner_thread.join(timeout=5)
        contender_thread.join(timeout=5)

        self.assertEqual(observations, ["busy"])
        self.assertFalse(owner_thread.is_alive())
        self.assertFalse(contender_thread.is_alive())

    def test_spawned_process_is_busy_then_acquires_after_release(self):
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe()
        process = context.Process(
            target=_process_lock_contender,
            args=(str(self.paths.home), child_connection),
        )
        process.start()
        self.addCleanup(lambda: process.kill() if process.is_alive() else None)
        coordinator = self._coordinator()

        with coordinator.locked("configuration"):
            parent_connection.send("acquire")
            self.assertTrue(parent_connection.poll(5))
            self.assertEqual(parent_connection.recv(), "busy")

        parent_connection.send("acquire")
        self.assertTrue(parent_connection.poll(5))
        self.assertEqual(parent_connection.recv(), "acquired")
        process.join(timeout=5)
        self.assertEqual(process.exitcode, 0)

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "fork unavailable")
    def test_forked_child_does_not_reuse_or_keep_parent_lock(self):
        context = multiprocessing.get_context("fork")
        parent_connection, child_connection = context.Pipe()
        coordinator = self._coordinator()

        with coordinator.locked("configuration"):
            process = context.Process(
                target=_process_lock_contender,
                args=(str(self.paths.home), child_connection),
            )
            process.start()
            self.addCleanup(lambda: process.kill() if process.is_alive() else None)
            parent_connection.send("acquire")
            self.assertTrue(parent_connection.poll(5))
            self.assertEqual(parent_connection.recv(), "busy")

        parent_connection.send("acquire")
        self.assertTrue(parent_connection.poll(5))
        self.assertEqual(parent_connection.recv(), "acquired")
        process.join(timeout=5)
        self.assertEqual(process.exitcode, 0)

    def test_nested_commit_is_rejected_before_any_nested_side_effect(self):
        api = _api()
        self.paths.write_triplet()
        nested_target = self.paths.wrapper_json
        injector = _NestedCommitInjector(None, nested_target, {})
        coordinator = self._coordinator(injector)
        injector.coordinator = coordinator
        with coordinator.locked("configuration"):
            pass
        before = snapshot_tree(self.paths.home)
        injector.before_tree = before

        result = coordinator.commit(
            "configuration",
            replacements={self.paths.toml: (b"outer", 0o644)},
            removals=(),
        )

        self.assertIsInstance(injector.error, api.NestedTransactionError)
        self.assertTrue(injector.side_effect_free)
        self.assertTrue(result.committed)
        self.assertEqual(self.paths.wrapper_json.read_bytes(), before[
            self.paths.wrapper_json.relative_to(self.paths.home).as_posix()
        ].content)


if __name__ == "__main__":
    unittest.main()
