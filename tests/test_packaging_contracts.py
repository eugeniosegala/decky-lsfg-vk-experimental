"""Regression tests for packaging and generated-file release contracts."""

import json
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


PROJECT_DIR = Path(__file__).parents[1]
SCRIPTS_DIR = PROJECT_DIR / "scripts"


class PackagingContractTests(unittest.TestCase):
    def test_direct_deploy_publishes_verified_frontend_last(self):
        source = (SCRIPTS_DIR / "deploy-dev.sh").read_text(encoding="utf-8")

        backend_verification = source.index(
            'verify_tree_files "$project_dir/py_modules" "$plugin_dir/py_modules"'
        )
        engine_verification = source.index(
            'verify_file_copy "$built_layer_64" "$installed_layer_64"'
        )
        metadata_generation = source.index(
            'node "$project_dir/scripts/generate-dev-build-info.mjs"'
        )
        frontend_publication = source.index(
            'copy_file "$project_dir/dist/index.js" "$plugin_dir/dist/index.js"'
        )

        self.assertLess(backend_verification, metadata_generation)
        self.assertLess(engine_verification, metadata_generation)
        self.assertLess(metadata_generation, frontend_publication)
        self.assertIn(
            'mktemp -d "$flatpak_tmp_root/decky-lsfg-vk-flatpaks.XXXXXX"',
            source,
        )
        self.assertIn(
            'find "$plugin_dir/py_modules" \\( -type f -o -type l \\) -print0',
            source,
        )

    def test_dev_build_info_hashes_verified_flatpak_bundle_set(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "build-info.json"
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Packaging Tests"],
                cwd=root,
                check=True,
            )
            (root / "tracked").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)

            bundle_paths = {}
            expected_hash = hashlib.sha256()
            for runtime in ("23.08", "24.08", "25.08"):
                bundle_path = root / f"bundle-{runtime}.flatpak"
                payload = f"bundle:{runtime}\n".encode()
                bundle_path.write_bytes(payload)
                bundle_paths[runtime] = bundle_path
                expected_hash.update(runtime.encode())
                expected_hash.update(b"\0")
                expected_hash.update(payload)
                expected_hash.update(b"\0")

            command = [
                "node",
                str(SCRIPTS_DIR / "generate-dev-build-info.mjs"),
                "--output",
                str(output),
                "--decky-repo",
                str(root),
                "--frontend-deployed",
                "true",
                "--backend-deployed",
                "true",
                "--engine-repo",
                str(root),
            ]
            for runtime, bundle_path in bundle_paths.items():
                command.extend([f"--flatpak-bundle-{runtime}", str(bundle_path)])

            result = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            build_info = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                build_info["engine"]["flatpakBundlesSha256"],
                expected_hash.hexdigest(),
            )

            incomplete = subprocess.run(
                command[:-2], check=False, capture_output=True, text=True
            )
            self.assertEqual(incomplete.returncode, 2)
            self.assertIn(
                "all three Flatpak runtime bundles must be supplied together",
                incomplete.stderr,
            )

    def test_direct_backend_deploy_removes_stale_python_modules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            scripts = root / "scripts"
            source_modules = root / "py_modules" / "pkg"
            plugin = Path(temp_dir) / "plugin"
            installed_modules = plugin / "py_modules" / "pkg"
            scripts.mkdir(parents=True)
            source_modules.mkdir(parents=True)
            installed_modules.mkdir(parents=True)
            shutil.copy2(SCRIPTS_DIR / "deploy-dev.sh", scripts)
            (root / "main.py").write_text("# new main\n", encoding="utf-8")
            (root / "shared_config.py").write_text("# new config\n", encoding="utf-8")
            (source_modules / "current.py").write_text(
                "CURRENT = True\n", encoding="utf-8"
            )
            (installed_modules / "removed.py").write_text(
                "STALE = True\n", encoding="utf-8"
            )
            (plugin / "plugin.json").write_text(
                json.dumps({"name": "Decky LSFG-VK Experimental"}), encoding="utf-8"
            )
            (plugin / "dist").mkdir()

            (scripts / "generate_ts_schema.py").write_text("", encoding="utf-8")
            (scripts / "generate-dev-build-info.mjs").write_text(
                """import { writeFileSync } from "node:fs";
const index = process.argv.indexOf("--output");
writeFileSync(process.argv[index + 1], "{}\\n");
""",
                encoding="utf-8",
            )
            (scripts / "build-frontend.mjs").write_text(
                """import { mkdirSync, writeFileSync } from "node:fs";
mkdirSync(new URL("../dist", import.meta.url), { recursive: true });
writeFileSync(new URL("../dist/index.js", import.meta.url), "built\\n");
""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "bash",
                    str(scripts / "deploy-dev.sh"),
                    "--backend",
                    "--plugin-dir",
                    str(plugin),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((installed_modules / "removed.py").exists())
            self.assertEqual(
                (installed_modules / "current.py").read_text(encoding="utf-8"),
                "CURRENT = True\n",
            )
            self.assertEqual(
                (plugin / "dist" / "index.js").read_text(encoding="utf-8"),
                "built\n",
            )

    def test_watch_and_typecheck_prepare_ignored_dev_build_module(self):
        manifest = json.loads(
            (PROJECT_DIR / "package.json").read_text(encoding="utf-8")
        )
        prepare = "node scripts/prepare-dev-build-info-module.mjs && "

        self.assertTrue(manifest["scripts"]["watch"].startswith(prepare))
        self.assertTrue(manifest["scripts"]["typecheck"].startswith(prepare))

    def _run_manifest_validator(self, mode: str, manifest: dict):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "package.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            return subprocess.run(
                [
                    "node",
                    str(SCRIPTS_DIR / "validate-package-manifest.mjs"),
                    mode,
                    str(manifest_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    @staticmethod
    def _manifest(remote_binary_count: int = 1):
        binary = {
            "name": "engine.tar.xz",
            "version": "2.0.0-dev28-experimental.25",
            "lineage_version": "2.0.0-dev28",
            "source_repository": "https://github.com/example/engine",
            "source_commit": "1" * 40,
            "url": (
                "https://github.com/example/engine/releases/download/"
                "v2.0.0-dev28-experimental.25/engine.tar.xz"
            ),
            "sha256hash": "0" * 64,
            "release_tag": "v2.0.0-dev28-experimental.25",
        }
        return {
            "name": "decky-lsfg-vk-experimental",
            "version": "0.13.0-experimental.25",
            "repository": {
                "url": "git+https://github.com/example/project.git",
            },
            "remote_binary": [dict(binary) for _ in range(remote_binary_count)],
        }

    def test_package_local_requires_exactly_one_remote_binary(self):
        for remote_binary_count in (0, 1, 2):
            with self.subTest(remote_binary_count=remote_binary_count):
                result = self._run_manifest_validator(
                    "package-local",
                    self._manifest(remote_binary_count=remote_binary_count),
                )

                if remote_binary_count == 1:
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(
                        result.stdout,
                        "engine.tar.xz\t2.0.0-dev28-experimental.25\t"
                        "https://github.com/example/engine/releases/download/"
                        "v2.0.0-dev28-experimental.25/engine.tar.xz\t"
                        f"{'0' * 64}\t\t\t\n",
                    )
                else:
                    self.assertNotEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertIn(
                        "package.json must define exactly one remote_binary entry",
                        result.stderr,
                    )

    def test_publish_requires_exactly_one_remote_binary(self):
        for remote_binary_count in (0, 1, 2):
            with self.subTest(remote_binary_count=remote_binary_count):
                result = self._run_manifest_validator(
                    "publish-package",
                    self._manifest(remote_binary_count=remote_binary_count),
                )

                if remote_binary_count == 1:
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(
                        result.stdout,
                        "engine.tar.xz\t2.0.0-dev28-experimental.25\t"
                        "0.13.0-experimental.25\texample/project\tfalse\t"
                        "https://github.com/example/engine/releases/download/"
                        "v2.0.0-dev28-experimental.25/engine.tar.xz\t"
                        "v2.0.0-dev28-experimental.25\n",
                    )
                else:
                    self.assertNotEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertIn(
                        "package.json must define exactly one remote_binary entry",
                        result.stderr,
                    )

    def test_shared_validator_preserves_flatpak_fields_for_both_callers(self):
        manifest = self._manifest()
        manifest["remote_binary"][0]["flatpak_bundle"] = {
            "name": "flatpaks.tar.xz",
            "url": (
                "https://github.com/example/engine/releases/download/"
                "v2.0.0-dev28-experimental.25/flatpaks.tar.xz"
            ),
            "sha256hash": "f" * 64,
        }

        package_local = self._run_manifest_validator("package-local", manifest)
        publish_package = self._run_manifest_validator("publish-package", manifest)

        self.assertEqual(
            package_local.stdout,
            "engine.tar.xz\t2.0.0-dev28-experimental.25\t"
            "https://github.com/example/engine/releases/download/"
            "v2.0.0-dev28-experimental.25/engine.tar.xz\t"
            f"{'0' * 64}\tflatpaks.tar.xz\t"
            "https://github.com/example/engine/releases/download/"
            "v2.0.0-dev28-experimental.25/flatpaks.tar.xz\t"
            f"{'f' * 64}\n",
        )
        self.assertEqual(package_local.stderr, "")
        self.assertEqual(package_local.returncode, 0)
        self.assertEqual(
            publish_package.stdout,
            "engine.tar.xz\t2.0.0-dev28-experimental.25\t"
            "0.13.0-experimental.25\texample/project\ttrue\t"
            "https://github.com/example/engine/releases/download/"
            "v2.0.0-dev28-experimental.25/engine.tar.xz\t"
            "v2.0.0-dev28-experimental.25\n",
        )
        self.assertEqual(publish_package.stderr, "")
        self.assertEqual(publish_package.returncode, 0)

    def test_repository_manifest_passes_every_validation_mode(self):
        for mode in ("check", "package-local", "publish-package"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [
                        "node",
                        str(SCRIPTS_DIR / "validate-package-manifest.mjs"),
                        mode,
                        str(PROJECT_DIR / "package.json"),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if mode == "check":
                    self.assertEqual(result.stdout, "")

    def test_manifest_rejects_unsafe_remote_binary_fields(self):
        mutations = {
            "non_string_name": ("name", ["engine.tar.xz"]),
            "path_traversal_name": ("name", "../../escape.tar.xz"),
            "newline_name": ("name", "engine\nINJECT.tar.xz"),
            "tabbed_version": ("version", "2.0.0\tshifted"),
            "insecure_url": ("url", "http://github.com/example/engine.tar.xz"),
            "file_url": ("url", "file:///etc/passwd"),
            "wrong_url_host": ("url", "https://example.invalid/engine.tar.xz"),
            "mismatched_url_name": (
                "url",
                "https://github.com/example/engine/releases/download/"
                "v2.0.0-dev28-experimental.25/other.tar.xz",
            ),
            "short_checksum": ("sha256hash", "f"),
            "non_hex_checksum": ("sha256hash", "z" * 64),
            "mismatched_release_tag": ("release_tag", "v9.9.9"),
            "invalid_source_repository": (
                "source_repository",
                "ssh://attacker.invalid/repo",
            ),
            "invalid_source_commit": ("source_commit", "not-a-commit"),
        }

        for case, (field, value) in mutations.items():
            for mode in ("check", "package-local", "publish-package"):
                with self.subTest(case=case, mode=mode):
                    manifest = self._manifest()
                    manifest["remote_binary"][0][field] = value
                    result = self._run_manifest_validator(mode, manifest)
                    self.assertNotEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )

    def test_manifest_rejects_invalid_repository_and_flatpak_fields(self):
        invalid_repositories = (
            "ssh://attacker.invalid/repo",
            "https://github.com/example/project",
            "git+https://github.com/example/project.git\nINJECT",
        )
        for repository_url in invalid_repositories:
            for mode in ("check", "publish-package"):
                with self.subTest(repository_url=repository_url, mode=mode):
                    manifest = self._manifest()
                    manifest["repository"]["url"] = repository_url
                    result = self._run_manifest_validator(mode, manifest)
                    self.assertNotEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )

        invalid_flatpaks = (
            {
                "name": "../flatpaks.tar.xz",
                "url": "https://github.com/x/y",
                "sha256hash": "f" * 64,
            },
            {
                "name": "flatpaks.tar.xz",
                "url": "file:///tmp/flatpaks.tar.xz",
                "sha256hash": "f" * 64,
            },
            {
                "name": "flatpaks.tar.xz",
                "url": (
                    "https://github.com/example/engine/releases/download/"
                    "v2.0.0-dev28-experimental.25/flatpaks.tar.xz"
                ),
                "sha256hash": "bad",
            },
        )
        for flatpak_bundle in invalid_flatpaks:
            for mode in ("check", "package-local", "publish-package"):
                with self.subTest(flatpak_bundle=flatpak_bundle, mode=mode):
                    manifest = self._manifest()
                    manifest["remote_binary"][0]["flatpak_bundle"] = flatpak_bundle
                    result = self._run_manifest_validator(mode, manifest)
                    self.assertNotEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )

    def test_package_local_shell_uses_shared_validator_mode_and_field_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            scripts = root / "scripts"
            engine = Path(temp_dir) / "engine"
            engine_scripts = engine / "scripts"
            scripts.mkdir(parents=True)
            engine_scripts.mkdir(parents=True)
            shutil.copy2(SCRIPTS_DIR / "package-local.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "package-output-path.sh", scripts)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (engine / "VERSION").write_text("actual-version\n", encoding="utf-8")
            (engine_scripts / "package-local.sh").write_text("", encoding="utf-8")
            (engine_scripts / "package-flatpaks.sh").write_text("", encoding="utf-8")
            validator_log = root / "validator.log"
            (scripts / "validate-package-manifest.mjs").write_text(
                """import { appendFileSync } from "node:fs";
appendFileSync(process.env.VALIDATOR_LOG, process.argv.slice(2).join("\\t"));
process.stdout.write(
  "engine.tar.xz\\texpected-version\\thttps://example.invalid/engine.tar.xz\\t" +
  "0000000000000000000000000000000000000000000000000000000000000000" +
  "\\t\\t\\t\\n",
);
""",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["VALIDATOR_LOG"] = str(validator_log)
            result = subprocess.run(
                [
                    "bash",
                    str(scripts / "package-local.sh"),
                    "--local-engine-repo",
                    str(engine),
                ],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Decky:  expected-version", result.stderr)
            self.assertIn("Engine: actual-version", result.stderr)
            self.assertEqual(
                validator_log.read_text(encoding="utf-8"),
                f"package-local\t{root.resolve() / 'package.json'}",
            )

    def test_publish_rechecks_clean_worktree_after_local_packaging(self):
        result, commands, artifact_exists, package_invoked, _ = (
            self._run_publish_fixture("dirty-other")
        )

        self.assertTrue(artifact_exists)
        self.assertTrue(package_invoked)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stderr,
            "Refusing to tag after packaging changed the worktree. "
            "Commit the generated changes first.\n",
        )
        status_checks = [
            command
            for command in commands.splitlines()
            if "status --porcelain --untracked-files=normal" in command
        ]
        self.assertEqual(len(status_checks), 2, commands)
        self.assertNotIn("tag -a", commands)
        self.assertNotIn("push origin", commands)

    def test_publish_allows_custom_in_repo_output_without_other_dirty_files(self):
        result, commands, artifact_exists, package_invoked, _ = (
            self._run_publish_fixture("output-only")
        )

        self.assertTrue(artifact_exists)
        self.assertTrue(package_invoked)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        status_checks = [
            command
            for command in commands.splitlines()
            if "status --porcelain --untracked-files=normal" in command
        ]
        self.assertEqual(len(status_checks), 2, commands)
        self.assertIn("tag -a v0.13.0-experimental.25", commands)
        self.assertIn("push origin main", commands)
        self.assertIn("push origin v0.13.0-experimental.25", commands)

    def test_publish_allows_custom_external_output(self):
        result, commands, artifact_exists, package_invoked, _ = (
            self._run_publish_fixture("clean", output_location="external")
        )

        self.assertTrue(artifact_exists)
        self.assertTrue(package_invoked)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("tag -a v0.13.0-experimental.25", commands)
        self.assertIn("push origin main", commands)
        self.assertIn("push origin v0.13.0-experimental.25", commands)

    def test_publish_rejects_tracked_output_before_packaging_can_overwrite_it(self):
        result, commands, artifact_exists, package_invoked, artifact_content = (
            self._run_publish_fixture(
                "clean", output_location="in-repo", tracked_output=True
            )
        )

        self.assertTrue(artifact_exists)
        self.assertFalse(package_invoked)
        self.assertEqual(artifact_content, b"original tracked artifact\n")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Refusing to publish to tracked output path:", result.stderr)
        self.assertNotIn("tag -a", commands)
        self.assertNotIn("push origin", commands)

    def test_publish_rejects_tracked_output_through_symlinked_parent(self):
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            scripts = root / "scripts"
            fake_bin = root / "fake-bin"
            scripts.mkdir(parents=True)
            fake_bin.mkdir()
            shutil.copy2(SCRIPTS_DIR / "publish-package.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "package-output-path.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "validate-package-manifest.mjs", scripts)
            manifest_path = root / "package.json"
            manifest_path.write_text(json.dumps(self._manifest()), encoding="utf-8")
            original_manifest = manifest_path.read_bytes()
            (root / "alias").symlink_to(".", target_is_directory=True)
            package_invoked = root / "package-invoked"
            self._write_executable(
                scripts / "package-local.sh",
                "#!/bin/sh\ntouch \"$FAKE_PACKAGE_INVOKED\"\nprintf 'overwritten\\n' > \"$1\"\n",
            )
            self._write_executable(fake_bin / "gh", "#!/bin/sh\nexit 0\n")

            subprocess.run(
                [real_git, "init", "-q", "-b", "main"], cwd=root, check=True
            )
            subprocess.run(
                [real_git, "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [real_git, "config", "user.name", "Packaging Tests"],
                cwd=root,
                check=True,
            )
            subprocess.run([real_git, "add", "."], cwd=root, check=True)
            subprocess.run(
                [real_git, "commit", "-qm", "fixture"], cwd=root, check=True
            )
            subprocess.run(
                [real_git, "tag", "v0.13.0-experimental.24"], cwd=root, check=True
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                    "FAKE_PACKAGE_INVOKED": str(package_invoked),
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    str(scripts / "publish-package.sh"),
                    str(root / "alias" / "package.json"),
                ],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Refusing to publish to tracked output path", result.stderr)
            self.assertFalse(package_invoked.exists())
            self.assertEqual(manifest_path.read_bytes(), original_manifest)

    def test_package_local_rejects_tracked_output_through_symlinked_parent(self):
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(SCRIPTS_DIR / "package-local.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "package-output-path.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "validate-package-manifest.mjs", scripts)
            manifest_path = root / "package.json"
            manifest_path.write_text(json.dumps(self._manifest()), encoding="utf-8")
            original_manifest = manifest_path.read_bytes()
            (root / "alias").symlink_to(".", target_is_directory=True)

            subprocess.run(
                [real_git, "init", "-q", "-b", "main"], cwd=root, check=True
            )
            subprocess.run(
                [real_git, "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [real_git, "config", "user.name", "Packaging Tests"],
                cwd=root,
                check=True,
            )
            subprocess.run([real_git, "add", "."], cwd=root, check=True)
            subprocess.run(
                [real_git, "commit", "-qm", "fixture"], cwd=root, check=True
            )

            unsafe_outputs = (
                root / "alias" / "package.json",
                root / "missing-parent" / ".." / "package.json",
                root / "PACKAGE.JSON",
            )
            for output_path in unsafe_outputs:
                with self.subTest(output_path=output_path):
                    result = subprocess.run(
                        ["bash", str(scripts / "package-local.sh"), str(output_path)],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    self.assertNotEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertIn(
                        "Refusing to package to tracked output path", result.stderr
                    )
                    self.assertEqual(manifest_path.read_bytes(), original_manifest)

            alternate_root = Path(str(root).replace("/var/", "/VAR/", 1))
            if alternate_root != root and alternate_root.exists():
                self.assertTrue(os.path.samefile(root, alternate_root))
                result = subprocess.run(
                    [
                        "bash",
                        str(alternate_root / "scripts" / "package-local.sh"),
                        str(manifest_path),
                    ],
                    cwd=alternate_root,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(
                    "Refusing to package to tracked output path", result.stderr
                )
                self.assertEqual(manifest_path.read_bytes(), original_manifest)

            git_config = root / ".git" / "config"
            original_git_config = git_config.read_bytes()
            metadata_output = root / "missing-parent" / ".." / ".git" / "config"
            result = subprocess.run(
                ["bash", str(scripts / "package-local.sh"), str(metadata_output)],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("inside repository metadata", result.stderr)
            self.assertEqual(git_config.read_bytes(), original_git_config)

    def _run_publish_fixture(
        self,
        status_after_package: str,
        *,
        output_location: str = "in-repo",
        tracked_output: bool = False,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox = Path(temp_dir)
            root = sandbox / "repo"
            scripts = root / "scripts"
            fake_bin = root / "fake-bin"
            scripts.mkdir(parents=True)
            fake_bin.mkdir()
            shutil.copy2(SCRIPTS_DIR / "publish-package.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "package-output-path.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "validate-package-manifest.mjs", scripts)
            (root / "package.json").write_text(
                json.dumps(self._manifest()), encoding="utf-8"
            )

            if output_location == "in-repo":
                output_path = root / "custom-release.zip"
            elif output_location == "external":
                output_path = sandbox / "artifacts" / "custom-release.zip"
                output_path.parent.mkdir()
            else:
                self.fail(f"Unsupported output location: {output_location}")
            if tracked_output:
                output_path.write_bytes(b"original tracked artifact\n")

            package_complete_marker = root / "package-complete"
            git_log = root / "git.log"
            self._write_executable(
                scripts / "package-local.sh",
                """#!/bin/sh
printf 'packaged artifact\n' > "$1"
touch "$FAKE_PACKAGE_COMPLETE_MARKER"
""",
            )
            self._write_executable(
                fake_bin / "gh",
                """#!/bin/sh
exit 0
""",
            )
            self._write_executable(
                fake_bin / "git",
                """#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_GIT_LOG"
if [ "$1" = "-C" ]; then
  shift 2
fi
case "$1" in
  status)
    if [ -f "$FAKE_PACKAGE_COMPLETE_MARKER" ]; then
      case "$FAKE_STATUS_AFTER_PACKAGE" in
        dirty-other) echo ' M package.json' ;;
        output-only)
          case "$*" in
            *exclude*custom-release.zip*) ;;
            *) echo '?? custom-release.zip' ;;
          esac
          ;;
      esac
    fi
    ;;
  ls-files)
    if [ "$FAKE_TRACKED_OUTPUT" = "true" ]; then
      printf '%s\0' "$FAKE_TRACKED_OUTPUT_PATH"
      exit 0
    fi
    exit 1
    ;;
  rev-parse)
    case "$*" in
      *refs/tags/v0.13.0-experimental.24*) exit 0 ;;
      *refs/tags/v0.13.0-experimental.25*) exit 1 ;;
      *HEAD*) echo '0123456789abcdef0123456789abcdef01234567' ;;
    esac
    ;;
  merge-base) exit 0 ;;
  tag)
    if [ "$2" = "--merged" ]; then
      echo 'v0.13.0-experimental.24'
    fi
    ;;
  branch) echo 'main' ;;
