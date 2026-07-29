#!/usr/bin/env bash
# Build a complete, manually installable Decky plugin archive.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path=""
output_path_set=false
publish_release=false

usage() {
  cat <<'EOF'
Usage: scripts/package-release.sh [--publish] [output-path]

Builds a verified Decky plugin ZIP. With --publish, also creates or updates the
matching GitHub pre-release after verifying the current branch is clean and the
release version is committed. --publish requires authenticated git and gh.
EOF
}

while (($#)); do
  case "$1" in
    --publish)
      publish_release=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ "$output_path_set" == true ]]; then
        echo "Only one output path may be specified" >&2
        usage >&2
        exit 2
      fi
      output_path="$1"
      output_path_set=true
      ;;
  esac
  shift
done

for command in curl node npm python3 zip unzip; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

if command -v sha256sum >/dev/null 2>&1; then
  checksum_command=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  checksum_command=(shasum -a 256)
else
  echo "Required command not found: sha256sum or shasum" >&2
  exit 1
fi

read -r archive_name archive_url archive_checksum package_version github_repository < <(
  node -e '
    const manifest = require(process.argv[1]);
    const [binary] = manifest.remote_binary ?? [];
    const repositoryUrl = manifest.repository?.url;
    const githubRepository = repositoryUrl
      ?.replace(/^git\+https:\/\/github\.com\//, "")
      .replace(/\.git$/, "");
    if (!binary?.name || !binary?.url || !binary?.sha256hash || !manifest.version || !githubRepository) {
      process.exitCode = 1;
      throw new Error("package.json must define version, GitHub repository, and one verified remote_binary entry");
    }
    process.stdout.write(`${binary.name}\t${binary.url}\t${binary.sha256hash}\t${manifest.version}\t${githubRepository}\n`);
  ' "$project_dir/package.json"
)

if [[ "$output_path_set" == false ]]; then
  if [[ "$publish_release" == true ]]; then
    output_path="$project_dir/out/Decky.LSFG-VK.Experimental-$package_version.zip"
  else
    output_path="$project_dir/out/Decky.LSFG-VK.Experimental.zip"
  fi
fi

case "$output_path" in
  /*) ;;
  *) output_path="$project_dir/$output_path" ;;
esac

staging_dir="$(mktemp -d "${TMPDIR:-/tmp}/decky-lsfg-vk-package.XXXXXX")"
package_name="Decky LSFG-VK Experimental"
package_dir="$staging_dir/$package_name"

cleanup() {
  rm -rf "$staging_dir"
}
trap cleanup EXIT

echo "Generating configuration bindings..."
python3 "$project_dir/scripts/generate_ts_schema.py"

echo "Building frontend..."
(
  cd "$project_dir"
  npm run build
)

echo "Downloading verified engine payload..."
mkdir -p "$package_dir/bin" "$package_dir/dist" "$package_dir/py_modules"
curl --fail --location --silent --show-error "$archive_url" \
  --output "$package_dir/bin/$archive_name"

actual_checksum="$(${checksum_command[@]} "$package_dir/bin/$archive_name" | awk '{print $1}')"
if [[ "$actual_checksum" != "$archive_checksum" ]]; then
  echo "Checksum mismatch for $archive_name" >&2
  echo "Expected: $archive_checksum" >&2
  echo "Actual:   $actual_checksum" >&2
  exit 1
fi

echo "Assembling Decky archive..."
cp "$project_dir/LICENSE" "$project_dir/README.md" "$project_dir/main.py" \
  "$project_dir/package.json" "$project_dir/plugin.json" "$project_dir/shared_config.py" \
  "$package_dir/"
cp -R "$project_dir/dist/." "$package_dir/dist/"
cp -R "$project_dir/py_modules/." "$package_dir/py_modules/"

# Python bytecode is host-version-specific and is regenerated on the Steam Deck.
find "$package_dir/py_modules" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$package_dir/py_modules" -type d -name '__pycache__' -prune -exec rm -rf {} +

mkdir -p "$(dirname "$output_path")"
rm -f "$output_path"
(
  cd "$staging_dir"
  zip -qr "$output_path" "$package_name"
)

unzip -t "$output_path" >/dev/null
echo "Created and verified: $output_path"

if [[ "$publish_release" == true ]]; then
  for command in git gh; do
    if ! command -v "$command" >/dev/null 2>&1; then
      echo "Publishing requires command: $command" >&2
      exit 1
    fi
  done

  if ! gh auth status >/dev/null 2>&1; then
    echo "Publishing requires an authenticated GitHub CLI session. Run: gh auth login -h github.com" >&2
    exit 1
  fi

  if [[ -n "$(git -C "$project_dir" status --porcelain --untracked-files=normal)" ]]; then
    echo "Refusing to publish from a dirty worktree. Commit the release changes first." >&2
    exit 1
  fi

  release_tag="v$package_version"
  current_commit="$(git -C "$project_dir" rev-parse HEAD)"
  if git -C "$project_dir" rev-parse -q --verify "refs/tags/$release_tag" >/dev/null; then
    tag_commit="$(git -C "$project_dir" rev-list -n 1 "$release_tag")"
    if [[ "$tag_commit" != "$current_commit" ]]; then
      echo "Tag $release_tag does not point at HEAD. Create the release from its intended commit." >&2
      exit 1
    fi
  else
    git -C "$project_dir" tag -a "$release_tag" -m "Decky LSFG-VK Experimental $package_version"
  fi

  current_branch="$(git -C "$project_dir" branch --show-current)"
  if [[ -z "$current_branch" ]]; then
    echo "Publishing requires a checked-out branch, not a detached HEAD." >&2
    exit 1
  fi

  notes_file="$staging_dir/release-notes.md"
  printf '%s\n' \
    '## Installation' \
    '' \
    "1. Download \`$(basename "$output_path")\` below." \
    "2. On the Steam Deck, open Decky Loader's settings and enable **Developer Mode**." \
    '3. Choose **Developer** → **Install Plugin from Zip**, then select the downloaded ZIP.' \
    '4. In the plugin, install lsfg-vk and add `~/.local/bin/lsfg-vk-experimental %command%` to the game’s Steam launch options.' \
    '' \
    '## Important' \
    '' \
    '- This is an experimental build; test it per game.' \
    '- The public and experimental plugins can coexist; select exactly one LSFG-VK wrapper per native Steam/Proton game.' \
    '- The isolated experimental wrapper bypasses other global implicit Vulkan layers (such as vkBasalt) for that game.' \
    '- Confirm the detected `Lossless.dll` path before launching. Leaving it blank permits lsfg-vk automatic discovery.' \
    '' \
    '## Engine payload' \
    '' \
    "- Bundles checksum-verified \`$archive_name\`." \
    > "$notes_file"

  echo "Publishing $release_tag to $github_repository..."
  git -C "$project_dir" push origin "$current_branch"
  git -C "$project_dir" push origin "$release_tag"

  if gh release view "$release_tag" --repo "$github_repository" >/dev/null 2>&1; then
    gh release edit "$release_tag" --repo "$github_repository" \
      --title "Decky LSFG-VK Experimental $package_version" \
      --notes-file "$notes_file" \
      --prerelease
    gh release upload "$release_tag" "$output_path" --repo "$github_repository" --clobber
  else
    gh release create "$release_tag" "$output_path" --repo "$github_repository" \
      --title "Decky LSFG-VK Experimental $package_version" \
      --notes-file "$notes_file" \
      --prerelease \
      --verify-tag
  fi

  echo "Published: https://github.com/$github_repository/releases/tag/$release_tag"
fi
