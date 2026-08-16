"""Reusable filesystem fixtures for transactional state tests.

The snapshot intentionally records only the metadata promised by the project:
entry type, regular-file bytes, symlink target, and permission mode.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
from typing import Iterator

from py_modules.lsfg_vk.constants import (
    CLI_FILENAME,
    DIAGNOSTICS_HELPER_FILENAME,
    EXPERIMENTAL_LAYER_BUILD_MARKER,
    JSON32_FILENAME,
    JSON_FILENAME,
    LIB_FILENAME,
)


@dataclass(frozen=True)
class EntrySnapshot:
    kind: str
    mode: int
    content: bytes | None = None
    link_target: str | None = None


def snapshot_entry(path: Path) -> EntrySnapshot:
    """Snapshot a path without following a symlink."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return EntrySnapshot("absent", 0)

    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISREG(metadata.st_mode):
        return EntrySnapshot("regular", mode, content=path.read_bytes())
    if stat.S_ISLNK(metadata.st_mode):
        return EntrySnapshot("symlink", mode, link_target=os.readlink(path))
    if stat.S_ISDIR(metadata.st_mode):
        return EntrySnapshot("directory", mode)
    return EntrySnapshot("other", mode)


def snapshot_tree(root: Path) -> dict[str, EntrySnapshot]:
    """Capture every existing descendant without traversing symlinked dirs."""
    if not root.exists():
        return {}
    result: dict[str, EntrySnapshot] = {}
    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in sorted((*names, *files)):
            path = directory_path / name
            result[path.relative_to(root).as_posix()] = snapshot_entry(path)
    return result


class TemporaryHome:
    """An isolated layout with convenient configuration target aliases."""

    def __init__(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self._temporary_directory.name)
        self.config_dir = self.home / ".config/decky-lsfg-vk-experimental"
        self.toml = self.config_dir / "conf.toml"
        self.wrapper_json = self.config_dir / "profile-wrapper-settings.json"
        self.launcher = self.home / ".local/bin/lsfg-vk-experimental"
        self.journal = self.config_dir / ".state-transaction.json"
        self.lock = self.config_dir / ".state-mutation.lock"

    def cleanup(self) -> None:
        self._temporary_directory.cleanup()

    def managed_paths(self) -> Iterator[Path]:
        yield self.toml
        yield self.wrapper_json
        yield self.launcher

    def write_triplet(
        self,
        toml: bytes = b"old toml\n",
        wrapper_json: bytes = b'{"version": 1, "profiles": {}}\n',
        launcher: bytes = b"#!/bin/sh\nexec \"$@\"\n",
    ) -> None:
        for path, content, mode in (
            (self.toml, toml, 0o640),
            (self.wrapper_json, wrapper_json, 0o600),
            (self.launcher, launcher, 0o750),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(mode)


def layer_manifest(architecture: str) -> bytes:
    """Return a minimal valid upstream Vulkan implicit-layer manifest."""
    return json.dumps({
        "file_format_version": "1.2.1",
        "layer": {
            "name": "VK_LAYER_LSFGVK_frame_generation",
            "library_path": f"upstream-{architecture}",
            "library_arch": architecture,
        },
    }).encode("utf-8")


def write_engine_archive(
    path: Path,
    *,
    include_32bit: bool = True,
    include_cli: bool = True,
    extra_members: tuple[tuple[str, bytes], ...] = (),
) -> str:
    """Write a tiny real tar.xz and return its SHA-256 checksum.

    ``extra_members`` deliberately remains a sequence so archive-admission tests
    can express duplicate member names, which a dict-based helper would hide.
    """
    members = [
        (f"lib/{LIB_FILENAME}", b"ELF64:" + EXPERIMENTAL_LAYER_BUILD_MARKER),
        (f"share/vulkan/implicit_layer.d/{JSON_FILENAME}", layer_manifest("64")),
    ]
    if include_32bit:
        members.extend((
            (f"lib32/{LIB_FILENAME}", b"ELF32:" + EXPERIMENTAL_LAYER_BUILD_MARKER),
            (f"share/vulkan/implicit_layer.d/{JSON32_FILENAME}", layer_manifest("32")),
        ))
    if include_cli:
        members.append((f"bin/{CLI_FILENAME}", b"#!/bin/sh\nexit 0\n"))
    members.extend(extra_members)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:xz") as archive:
        for name, content in members:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if name.endswith(CLI_FILENAME) else 0o644
            archive.addfile(info, io.BytesIO(content))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bundled_engine(root: Path, *, include_32bit: bool = True) -> Path:
    """Create the minimum release-like tree consumed by InstallationService."""
    archive = root / "bin/engine.tar.xz"
    checksum = write_engine_archive(archive, include_32bit=include_32bit)
    (root / "package.json").write_text(json.dumps({
        "remote_binary": [{
            "name": archive.name,
            "version": "test-version",
            "sha256hash": checksum,
            "architectures": ["64", "32"] if include_32bit else ["64"],
        }],
    }), encoding="utf-8")
    helper = root / "scripts" / DIAGNOSTICS_HELPER_FILENAME
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_bytes(b"#!/bin/sh\necho diagnostics\n")
    helper.chmod(0o755)
    return archive
