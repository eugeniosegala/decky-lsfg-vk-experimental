"""Durable, cooperative filesystem transactions for plugin-managed state.

The coordinator serializes cooperating writers with a non-blocking advisory
lock.  Its write-ahead log provides old-or-new recovery for regular files and
absence, preserving file bytes and permission modes.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from typing import Iterator, Mapping, Sequence
import uuid

from .constants import (
    CLI_DIR,
    CLI_FILENAME,
    CONFIG_DIR,
    CONFIG_FILENAME,
    DIAGNOSTICS_SCRIPT_NAME,
    HDR_META_JSON_FILENAME_64,
    JSON32_FILENAME,
    JSON_FILENAME,
    LEGACY_PRIVATE_JSON_FILENAMES,
    LIB_FILENAME,
    LOCAL_LIB,
    LOCAL_LIB32,
    SCRIPT_NAME,
    USER_VULKAN_EXPLICIT_LAYER_DIR,
    USER_VULKAN_LAYER_DIR,
    VULKAN_LAYER_DIR,
    WRAPPER_PROFILE_SETTINGS_FILENAME,
    FLATPAK_OVERRIDE_OWNERSHIP_FILENAME,
)


class MutationBusyError(RuntimeError):
    """Another cooperating mutation currently owns the advisory lock."""


class MutationBlockedError(RuntimeError):
    """Persisted state is unsafe or cannot be recovered without ambiguity."""


class RecoveryPendingError(RuntimeError):
    """A valid journal exists and must be recovered by a mutation/startup entry."""


class NestedTransactionError(MutationBlockedError):
    """A transaction commit was attempted inside another commit."""


class FaultInjector:
    """Production no-op seam used by deterministic durability tests."""

    def hit(self, name: str, index: int | None = None) -> None:
        del name, index


@dataclass(frozen=True)
class PathLayout:
    home: Path
    config_dir: Path
    config_file: Path
    wrapper_settings: Path
    launcher: Path
    diagnostics_helper: Path
    private_library64: Path
    private_library32: Path
    private_manifest64: Path
    private_manifest32: Path
    registered_manifest64: Path
    registered_manifest32: Path
    obsolete_hdr_manifest: Path
    cli: Path
    engine_state: Path
    legacy_private_manifests: tuple[Path, ...]
    lock_file: Path
    journal_file: Path
    flatpak_override_ownership: Path

    @classmethod
    def from_home(cls, home: Path) -> "PathLayout":
        home = Path(os.path.abspath(os.fspath(home)))
        config_dir = home / CONFIG_DIR
        private_manifest_dir = home / VULKAN_LAYER_DIR
        private_root = (home / LOCAL_LIB).parent
        return cls(
            home=home,
            config_dir=config_dir,
            config_file=config_dir / CONFIG_FILENAME,
            wrapper_settings=config_dir / WRAPPER_PROFILE_SETTINGS_FILENAME,
            launcher=home / SCRIPT_NAME,
            diagnostics_helper=home / DIAGNOSTICS_SCRIPT_NAME,
            private_library64=home / LOCAL_LIB / LIB_FILENAME,
            private_library32=home / LOCAL_LIB32 / LIB_FILENAME,
            private_manifest64=private_manifest_dir / JSON_FILENAME,
            private_manifest32=private_manifest_dir / JSON32_FILENAME,
            registered_manifest64=home / USER_VULKAN_LAYER_DIR / JSON_FILENAME,
            registered_manifest32=home / USER_VULKAN_LAYER_DIR / JSON32_FILENAME,
            obsolete_hdr_manifest=(
                home / USER_VULKAN_EXPLICIT_LAYER_DIR / HDR_META_JSON_FILENAME_64
            ),
            cli=home / CLI_DIR / CLI_FILENAME,
            engine_state=private_root / "installed-engine.json",
            legacy_private_manifests=tuple(
                private_manifest_dir / name for name in LEGACY_PRIVATE_JSON_FILENAMES
            ),
            lock_file=config_dir / ".state-mutation.lock",
            journal_file=config_dir / ".state-transaction.json",
            flatpak_override_ownership=(
                config_dir / FLATPAK_OVERRIDE_OWNERSHIP_FILENAME
            ),
        )

    # Compatibility names used by the existing services.
    @property
    def config_file_path(self) -> Path:
        return self.config_file

    @property
    def wrapper_profile_settings_path(self) -> Path:
        return self.wrapper_settings

    @property
    def lsfg_script_path(self) -> Path:
        return self.launcher


@dataclass(frozen=True)
class FileIdentity:
    kind: str
    sha256: str | None
    mode: int

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind, "sha256": self.sha256, "mode": self.mode}

    @classmethod
    def from_json(cls, value: object) -> "FileIdentity":
        if not isinstance(value, dict):
            raise MutationBlockedError("journal contains an invalid file identity")
        kind, digest, mode = value.get("kind"), value.get("sha256"), value.get("mode")
        if kind not in ("absent", "regular") or not isinstance(mode, int):
            raise MutationBlockedError("journal contains an invalid file identity")
        if kind == "absent":
            if digest is not None or mode != 0:
                raise MutationBlockedError("journal contains an invalid absent identity")
        elif (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not 0 <= mode <= 0o7777
        ):
            raise MutationBlockedError("journal contains an invalid regular identity")
        return cls(kind, digest, mode)


@dataclass
class TransactionEntry:
    target: Path
    action: str
    expected_before: FileIdentity
    expected_after: FileIdentity
    stage: Path | None
    backup: Path | None
    payload_class: str = "user"

    def to_json(self) -> dict[str, object]:
        return {
            "target": str(self.target),
            "action": self.action,
            "expected_before": self.expected_before.to_json(),
            "expected_after": self.expected_after.to_json(),
            "stage": str(self.stage) if self.stage else None,
            "backup": str(self.backup) if self.backup else None,
            "payload_class": self.payload_class,
        }


@dataclass(frozen=True)
class TransactionResult:
    committed: bool = False
    recovery_pending: bool = False
    refresh_required: bool = False
    warning: str | None = None


@dataclass
class _LockState:
    rlock: threading.RLock = field(default_factory=threading.RLock)
    owner_thread: int | None = None
    depth: int = 0
    fd: int | None = None
    pid: int = field(default_factory=os.getpid)
    active_transaction: str | None = None
    active_external_operation: str | None = None


_REGISTRY_GUARD = threading.Lock()
_LOCK_REGISTRY: dict[str, _LockState] = {}


def _reset_after_fork() -> None:
    global _REGISTRY_GUARD, _LOCK_REGISTRY
    for state in _LOCK_REGISTRY.values():
        if state.fd is not None:
            try:
                # Deliberately do not LOCK_UN an inherited open-file description.
                os.close(state.fd)
            except OSError:
                pass
    _LOCK_REGISTRY = {}
    _REGISTRY_GUARD = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def _canonical(path: Path) -> str:
    return os.path.abspath(os.fspath(path))


def _with_platform_root_alias(path: Path) -> Path:
    """Resolve only macOS's fixed ``/var`` -> ``/private/var`` root alias."""
    canonical = Path(_canonical(path))
    if len(canonical.parts) > 1 and canonical.parts[1] == "var":
        root_component = Path(canonical.anchor) / "var"
        try:
            if (
                stat.S_ISLNK(root_component.lstat().st_mode)
                and Path(os.path.realpath(root_component)) == Path("/private/var")
            ):
                return Path("/private/var").joinpath(*canonical.parts[2:])
        except OSError:
            pass
    return canonical