esac
exit 0
""",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                    "FAKE_PACKAGE_COMPLETE_MARKER": str(package_complete_marker),
                    "FAKE_STATUS_AFTER_PACKAGE": status_after_package,
                    "FAKE_TRACKED_OUTPUT": "true" if tracked_output else "false",
                    "FAKE_TRACKED_OUTPUT_PATH": str(output_path),
                    "FAKE_GIT_LOG": str(git_log),
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    str(scripts / "publish-package.sh"),
                    str(output_path),
                ],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            commands = git_log.read_text(encoding="utf-8")
            artifact_exists = output_path.is_file()
            artifact_content = output_path.read_bytes() if artifact_exists else None
            return (
                result,
                commands,
                artifact_exists,
                package_complete_marker.is_file(),
                artifact_content,
            )

    def test_generated_i18n_drift_fails_canonical_generated_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            fake_bin = root / "fake-bin"
            (root / "defaults" / "i18n").mkdir(parents=True)
            (root / "src" / "i18n").mkdir(parents=True)
            scripts.mkdir()
            fake_bin.mkdir()
            shutil.copy2(SCRIPTS_DIR / "check-generated.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "build_i18n_json.sh", scripts)
            (scripts / "generate_ts_schema.py").write_text("", encoding="utf-8")
            (root / "defaults" / "i18n" / "template.json").write_text(
                "{}", encoding="utf-8"
            )
            (root / "src" / "i18n" / "languages.json").write_text(
                "{}", encoding="utf-8"
            )

            git_log = root / "git.log"
            self._write_executable(fake_bin / "python3", "#!/bin/sh\nexit 0\n")
            self._write_executable(fake_bin / "jq", "#!/bin/sh\necho '{\"template\":{}}'\n")
            self._write_executable(
                fake_bin / "git",
                """#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_GIT_LOG"
