#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script_dir="$project_dir/scripts"
output_path=""
output_path_set=false

usage() {
  cat <<'EOF'
Usage: scripts/publish-package.sh [output-path]

Builds and verifies the Decky plugin ZIP, then creates or verifies the matching
tag, pushes it, uploads the ZIP, and creates or updates the GitHub pre-release.
EOF
}

while (($#)); do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      if (($# > 1)); then
        echo "Only one output path may be specified" >&2
        usage >&2
        exit 2
      fi
      if (($# == 1)); then
        output_path="$1"
        output_path_set=true
        shift
      fi
      break
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

if (($#)); then
  echo "Only one output path may be specified" >&2
  usage >&2
  exit 2
fi

for command in git gh node; do
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

read -r archive_name engine_version package_version github_repository < <(
  node -e '
    const manifest = require(process.argv[1]);
    const [binary] = manifest.remote_binary ?? [];
    const repositoryUrl = manifest.repository?.url;
    const githubRepository = repositoryUrl
      ?.replace(/^git\+https:\/\/github\.com\//, "")
      .replace(/\.git$/, "");
    if (!binary?.name || !binary?.version || !manifest.version || !githubRepository) {
      process.exitCode = 1;
      throw new Error("package.json must define version, GitHub repository, and one versioned remote_binary entry");
    }
    process.stdout.write(`${binary.name}\t${binary.version}\t${manifest.version}\t${githubRepository}\n`);
  ' "$project_dir/package.json"
)

if [[ "$output_path_set" == false ]]; then
  output_path="$project_dir/out/Decky.LSFG-VK.Experimental-$package_version.zip"
elif [[ "$output_path" != /* ]]; then
  output_path="$project_dir/$output_path"
fi

"$script_dir/package-local.sh" "$output_path"

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

notes_dir="$(mktemp -d "${TMPDIR:-/tmp}/decky-lsfg-vk-release-notes.XXXXXX")"
cleanup() {
  rm -rf "$notes_dir"
}
trap cleanup EXIT
notes_file="$notes_dir/release-notes.md"

printf '%s\n' \
  '## Installation' \
  '' \
  "1. Download \`$(basename "$output_path")\` below." \
  "2. On the Steam OS, open Decky Loader's settings and enable **Developer Mode**." \
  '3. Choose **Developer** > **Install Plugin from Zip**, then select the downloaded ZIP.' \
  '4. In the plugin, select **Install Experimental LSFG-VK (developer build)** and add `~/.local/bin/lsfg-vk-experimental %command%` to the game’s Steam launch options.' \
  '' \
  "## Known limitations — lsfg-vk $engine_version" \
  '' \
  '- **Display mode:** Use the game’s native **Fullscreen** mode where possible. Windowed or borderless mode does not normally improve lsfg-vk compatibility or attachment; use it only when a specific game requires it.' \
  '' \
  '- **Steam menu / Game Mode:** With frame generation enabled, opening and closing the Steam menu can occasionally leave a game presenting at its base rate (often 60 fps on a 120 Hz display). It may recover after a few seconds; if it does not, quit and relaunch the game. This is a current lsfg-vk v2/Gamescope presentation limitation, not a failed Decky installation.' \
  '' \
  '- **HDR:** HDR remains problematic with this payload. Disable HDR in the game or SteamOS before launching. The plugin has no general HDR control, so a game-specific HDR workaround must be applied outside the plugin.' \
  '' \
  '- **Changing multiplier:** Changing the FPS multiplier while a game is running can cause persistent performance degradation. Restart the game after changing the multiplier before judging performance.' \
  '' \
  '## v2 improvements' \
  '' \
  '- **Reworked Vulkan layer:** The v2 line includes a rewritten backend with synchronization, resource-reuse, VRAM, pipeline-cache, and multi-device/instance improvements.' \
  '- **More flexible configuration:** Named profiles, automatic executable matching, optional GPU selection, frame-pacing work, and CLI validation/benchmark tools are available.' \
  '- **Quality/performance choice:** In testing, v2 with **Performance Mode disabled** can produce less ghosting than the older build. Performance Mode remains available when lower GPU overhead matters more than image quality.' \
  '- **FP16:** Half-precision processing is available on compatible hardware and can improve performance. Results vary by game and GPU.' \
  '' \
  '## Updating an existing experimental installation' \
  '' \
  '1. Quit games currently launched with `~/.local/bin/lsfg-vk-experimental`.' \
  '2. In Game Mode, choose **Developer** > **Install Plugin from Zip** and select this newer ZIP. Do not uninstall the experimental plugin first.' \
  '3. Reload the plugin from Decky, or restart Game Mode if it does not reload automatically.' \
  '' \
  'Existing experimental profiles, private layer files, and Steam launch options are retained. The public/original plugin may remain installed, but use exactly one plugin wrapper per game.' \
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