@contextmanager
def _directory_fd(path: Path) -> Iterator[int]:
    """Open an absolute directory one no-follow component at a time."""
    canonical = _with_platform_root_alias(path)
    descriptor = os.open(
        canonical.anchor,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    os.set_inheritable(descriptor, False)
    try:
        for component in canonical.parts[1:]:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.set_inheritable(next_descriptor, False)
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as exc:
        os.close(descriptor)
        raise MutationBlockedError(f"directory path is unsafe: {canonical}: {exc}") from exc
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _identity_at(directory_fd: int, name: str, display_path: Path) -> FileIdentity:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return FileIdentity("absent", None, 0)
    except OSError as exc:
        raise MutationBlockedError(
            f"cannot inspect managed target {display_path}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise MutationBlockedError(f"managed target is not a regular file: {display_path}")
    descriptor: int | None = None
    digest = hashlib.sha256()
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        os.set_inheritable(descriptor, False)
        opened_before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or (metadata.st_dev, metadata.st_ino)
            != (opened_before.st_dev, opened_before.st_ino)
        ):
            raise MutationBlockedError(
                f"managed target changed during inspection: {display_path}"
            )
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        opened_after = os.fstat(descriptor)
        before = (
            opened_before.st_dev, opened_before.st_ino, opened_before.st_size,
            opened_before.st_mtime_ns, opened_before.st_mode,
        )
        after = (
            opened_after.st_dev, opened_after.st_ino, opened_after.st_size,
            opened_after.st_mtime_ns, opened_after.st_mode,
        )
        if before != after:
            raise MutationBlockedError(
                f"managed target changed during inspection: {display_path}"
            )
    except OSError as exc:
        raise MutationBlockedError(f"cannot read managed target {display_path}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return FileIdentity("regular", digest.hexdigest(), stat.S_IMODE(opened_after.st_mode))


def _identity(path: Path) -> FileIdentity:
    with _directory_fd(path.parent) as directory_fd:
        return _identity_at(directory_fd, path.name, path)


def regular_file_exists_nofollow(path: Path) -> bool:
    """Inspect a regular file without following any path component symlinks."""
    try:
        with _directory_fd(path.parent) as directory_fd:
            try:
                metadata = os.stat(
                    path.name, dir_fd=directory_fd, follow_symlinks=False
                )
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise MutationBlockedError(
                    f"cannot inspect managed target {path}: {exc}"
                ) from exc
            if not stat.S_ISREG(metadata.st_mode):
                raise MutationBlockedError(
                    f"managed target is not a regular file: {path}"
                )

            descriptor: int | None = None
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                flags |= getattr(os, "O_CLOEXEC", 0)
                descriptor = os.open(path.name, flags, dir_fd=directory_fd)
                os.set_inheritable(descriptor, False)
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (metadata.st_dev, metadata.st_ino)
                    != (opened.st_dev, opened.st_ino)
                ):
                    raise MutationBlockedError(
                        f"managed target changed during inspection: {path}"
                    )
            except OSError as exc:
                raise MutationBlockedError(
                    f"cannot inspect managed target {path}: {exc}"
                ) from exc
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            return True
    except MutationBlockedError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return False
        raise


def read_bytes_nofollow(path: Path) -> bytes:
    """Read one regular file without following the file or directory symlinks."""
    with _directory_fd(path.parent) as directory_fd:
        identity = _identity_at(directory_fd, path.name, path)
        if identity.kind != "regular":
            raise FileNotFoundError(path)
        descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        try:
            os.set_inheritable(descriptor, False)
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            content = b"".join(chunks)
            opened = os.fstat(descriptor)
            observed = FileIdentity(
                "regular",
                hashlib.sha256(content).hexdigest(),
                stat.S_IMODE(opened.st_mode),
            )
            if observed != identity or opened.st_size != len(content):
                raise MutationBlockedError(f"managed target changed during read: {path}")
            return content
        finally:
            os.close(descriptor)


def _inspect_read_journal(layout: PathLayout) -> None:
    """Classify a journal without recovering, cleaning, or bootstrapping state."""
    try:
        metadata = layout.journal_file.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise MutationBlockedError(f"transaction journal is unreadable: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise MutationBlockedError("transaction journal is not a regular file")
    MutationCoordinator(layout)._load_journal()
    raise RecoveryPendingError("transaction recovery is pending")


@contextmanager
def read_only_guard(layout: PathLayout) -> Iterator[None]:
    """Protect a stable read without creating a lock or modifying recovery state."""
    descriptor: int | None = None
    lock_was_absent = False
    try:
        try:
            lock_metadata = layout.lock_file.lstat()
        except FileNotFoundError:
            lock_was_absent = True
        except OSError as exc:
            raise MutationBlockedError(f"mutation lock is unreadable: {exc}") from exc
        else:
            if not stat.S_ISREG(lock_metadata.st_mode):
                raise MutationBlockedError("mutation lock is not a regular file")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_CLOEXEC", 0)
            try:
                descriptor = os.open(layout.lock_file, flags)
                os.set_inheritable(descriptor, False)
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino)
                    != (lock_metadata.st_dev, lock_metadata.st_ino)
                ):
                    raise MutationBusyError("mutation lock changed during read")
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise MutationBusyError("another mutation is in progress") from exc
            except OSError as exc:
                raise MutationBlockedError(f"mutation lock is unreadable: {exc}") from exc

        _inspect_read_journal(layout)
        yield
        _inspect_read_journal(layout)
        if lock_was_absent:
            try:
                layout.lock_file.lstat()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise MutationBusyError("mutation lock changed during read") from exc
            else:
                raise MutationBusyError("mutation lock appeared during read")
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _ensure_directory(path: Path) -> None:
    """Create a directory chain without accepting symlinked/non-directory parts."""
    path = _with_platform_root_alias(path)
    missing: list[Path] = []
    current = path
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise MutationBlockedError(f"no existing parent for {path}")
            current = parent
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise MutationBlockedError(f"directory path is unsafe: {current}")
        break
    for directory in reversed(missing):
        directory.mkdir(mode=0o755)
        _fsync_directory(directory.parent)
        _fsync_directory(directory)