case "$*" in
  *ls-files*) exit 0 ;;
  *diff*src/i18n/languages.json*) exit 1 ;;
esac
exit 0
""",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                    "FAKE_GIT_LOG": str(git_log),
                }
            )
            result = subprocess.run(
                ["bash", str(scripts / "check-generated.sh")],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            checked_paths = git_log.read_text(encoding="utf-8")
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("diff --exit-code", checked_paths)
            self.assertIn("src/i18n/languages.json", checked_paths)

    def test_i18n_generation_failure_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            defaults = root / "defaults" / "i18n"
            output_dir = root / "src" / "i18n"
            fake_bin = root / "fake-bin"
            scripts.mkdir()
            defaults.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            fake_bin.mkdir()
            shutil.copy2(SCRIPTS_DIR / "build_i18n_json.sh", scripts)
            (defaults / "template.json").write_text("{}\n", encoding="utf-8")
            output = output_dir / "languages.json"
            output.write_bytes(b"original generated translations\n")
            self._write_executable(fake_bin / "node", "#!/bin/sh\nexit 7\n")

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(scripts / "build_i18n_json.sh")],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            self.assertEqual(output.read_bytes(), b"original generated translations\n")
            self.assertEqual(list(output_dir.glob(".languages.json.*")), [])

    def test_i18n_generation_publishes_readable_file_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            defaults = root / "defaults" / "i18n"
            output_dir = root / "src" / "i18n"
            scripts.mkdir()
            defaults.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            shutil.copy2(SCRIPTS_DIR / "build_i18n_json.sh", scripts)
            (defaults / "template.json").write_text(
                '{"status":"ok"}\n', encoding="utf-8"
            )

            result = subprocess.run(
                ["bash", str(scripts / "build_i18n_json.sh")],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            output = output_dir / "languages.json"
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"template": {"status": "ok"}},
            )
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o644)

    def test_staged_deletion_of_generated_output_fails_tracked_file_check(self):
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            fake_bin = root / "fake-bin"
            (root / "defaults" / "i18n").mkdir(parents=True)
            (root / "src" / "config").mkdir(parents=True)
            (root / "src" / "i18n").mkdir(parents=True)
            (root / "py_modules" / "lsfg_vk").mkdir(parents=True)
            scripts.mkdir()
            fake_bin.mkdir()
            shutil.copy2(SCRIPTS_DIR / "check-generated.sh", scripts)
            shutil.copy2(SCRIPTS_DIR / "build_i18n_json.sh", scripts)
            (scripts / "generate_ts_schema.py").write_text("", encoding="utf-8")
            (root / "defaults" / "i18n" / "template.json").write_text(
                "{}", encoding="utf-8"
            )
            (root / "src" / "config" / "generatedConfigSchema.ts").write_text(
                "generated schema\n", encoding="utf-8"
            )
            (
                root / "py_modules" / "lsfg_vk" / "config_schema_generated.py"
            ).write_text("# generated schema\n", encoding="utf-8")
            generated_i18n = root / "src" / "i18n" / "languages.json"
            generated_i18n.write_text('{"template":{}}\n', encoding="utf-8")

            subprocess.run([real_git, "init", "-q"], cwd=root, check=True)
            subprocess.run(
                [real_git, "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [real_git, "config", "user.name", "Packaging Tests"],
                cwd=root,
                check=True,
            )
            subprocess.run([real_git, "add", "."], cwd=root, check=True)
            subprocess.run(
                [real_git, "commit", "-qm", "initial generated outputs"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [real_git, "rm", "--cached", "src/i18n/languages.json"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            tracked_check = subprocess.run(
                [
                    real_git,
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    "src/i18n/languages.json",
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(tracked_check.returncode, 0)
            self.assertTrue(generated_i18n.is_file())

            git_log = root / "git.log"
            self._write_executable(fake_bin / "python3", "#!/bin/sh\nexit 0\n")
            self._write_executable(fake_bin / "jq", "#!/bin/sh\necho '{\"template\":{}}'\n")
            self._write_executable(
                fake_bin / "git",
                """#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_GIT_LOG"
exec "$REAL_GIT" "$@"
""",
            )
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                    "FAKE_GIT_LOG": str(git_log),
                    "REAL_GIT": real_git,
                }
            )
            result = subprocess.run(
                ["bash", str(scripts / "check-generated.sh")],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            commands = git_log.read_text(encoding="utf-8")
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ls-files --error-unmatch", commands)
            self.assertIn("src/i18n/languages.json", commands)

    @staticmethod
    def _write_executable(path: Path, content: str):
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
