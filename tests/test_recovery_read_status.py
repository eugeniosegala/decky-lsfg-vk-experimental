"""RED contracts for read-only installation status and startup recovery."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
import fcntl
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests.state_transaction_fixtures import TemporaryHome, snapshot_tree


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


decky = sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))
decky.logger = getattr(decky, "logger", _Logger())
decky.DECKY_USER_HOME = getattr(decky, "DECKY_USER_HOME", "/tmp/decky-user")
decky.DECKY_HOME = getattr(decky, "DECKY_HOME", "/tmp/decky")
decky.migrate_logs = getattr(decky, "migrate_logs", Mock())
decky.migrate_settings = getattr(decky, "migrate_settings", Mock())
decky.migrate_runtime = getattr(decky, "migrate_runtime", Mock())

from py_modules.lsfg_vk import state_transaction  # noqa: E402
from py_modules.lsfg_vk.configuration import ConfigurationService  # noqa: E402
from py_modules.lsfg_vk.installation import InstallationService  # noqa: E402
from py_modules.lsfg_vk.plugin import Plugin  # noqa: E402


class _SimulatedCrash(BaseException):
    pass


class _CrashAtPrepared:
    def hit(self, name: str, index: int | None = None) -> None:
        del index
        if name == "prepared":
            raise _SimulatedCrash("leave a valid non-committed journal")


class InstallationStatusRecoveryContracts(unittest.TestCase):
    def setUp(self):
        self.paths = TemporaryHome()
        self.addCleanup(self.paths.cleanup)
        self.layout = state_transaction.PathLayout.from_home(self.paths.home)
        with patch.object(Path, "home", return_value=self.paths.home):
            self.service = InstallationService(logger=_Logger())

    def assert_unavailable_status(self, result, error_code, *, retryable):
        self.assertIs(result.get("status_available"), False, result)
        self.assertIs(
            result.get("installed"), True,
            "legacy clients must fail safe as installed",
        )
        self.assertEqual(result.get("error_code"), error_code)
        self.assertIs(result.get("retryable"), retryable)
        self.assertTrue(result.get("warning"))

    def test_available_installation_status_emits_explicit_availability(self):
        result = self.service.check_installation()

        self.assertIs(result.get("status_available"), True, result)
        self.assertFalse(result["installed"], result)

    def test_busy_installation_status_is_unavailable_and_does_not_write(self):
        self.layout.config_dir.mkdir(parents=True)
        self.layout.lock_file.write_bytes(b"")
        descriptor = self.layout.lock_file.open("rb")
        self.addCleanup(descriptor.close)
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot_tree(self.paths.home)

        result = self.service.check_installation()

        self.assert_unavailable_status(result, "mutation_busy", retryable=True)
        self.assertIs(result.get("recovery_pending"), False)
        self.assertEqual(result.get("recovery_action"), "refresh")
        self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_valid_hot_journal_status_is_pending_and_does_not_recover_or_write(self):
        self.paths.write_triplet()
        coordinator = state_transaction.MutationCoordinator(
            self.layout, _CrashAtPrepared()
        )
        with self.assertRaises(_SimulatedCrash):
            coordinator.commit(
                "configuration",
                replacements={self.layout.config_file: (b"new config\n", 0o640)},
                removals=(),
            )
        before = snapshot_tree(self.paths.home)

        result = self.service.check_installation()

        self.assert_unavailable_status(result, "recovery_pending", retryable=False)
        self.assertIs(result.get("recovery_pending"), True)
        self.assertEqual(result.get("recovery_action"), "wait_for_recovery")
        self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_invalid_journal_status_is_blocked_and_preserves_evidence(self):
        self.layout.config_dir.mkdir(parents=True)
        self.layout.journal_file.write_bytes(b"not a valid transaction journal")
        before = snapshot_tree(self.paths.home)

        result = self.service.check_installation()

        self.assert_unavailable_status(result, "recovery_blocked", retryable=False)
        self.assertIs(result.get("recovery_pending"), True)
        self.assertEqual(result.get("recovery_action"), "repair_required")
        self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_symlink_managed_file_makes_status_blocked(self):
        target = self.paths.home / "outside-library"
        target.write_bytes(b"external")
        self.service.lib_file.parent.mkdir(parents=True, exist_ok=True)
        self.service.lib_file.symlink_to(target)

        result = self.service.check_installation()

        self.assert_unavailable_status(result, "recovery_blocked", retryable=False)

    def test_symlinked_parent_directory_makes_status_blocked(self):
        outside = self.paths.home / "outside-local"
        outside.mkdir()
        (self.paths.home / ".local").symlink_to(outside, target_is_directory=True)
        before = snapshot_tree(self.paths.home)

        result = self.service.check_installation()

        self.assert_unavailable_status(result, "recovery_blocked", retryable=False)
        self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_directory_managed_file_makes_status_blocked(self):
        self.service.registered_json_file.mkdir(parents=True)

        result = self.service.check_installation()

        self.assert_unavailable_status(result, "recovery_blocked", retryable=False)

    def test_ambiguous_inspection_error_makes_status_blocked(self):
        real_inspect = state_transaction.regular_file_exists_nofollow

        def failing_inspect(path):
            if path == self.service.json_file:
                raise state_transaction.MutationBlockedError("inspection denied")
            return real_inspect(path)

        with patch.object(
            state_transaction,
            "regular_file_exists_nofollow",
            side_effect=failing_inspect,
        ):
            result = self.service.check_installation()

        self.assert_unavailable_status(result, "recovery_blocked", retryable=False)


class ConfigurationReadRecoveryContracts(unittest.TestCase):
    def setUp(self):
        self.paths = TemporaryHome()
        self.addCleanup(self.paths.cleanup)
        self.layout = state_transaction.PathLayout.from_home(self.paths.home)
        with patch.object(Path, "home", return_value=self.paths.home):
            self.service = ConfigurationService(logger=_Logger())

    def _read_results(self):
        return (
            ("config", self.service.get_config(), "config"),
            ("profiles", self.service.get_profiles(), "profiles"),
        )

    def assert_unavailable_reads(
        self, error_code: str, *, retryable: bool, pending: bool, action: str
    ):
        for name, result, payload_key in self._read_results():
            with self.subTest(read=name):
                self.assertIs(result.get("success"), False, result)
                self.assertIsNone(result.get(payload_key), result)
                self.assertEqual(result.get("error_code"), error_code)
                self.assertIs(result.get("retryable"), retryable)
                self.assertIs(result.get("recovery_pending"), pending)
                self.assertTrue(result.get("warning"))
                self.assertEqual(result.get("recovery_action"), action)

    def test_busy_config_and_profile_reads_are_unavailable_without_writing(self):
        self.layout.config_dir.mkdir(parents=True)
        self.layout.lock_file.write_bytes(b"")
        descriptor = self.layout.lock_file.open("rb")
        self.addCleanup(descriptor.close)
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot_tree(self.paths.home)

        self.assert_unavailable_reads(
            "mutation_busy", retryable=True, pending=False, action="refresh"
        )

        self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_valid_hot_journal_config_and_profile_reads_do_not_recover_or_write(self):
        self.paths.write_triplet()
        coordinator = state_transaction.MutationCoordinator(
            self.layout, _CrashAtPrepared()
        )
        with self.assertRaises(_SimulatedCrash):
            coordinator.commit(
                "configuration",
                replacements={self.layout.config_file: (b"new config\n", 0o640)},
                removals=(),
            )
        before = snapshot_tree(self.paths.home)

        self.assert_unavailable_reads(
            "recovery_pending",
            retryable=False,
            pending=True,
            action="wait_for_recovery",
        )

        self.assertEqual(snapshot_tree(self.paths.home), before)

    def test_invalid_journal_config_and_profile_reads_preserve_evidence(self):
        self.layout.config_dir.mkdir(parents=True)
        self.layout.journal_file.write_bytes(b"not a valid transaction journal")
        before = snapshot_tree(self.paths.home)

        self.assert_unavailable_reads(
            "recovery_blocked",
            retryable=False,
            pending=True,
            action="repair_required",
        )

        self.assertEqual(snapshot_tree(self.paths.home), before)


class _StartupCoordinator:
    def __init__(self, recovery):
        self.recovery = recovery
        self.recover_calls = 0

    def locked(self, _operation):
        return nullcontext()

    def recover(self):
        self.recover_calls += 1
        if isinstance(self.recovery, BaseException):
            raise self.recovery
        return self.recovery


class StartupRecoveryBarrierContracts(unittest.TestCase):
    def setUp(self):
        self.plugin = Plugin.__new__(Plugin)
        self.plugin.configuration_service = SimpleNamespace(
            migrate_wrapper_profile_settings_if_needed=Mock(return_value=False),
            remove_legacy_vkbasalt_exports=Mock(return_value=False),
            migrate_launch_script_if_needed=Mock(return_value=False),
        )
        self.plugin.installation_service = SimpleNamespace(
            remove_obsolete_hdr_meta_layer_if_needed=Mock(return_value=False),
            migrate_diagnostics_helper_if_needed=Mock(return_value=False),
        )

    def _main_writers(self):
        return (
            self.plugin.configuration_service.migrate_wrapper_profile_settings_if_needed,
            self.plugin.configuration_service.remove_legacy_vkbasalt_exports,
            self.plugin.installation_service.remove_obsolete_hdr_meta_layer_if_needed,
            self.plugin.configuration_service.migrate_launch_script_if_needed,
            self.plugin.installation_service.migrate_diagnostics_helper_if_needed,
        )

    def test_main_busy_recovery_prevents_every_startup_writer(self):
        coordinator = _StartupCoordinator(
            state_transaction.MutationBusyError("another mutation owns the lock")
        )

        with patch.object(state_transaction, "MutationCoordinator", return_value=coordinator):
            asyncio.run(self.plugin._main())

        self.assertEqual(coordinator.recover_calls, 1)
        for writer in self._main_writers():
            writer.assert_not_called()

    def test_main_blocked_recovery_prevents_every_startup_writer(self):
        coordinator = _StartupCoordinator(
            state_transaction.MutationBlockedError("journal is ambiguous")
        )

        with patch.object(state_transaction, "MutationCoordinator", return_value=coordinator):
            asyncio.run(self.plugin._main())

        self.assertEqual(coordinator.recover_calls, 1)
        for writer in self._main_writers():
            writer.assert_not_called()

    def test_migration_busy_or_blocked_recovery_prevents_all_decky_migrations(self):
        for error in (
            state_transaction.MutationBusyError("another mutation owns the lock"),
            state_transaction.MutationBlockedError("journal is ambiguous"),
        ):
            with self.subTest(error=type(error).__name__):
                coordinator = _StartupCoordinator(error)
                decky.migrate_logs.reset_mock()
                decky.migrate_settings.reset_mock()
                decky.migrate_runtime.reset_mock()

                with patch.object(
                    state_transaction, "MutationCoordinator", return_value=coordinator
                ):
                    asyncio.run(self.plugin._migration())

                self.assertEqual(coordinator.recover_calls, 1)
                decky.migrate_logs.assert_not_called()
                decky.migrate_settings.assert_not_called()
                decky.migrate_runtime.assert_not_called()

    def test_successful_startup_recovery_refresh_result_allows_fresh_migrations(self):
        coordinator = _StartupCoordinator(
            state_transaction.TransactionResult(refresh_required=True)
        )

        with patch.object(state_transaction, "MutationCoordinator", return_value=coordinator):
            asyncio.run(self.plugin._main())

        self.assertEqual(coordinator.recover_calls, 1)
        for writer in self._main_writers():
            writer.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