def _fsync_directory(path: Path) -> None:
    with _directory_fd(path) as descriptor:
        os.fsync(descriptor)


class MutationCoordinator:
    """Serialize and durably recover plugin-owned filesystem mutations."""

    _OPERATIONS = frozenset(
        ("configuration", "migration", "install", "update", "uninstall", "flatpak")
    )

    def __init__(self, layout: PathLayout, fault_injector: FaultInjector | None = None):
        self.layout = layout
        self.faults = fault_injector or FaultInjector()

    def _allowed_targets(self, operation: str) -> frozenset[str]:
        configuration = {
            self.layout.config_file,
            self.layout.wrapper_settings,
            self.layout.launcher,
        }
        lifecycle = {
            self.layout.private_library64,
            self.layout.private_library32,
            self.layout.private_manifest64,
            self.layout.private_manifest32,
            self.layout.registered_manifest64,
            self.layout.registered_manifest32,
            self.layout.obsolete_hdr_manifest,
            self.layout.cli,
            self.layout.engine_state,
            self.layout.launcher,
            self.layout.diagnostics_helper,
            *self.layout.legacy_private_manifests,
        }
        if operation == "configuration":
            targets = configuration
        elif operation == "migration":
            targets = configuration | lifecycle
        elif operation in ("install", "update"):
            targets = configuration | lifecycle
        elif operation == "uninstall":
            targets = lifecycle
        elif operation == "flatpak":
            targets = {self.layout.flatpak_override_ownership}
        else:
            raise MutationBlockedError(f"unknown transaction operation: {operation}")
        return frozenset(_canonical(path) for path in targets)

    def _validate_operation_order(
        self, operation: str, steps: Sequence[tuple[Path, str]]
    ) -> None:
        """Enforce lifecycle visibility order independently of the caller."""
        if operation not in ("install", "update", "uninstall"):
            return

        registered = {
            _canonical(self.layout.registered_manifest64),
            _canonical(self.layout.registered_manifest32),
        }
        marker = _canonical(self.layout.engine_state)
        ranks: list[int] = []
        marker_steps = 0
        for path, action in steps:
            key = _canonical(path)
            if key == marker:
                marker_steps += 1
                if action != ("remove" if operation == "uninstall" else "replace"):
                    raise MutationBlockedError(
                        f"{operation} state marker action is invalid"
                    )
                rank = 2 if operation in ("install", "uninstall") else 3
            elif key in registered:
                if operation == "install":
                    if action != "replace":
                        raise MutationBlockedError(
                            "install registered-manifest action is invalid"
                        )
                    rank = 1
                elif operation == "update":
                    rank = 0 if action == "remove" else 2
                else:
                    if action != "remove":
                        raise MutationBlockedError(
                            "uninstall registered-manifest action is invalid"
                        )
                    rank = 0
            else:
                if operation == "uninstall" and action != "remove":
                    raise MutationBlockedError("uninstall action is invalid")
                rank = 0 if operation == "install" else 1
            ranks.append(rank)

        if marker_steps > 1:
            raise MutationBlockedError("state marker transition is duplicated")
        if operation in ("install", "update") and marker_steps != 1:
            raise MutationBlockedError(f"{operation} must replace the state marker last")
        if ranks != sorted(ranks):
            raise MutationBlockedError(f"{operation} transaction order is invalid")

    def _validate_lifecycle_transitions(
        self, operation: str, entries: Sequence[TransactionEntry]
    ) -> None:
        """Validate activation boundaries after identities have been captured."""
        if operation not in ("install", "update"):
            return
        registered = {
            _canonical(self.layout.registered_manifest64),
            _canonical(self.layout.registered_manifest32),
        }
        for entry in entries:
            if _canonical(entry.target) not in registered or entry.action != "replace":
                continue
            if entry.expected_before.kind != "absent":
                raise MutationBlockedError(
                    f"{operation} must deactivate a registered manifest before publishing"
                )

    def _lock_state(self) -> _LockState:
        global _REGISTRY_GUARD, _LOCK_REGISTRY
        if any(state.pid != os.getpid() for state in _LOCK_REGISTRY.values()):
            _reset_after_fork()
        key = _canonical(self.layout.lock_file)
        with _REGISTRY_GUARD:
            state = _LOCK_REGISTRY.get(key)
            if state is None:
                _ensure_directory(self.layout.lock_file.parent)
                state = _LockState()
                _LOCK_REGISTRY[key] = state
            return state

    @contextmanager
    def locked(
        self, operation: str, allowed_targets: Sequence[Path] | None = None
    ) -> Iterator[None]:
        self._allowed_targets(operation)
        if allowed_targets is not None:
            allowed = self._allowed_targets(operation)
            if any(_canonical(path) not in allowed for path in allowed_targets):
                raise MutationBlockedError("caller supplied a target outside the operation policy")
        state = self._lock_state()
        if not state.rlock.acquire(blocking=False):
            raise MutationBusyError("another mutation is in progress")
        thread_id = threading.get_ident()
        nested = state.owner_thread == thread_id and state.depth > 0
        if nested:
            state.depth += 1
            try:
                yield
            finally:
                state.depth -= 1
                state.rlock.release()
            return

        descriptor: int | None = None
        try:
            try:
                lock_metadata = self.layout.lock_file.lstat()
            except FileNotFoundError:
                lock_was_absent = True
            else:
                lock_was_absent = False
                if not stat.S_ISREG(lock_metadata.st_mode):
                    raise MutationBlockedError("mutation lock is not a regular file")
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(self.layout.lock_file, flags, 0o600)
            os.set_inheritable(descriptor, False)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise MutationBlockedError("mutation lock is not a regular file")
            os.fchmod(descriptor, 0o600)
            if lock_was_absent:
                os.fsync(descriptor)
                _fsync_directory(self.layout.lock_file.parent)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise MutationBusyError("another mutation is in progress") from exc
            state.owner_thread = thread_id
            state.depth = 1
            state.fd = descriptor
            yield
        finally:
            if state.owner_thread == thread_id and state.depth:
                state.depth = 0
                state.owner_thread = None
                state.fd = None
                if descriptor is not None:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(descriptor)
            elif descriptor is not None:
                os.close(descriptor)
            state.rlock.release()

    def _hit(self, name: str, index: int | None = None) -> None:
        self.faults.hit(name, index)

    @contextmanager
    def external_operation(
        self, operation: str, allowed_targets: Sequence[Path] | None = None
    ) -> Iterator[None]:
        """Hold the shared lock and reject nested external side effects."""
        with self.locked(operation, allowed_targets):
            state = self._lock_state()
            if state.active_external_operation is not None:
                raise MutationBusyError("another external mutation is in progress")
            state.active_external_operation = operation
            try:
                yield
            finally:
                state.active_external_operation = None

    def _journal_payload(
        self, tx_id: str, operation: str, phase: str, next_index: int,
        entries: Sequence[TransactionEntry],
    ) -> dict[str, object]:
        unsigned: dict[str, object] = {
            "schema": 1,
            "tx_id": tx_id,
            "operation": operation,
            "phase": phase,
            "next_index": next_index,
            "entries": [entry.to_json() for entry in entries],
        }
        canonical = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        return {**unsigned, "checksum": hashlib.sha256(canonical).hexdigest()}

    def _write_journal(self, payload: Mapping[str, object], tx_id: str) -> None:
        journal = self.layout.journal_file
        temporary = journal.with_name(f".{journal.name}.{tx_id}.tmp")
        descriptor: int | None = None
        with _directory_fd(journal.parent) as directory_fd:
            try:
                self._hit("journal_temp_create")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                descriptor = os.open(temporary.name, flags, 0o600, dir_fd=directory_fd)
                os.set_inheritable(descriptor, False)
                content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
                self._hit("journal_temp_write")
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fchmod(descriptor, 0o600)
                self._hit("journal_temp_file_fsync")
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                self._hit("journal_replace")
                os.replace(
                    temporary.name, journal.name,
                    src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                )
                self._hit("journal_parent_fsync")
                os.fsync(directory_fd)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                try:
                    os.unlink(temporary.name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass

    def _write_artifact(self, path: Path, content: bytes, mode: int, index: int, prefix: str) -> None:
        descriptor: int | None = None
        with _directory_fd(path.parent) as directory_fd:
            try:
                self._hit(f"{prefix}_create", index)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                descriptor = os.open(path.name, flags, 0o600, dir_fd=directory_fd)
                os.set_inheritable(descriptor, False)
                self._hit(f"{prefix}_write", index)
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                if prefix == "stage":
                    self._hit("stage_chmod", index)
                os.fchmod(descriptor, mode)
                self._hit(f"{prefix}_file_fsync", index)
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                self._hit(f"{prefix}_parent_fsync", index)
                os.fsync(directory_fd)
            finally:
                if descriptor is not None:
                    os.close(descriptor)

    def _load_journal(self) -> tuple[str, str, str, int, list[TransactionEntry]]:
        try:
            raw = read_bytes_nofollow(self.layout.journal_file)
            value = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MutationBlockedError(f"transaction journal is unreadable: {exc}") from exc
        if not isinstance(value, dict):
            raise MutationBlockedError("transaction journal is not an object")
        checksum = value.get("checksum")
        unsigned = {key: item for key, item in value.items() if key != "checksum"}
        canonical = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        if not isinstance(checksum, str) or hashlib.sha256(canonical).hexdigest() != checksum:
            raise MutationBlockedError("transaction journal checksum is invalid")
        if value.get("schema") != 1:
            raise MutationBlockedError("transaction journal schema is unsupported")
        tx_id, operation, phase, next_index = (
            value.get("tx_id"), value.get("operation"), value.get("phase"), value.get("next_index")
        )
        if not isinstance(tx_id, str) or operation not in self._OPERATIONS:
            raise MutationBlockedError("transaction journal operation is unsupported")
        if phase not in ("preparing", "prepared", "applying", "committed") or not isinstance(next_index, int):
            raise MutationBlockedError("transaction journal phase is invalid")
        raw_entries = value.get("entries")
        if not isinstance(raw_entries, list):
            raise MutationBlockedError("transaction journal entries are invalid")
        allowed = self._allowed_targets(operation)
        entries: list[TransactionEntry] = []
        seen: dict[str, list[TransactionEntry]] = {}
        for index, item in enumerate(raw_entries):
            if not isinstance(item, dict):
                raise MutationBlockedError("transaction journal entry is invalid")
            target_text = item.get("target")
            if not isinstance(target_text, str) or _canonical(Path(target_text)) not in allowed:
                raise MutationBlockedError("transaction journal target is not allowed")
            target = Path(target_text)
            target_key = _canonical(target)
            if target != Path(target_key):
                raise MutationBlockedError("transaction journal target is not canonical")
            action = item.get("action")
            if action not in ("replace", "remove"):
                raise MutationBlockedError("transaction journal action is invalid")
            stage_text, backup_text = item.get("stage"), item.get("backup")
            stage = Path(stage_text) if isinstance(stage_text, str) else None
            backup = Path(backup_text) if isinstance(backup_text, str) else None
            for sibling in (stage, backup):
                if sibling is not None and sibling.parent != target.parent:
                    raise MutationBlockedError("transaction artifact is not a target sibling")
            expected_stage = target.with_name(f".{target.name}.{tx_id}.{index}.stage")
            expected_backup = target.with_name(f".{target.name}.{tx_id}.{index}.backup")
            if stage is not None and stage != expected_stage:
                raise MutationBlockedError("transaction stage name is invalid")
            if backup is not None and backup != expected_backup:
                raise MutationBlockedError("transaction backup name is invalid")
            entry = TransactionEntry(
                target, action,
                FileIdentity.from_json(item.get("expected_before")),
                FileIdentity.from_json(item.get("expected_after")),
                stage, backup,
                str(item.get("payload_class", "user")),
            )
            prior = seen.setdefault(target_key, [])
            if prior:
                valid_update_transition = (
                    operation == "update"
                    and target in (
                        self.layout.registered_manifest64,
                        self.layout.registered_manifest32,
                    )
                    and len(prior) == 1
                    and prior[0].action == "remove"
                    and prior[0].expected_after.kind == "absent"
                    and action == "replace"
                    and entry.expected_before == prior[0].expected_after
                )
                if not valid_update_transition:
                    raise MutationBlockedError(
                        "duplicate transaction target transition is unsupported"
                    )
            prior.append(entry)
            entries.append(entry)
        self._validate_operation_order(
            operation, [(entry.target, entry.action) for entry in entries]
        )
        self._validate_lifecycle_transitions(operation, entries)
        return tx_id, operation, phase, next_index, entries

    def _cleanup(self, entries: Sequence[TransactionEntry], remove_journal: bool = True) -> None:
        for index, entry in enumerate(entries):
            for name, artifact in (("stage", entry.stage), ("backup", entry.backup)):
                if artifact is None:
                    continue
                self._hit(f"cleanup_{name}", index)
                with _directory_fd(artifact.parent) as directory_fd:
                    identity = _identity_at(directory_fd, artifact.name, artifact)
                    if identity.kind == "regular":
                        os.unlink(artifact.name, dir_fd=directory_fd)
                        os.fsync(directory_fd)
        if remove_journal:
            self._hit("cleanup_journal")
            journal = self.layout.journal_file
            with _directory_fd(journal.parent) as directory_fd:
                if _identity_at(directory_fd, journal.name, journal).kind == "regular":
                    os.unlink(journal.name, dir_fd=directory_fd)
                    os.fsync(directory_fd)

    def _rollback(self, entries: Sequence[TransactionEntry]) -> None:
        # Establish that every target chain is unambiguous before modifying live paths.
        chains: dict[str, list[TransactionEntry]] = {}
        for entry in entries:
            chains.setdefault(_canonical(entry.target), []).append(entry)
        for chain in chains.values():
            live = _identity(chain[0].target)
            possible = {chain[0].expected_before, *(entry.expected_after for entry in chain)}
            if live not in possible:
                raise MutationBlockedError(
                    f"cannot identify rollback state for {chain[0].target}"
                )
            first = chain[0]
            if live != first.expected_before and first.expected_before.kind == "regular":
                if first.backup is None or _identity(first.backup) != first.expected_before:
                    raise MutationBlockedError(
                        f"rollback backup is invalid for {first.target}"
                    )
        # Restore each target directly to the chain's original boundary.  This
        # handles update's old -> absent -> new manifest transition even when a
        # failure occurs before the first transition is applied.
        for chain in reversed(tuple(chains.values())):
            first = chain[0]
            live = _identity(first.target)
            if live == first.expected_before:
                continue
            if first.expected_before.kind == "absent":
                with _directory_fd(first.target.parent) as directory_fd:
                    os.unlink(first.target.name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
            else:
                if first.backup is None:
                    raise MutationBlockedError(
                        f"rollback backup is missing for {first.target}"
                    )
                if _identity(first.backup) != first.expected_before:
                    raise MutationBlockedError(
                        f"rollback backup is invalid for {first.target}"
                    )
                with _directory_fd(first.target.parent) as directory_fd:
                    if _identity_at(
                        directory_fd, first.backup.name, first.backup
                    ) != first.expected_before:
                        raise MutationBlockedError(
                            f"rollback backup changed before application: {first.target}"
                        )
                    os.replace(
                        first.backup.name, first.target.name,
                        src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    )
                    os.fsync(directory_fd)
            if _identity(first.target) != first.expected_before:
                raise MutationBlockedError(
                    f"rollback verification failed for {first.target}"
                )
        self._cleanup(entries)

    def recover(self) -> TransactionResult:
        with self.locked("configuration"):
            if _identity(self.layout.journal_file).kind == "absent":
                return TransactionResult()
            _tx_id, _operation, phase, _next_index, entries = self._load_journal()
            if phase == "committed":
                final_entries = {
                    _canonical(entry.target): entry for entry in entries
                }.values()
                for entry in final_entries:
                    if _identity(entry.target) != entry.expected_after:
                        raise MutationBlockedError(f"committed target is ambiguous: {entry.target}")
                self._cleanup(entries)
            else:
                self._rollback(entries)
            return TransactionResult(refresh_required=True)

    def commit(
        self,
        operation: str,
        replacements: Mapping[Path, tuple[bytes, int]],
        removals: Sequence[Path],
        *,
        ordered_steps: Sequence[tuple[Path, str, bytes | None, int]] | None = None,
    ) -> TransactionResult:
        with self.locked(operation):
            state = self._lock_state()
            if state.active_transaction is not None:
                raise NestedTransactionError("nested transaction commits are forbidden")
            tx_id = uuid.uuid4().hex
            state.active_transaction = tx_id
            entries: list[TransactionEntry] = []
            recovering_hot_journal = False
            commit_record_durable = False
            try:
                self._hit("transaction_reserved")
                if _identity(self.layout.journal_file).kind != "absent":
                    recovering_hot_journal = True
                    self.recover()
                    return TransactionResult(refresh_required=True)
                allowed = self._allowed_targets(operation)
                ordered: list[tuple[Path, str, bytes | None, int]] = []
                if ordered_steps is None:
                    replacement_keys = {_canonical(Path(path)) for path in replacements}
                    removal_keys = {_canonical(Path(path)) for path in removals}
                    if replacement_keys & removal_keys:
                        raise MutationBlockedError("a target cannot be replaced and removed together")
                    for path, (content, mode) in replacements.items():
                        ordered.append((Path(path), "replace", content, mode))
                    ordered.extend((Path(path), "remove", None, 0) for path in removals)
                else:
                    if replacements or removals:
                        raise MutationBlockedError(
                            "ordered transaction steps cannot be mixed with mappings"
                        )
                    ordered.extend(
                        (Path(path), action, content, mode)
                        for path, action, content, mode in ordered_steps
                    )
                keys = {_canonical(path) for path, _action, _content, _mode in ordered}
                if any(key not in allowed for key in keys):
                    raise MutationBlockedError("transaction target is outside the operation allowlist")
                seen_steps: dict[str, list[tuple[str, bytes | None, int]]] = {}
                for path, action, content, mode in ordered:
                    if action not in ("replace", "remove"):
                        raise MutationBlockedError("transaction action is invalid")
                    if action == "replace" and (
                        not isinstance(content, bytes)
                        or not isinstance(mode, int)
                        or not 0 <= mode <= 0o7777
                    ):
                        raise MutationBlockedError("replacement payload or mode is invalid")
                    if action == "remove" and (content is not None or mode != 0):
                        raise MutationBlockedError("removal payload is invalid")
                    key = _canonical(path)
                    prior = seen_steps.setdefault(key, [])
                    if prior:
                        valid_update_transition = (
                            operation == "update"
                            and path in (
                                self.layout.registered_manifest64,
                                self.layout.registered_manifest32,
                            )
                            and len(prior) == 1
                            and prior[0][0] == "remove"
                            and action == "replace"
                        )
                        if not valid_update_transition:
                            raise MutationBlockedError(
                                "duplicate transaction target transition is unsupported"
                            )
                    prior.append((action, content, mode))
                self._validate_operation_order(
                    operation,
                    [(path, action) for path, action, _content, _mode in ordered],
                )
                for path, _action, _content, _mode in ordered:
                    _ensure_directory(path.parent)
                predicted: dict[str, FileIdentity] = {}
                for index, (target, action, content, mode) in enumerate(ordered):
                    target_key = _canonical(target)
                    before = predicted.get(target_key, _identity(target))
                    after = (
                        FileIdentity("regular", hashlib.sha256(content or b"").hexdigest(), mode)
                        if action == "replace" else FileIdentity("absent", None, 0)
                    )
                    predicted[target_key] = after
                    stage = target.with_name(f".{target.name}.{tx_id}.{index}.stage") if action == "replace" else None
                    backup = (
                        target.with_name(f".{target.name}.{tx_id}.{index}.backup")
                        if before.kind == "regular" and target_key not in {
                            _canonical(entry.target) for entry in entries
                        }
                        else None
                    )
                    entries.append(TransactionEntry(target, action, before, after, stage, backup))
                self._validate_lifecycle_transitions(operation, entries)
                self._write_journal(self._journal_payload(tx_id, operation, "preparing", 0, entries), tx_id)
                for index, ((_, action, content, mode), entry) in enumerate(zip(ordered, entries)):
                    if action == "replace" and entry.stage is not None:
                        self._write_artifact(entry.stage, content or b"", mode, index, "stage")
                    if entry.expected_before.kind == "regular" and entry.backup is not None:
                        self._write_artifact(
                            entry.backup, read_bytes_nofollow(entry.target), entry.expected_before.mode,
                            index, "backup",
                        )
                        if _identity(entry.backup) != entry.expected_before:
                            raise MutationBlockedError(f"backup verification failed for {entry.target}")
                self._write_journal(self._journal_payload(tx_id, operation, "prepared", 0, entries), tx_id)
                self._hit("prepared")
                for index, entry in enumerate(entries):
                    self._write_journal(self._journal_payload(tx_id, operation, "applying", index, entries), tx_id)
                    self._hit("old_identity_revalidation", index)
                    if _identity(entry.target) != entry.expected_before:
                        raise MutationBlockedError(f"managed target changed during transaction: {entry.target}")
                    self._hit("live_replace", index)
                    with _directory_fd(entry.target.parent) as directory_fd:
                        if _identity_at(
                            directory_fd, entry.target.name, entry.target
                        ) != entry.expected_before:
                            raise MutationBlockedError(
                                f"managed target changed before application: {entry.target}"
                            )
                        if entry.action == "replace":
                            assert entry.stage is not None
                            if _identity_at(
                                directory_fd, entry.stage.name, entry.stage
                            ) != entry.expected_after:
                                raise MutationBlockedError(
                                    f"transaction stage changed before application: {entry.target}"
                                )
                            os.replace(
                                entry.stage.name, entry.target.name,
                                src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                            )
                        elif entry.expected_before.kind == "regular":
                            assert entry.backup is not None
                            if _identity_at(
                                directory_fd, entry.backup.name, entry.backup
                            ) != entry.expected_before:
                                raise MutationBlockedError(
                                    f"transaction backup changed before application: {entry.target}"
                                )
                            # The byte-copy backup already contains the old state.
                            os.unlink(entry.target.name, dir_fd=directory_fd)
                    self._hit("live_parent_fsync", index)
                    _fsync_directory(entry.target.parent)
                    self._hit("new_identity_verification", index)
                    if _identity(entry.target) != entry.expected_after:
                        raise MutationBlockedError(f"new target verification failed: {entry.target}")
                    self._write_journal(self._journal_payload(tx_id, operation, "applying", index + 1, entries), tx_id)
                    self._hit("progress_journal_rewrite", index)
                self._hit("full_new_state_verification")
                final_entries = {
                    _canonical(entry.target): entry for entry in entries
                }.values()
                if any(_identity(entry.target) != entry.expected_after for entry in final_entries):
                    raise MutationBlockedError("complete new state verification failed")
                self._hit("before_committed_journal_replace")
                self._write_journal(self._journal_payload(tx_id, operation, "committed", len(entries), entries), tx_id)
                commit_record_durable = True
                self._hit("after_committed_journal_replace")
                try:
                    self._cleanup(entries)
                except Exception:
                    return TransactionResult(
                        committed=True,
                        recovery_pending=True,
                        warning="The change was committed, but durable cleanup is pending.",
                    )
                return TransactionResult(committed=True)
            except Exception:
                if recovering_hot_journal:
                    raise
                # Commitment is true only after the committed journal replacement
                # and its parent-directory fsync both complete successfully.
                if commit_record_durable:
                    final_entries = {
                        _canonical(entry.target): entry for entry in entries
                    }.values()
                    if any(
                        _identity(entry.target) != entry.expected_after
                        for entry in final_entries
                    ):
                        raise MutationBlockedError(
                            "committed transaction state is ambiguous"
                        )
                    return TransactionResult(
                        committed=True,
                        recovery_pending=True,
                        warning=(
                            "The change was committed, but durable cleanup is pending."
                        ),
                    )
                try:
                    self._rollback(entries)
                except Exception as rollback_error:
                    raise MutationBlockedError(
                        "transaction failed and rollback could not be completed"
                    ) from rollback_error
                raise
            finally:
                state.active_transaction = None


__all__ = [
    "FaultInjector",
    "FileIdentity",
    "MutationBlockedError",
    "MutationBusyError",
    "MutationCoordinator",
    "NestedTransactionError",
    "PathLayout",
    "TransactionEntry",
    "TransactionResult",
    "read_bytes_nofollow",
]
