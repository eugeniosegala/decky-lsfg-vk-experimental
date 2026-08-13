"""Tests for installing the matching 64-bit and 32-bit Vulkan layers."""

import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


sys.modules.setdefault("decky", SimpleNamespace(logger=_Logger()))

from py_modules.lsfg_vk.constants import (  # noqa: E402
    JSON32_FILENAME,
    JSON_FILENAME,
    LIB_FILENAME,
)
from py_modules.lsfg_vk.installation import InstallationService  # noqa: E402


class DualArchInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.service = InstallationService(logger=_Logger())
        self.service.lib_file = self.root / "lib" / LIB_FILENAME
        self.service.lib32_file = self.root / "lib32" / LIB_FILENAME
        manifest_dir = self.root / "share/vulkan/implicit_layer.d"
        self.service.json_file = manifest_dir / JSON_FILENAME
        self.service.json32_file = manifest_dir / JSON32_FILENAME
        self.service.cli_file = self.root / "bin/lsfg-vk-cli"

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _manifest(arch: str) -> bytes:
        return json.dumps({
            "file_format_version": "1.2.1",
            "layer": {
                "name": "VK_LAYER_LSFGVK_frame_generation",
                "library_path": f"original-{arch}",
                "library_arch": arch,
            },
        }).encode("utf-8")

    def _archive(self, include_32bit: bool = True) -> Path:
        archive_path = self.root / "engine.tar.xz"
        members = {
            f"lib/{LIB_FILENAME}": b"ELF64",
            f"share/vulkan/implicit_layer.d/{JSON_FILENAME}": self._manifest("64"),
        }
        if include_32bit:
            members.update({
                f"lib32/{LIB_FILENAME}": b"ELF32",
                f"share/vulkan/implicit_layer.d/{JSON32_FILENAME}": self._manifest("32"),
            })

        with tarfile.open(archive_path, "w:xz") as archive:
            for name, content in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        return archive_path

    def test_installs_and_rewrites_both_layer_architectures(self):
        self.service._extract_and_install_files(self._archive())

        self.assertEqual(self.service.lib_file.read_bytes(), b"ELF64")
        self.assertEqual(self.service.lib32_file.read_bytes(), b"ELF32")
        manifest64 = json.loads(self.service.json_file.read_text(encoding="utf-8"))
        manifest32 = json.loads(self.service.json32_file.read_text(encoding="utf-8"))
        self.assertEqual(manifest64["layer"]["library_arch"], "64")
        self.assertEqual(manifest64["layer"]["library_path"], "../../lib/liblsfg-vk-layer.so")
        self.assertEqual(manifest32["layer"]["library_arch"], "32")
        self.assertEqual(manifest32["layer"]["library_path"], "../../lib32/liblsfg-vk-layer.so")

    def test_rejects_archive_missing_32bit_layer_before_installing_anything(self):
        with self.assertRaisesRegex(OSError, "required lsfg-vk files"):
            self.service._extract_and_install_files(self._archive(include_32bit=False))

        self.assertFalse(self.service.lib_file.exists())
        self.assertFalse(self.service.json_file.exists())


if __name__ == "__main__":
    unittest.main()
