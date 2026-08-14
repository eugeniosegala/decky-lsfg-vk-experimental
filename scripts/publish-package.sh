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

read -r archive_name engine_version package_version github_repository has_flatpak_bundle archive_url release_tag < <(
  node -e '
    const manifest = require(process.argv[1]);
    const [binary] = manifest.remote_binary ?? [];
    const repositoryUrl = manifest.repository?.url;
    const githubRepository = repositoryUrl
      ?.replace(/^git\+https:\/\/github\.com\//, "")
      .replace(/\.git$/, "");
    const flatpak = binary?.flatpak_bundle;
    if (!binary?.name || !binary?.version || !manifest.version || !githubRepository) {
      process.exitCode = 1;
      throw new Error("package.json must define version, GitHub repository, and one versioned remote_binary entry");
    }
    if (flatpak && (!flatpak.name || !flatpak.url || !flatpak.sha256hash)) {
      process.exitCode = 1;
      throw new Error("flatpak_bundle must define name, url, and sha256hash when present");
    }
    process.stdout.write(`${binary.name}\t${binary.version}\t${manifest.version}\t${githubRepository}\t${flatpak ? "true" : "false"}\t${binary.url ?? ""}\t${binary.release_tag ?? ""}\n`);
  ' "$project_dir/package.json"
)

notes_package_version="0.13.0-experimental.25"
notes_engine_version="2.0.0-dev28-experimental.25"
notes_previous_package_version="0.13.0-experimental.24"
notes_previous_package_tag="v$notes_previous_package_version"
notes_package_tag_pattern="v0.13.0-experimental.*"
if [[ "$package_version" != "$notes_package_version" || "$engine_version" != "$notes_engine_version" ]]; then
  echo "Release notes still describe plugin $notes_package_version with engine $notes_engine_version. Update them before publishing." >&2
  exit 1
fi
if ! git -C "$project_dir" rev-parse -q --verify "refs/tags/$notes_previous_package_tag" >/dev/null; then
  echo "Release-note baseline tag $notes_previous_package_tag is missing." >&2
  exit 1
fi
if ! git -C "$project_dir" merge-base --is-ancestor "$notes_previous_package_tag" HEAD; then
  echo "Release-note baseline $notes_previous_package_tag is not an ancestor of HEAD." >&2
  exit 1
fi
latest_previous_package_tag=""
while IFS= read -r candidate_tag; do
  if [[ "$candidate_tag" != "v$notes_package_version" ]]; then
    latest_previous_package_tag="$candidate_tag"
    break
  fi
done < <(git -C "$project_dir" tag --merged HEAD --list "$notes_package_tag_pattern" --sort=-version:refname)
if [[ "$latest_previous_package_tag" != "$notes_previous_package_tag" ]]; then
  echo "Release notes use $notes_previous_package_tag, but the latest prior tag is ${latest_previous_package_tag:-missing}. Update the baseline and change list before publishing." >&2
  exit 1
fi
if [[ "$archive_url" == local-only://* || "$release_tag" == local-only-* ]]; then
  echo "Refusing to publish a package pinned to a local-only engine payload." >&2
  exit 1
fi

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
  '> **Optional coexistence:** If you want to keep the original/public Decky LSFG-VK plugin installed, you can. Both plugins can remain installed and enabled. For native Steam/Proton games, choose exactly one launch wrapper: public `~/lsfg %command%` or experimental `~/.local/bin/lsfg-vk-experimental %command%`; never combine them. Flatpak apps, including Heroic, are selected through Flatpak setup instead.' \
  '' \
  "## What’s new since \`$notes_previous_package_version\`" \
  '' \
  '- **Engine update:** Bundles checksum-verified `lsfg-vk 2.0.0-dev28-experimental.25`. Complete the required in-plugin engine-update step after installing the ZIP.' \
  '- **HDR foundation — in progress:** The bundled engine contains HDR10/PQ and linear-scRGB colour-pipeline groundwork, Gamescope feedback, packed HDR10 boundary transport, and safe passthrough. HDR activation and frame generation are not exposed by this Decky release while cross-game presentation, colour, and performance validation continues.' \
  '- **64-bit and 32-bit Vulkan support:** Installs architecture-matched host and Flatpak layers. Vulkan selects the correct layer for each game process, so genuine 32-bit Vulkan games no longer need the old WoW64 option; existing wrappers are migrated away from stale `PROTON_USE_WOW64` exports.' \
  '- **Locked SDR safety boundary:** **Disable Experimental HDR (Restart)** is checked and read-only. The backend also overrides older saved opt-ins, exports `LSFGVK_DISABLE_HDR_EXPOSURE=1`, and leaves DXVK at its normal SDR default. Heroic keeps Gamescope WSI in the Vulkan chain so its established presentation and frame-limiting path remains intact.' \
  '- **Safer live reconfiguration and stall recovery:** Transient partial configuration writes are retried. Frame Generation and Adaptive Target, Maximum Multiplier, and Smooth Cadence can update in place when resources permit; resource-shape and model settings are deferred, so restart the game to guarantee those changes. A transient backend stall keeps native presentation active and warms temporal history before generation resumes.' \
  '- **Private layer discovery migration:** The `.25` wrapper regenerates older launchers and retains the uniquely named experimental layer on the proven SDR path. Heroic Flatpak launches explicitly retain Gamescope WSI ahead of the experimental layer; Flatpak cleanup recognises both historical isolated and additive layouts.' \
  '- **Diagnostic log presets:** Installs `~/.local/bin/lsfg-vk-experimental-diagnostics` with focused HDR, Adaptive, recovery, performance, lifecycle, startup, layer, and error filters.' \
  '- **Local engine packaging:** Maintainers can build a Decky ZIP directly from a sibling lsfg-vk checkout. The generated ZIP records the exact commit, dirty state, filenames, and checksums without changing the tracked public release pin.' \
  '- **Documentation:** Expands HDR, dual-architecture, diagnostics, Flatpak migration, local packaging, and community-coverage guidance.' \
  '' \
  '## 🎮 In-game considerations' \
  '' \
  '> [!TIP]' \
  '> **Try the game’s V-Sync setting first.** In many games it can materially improve frame pacing and the perceived smoothness of frame generation. Test it both enabled and disabled before making deeper adjustments.' \
  '' \
  'Every game, renderer, and display setup behaves differently. Also compare Fixed and Adaptive Frame Generation, then fullscreen, borderless, and windowed modes. Change one setting at a time and keep the configuration that feels best for that game.' \
  '' \
  'See the [Configuration guide](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/blob/main/docs/CONFIGURATION.md) and [Troubleshooting guide](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/blob/main/docs/TROUBLESHOOTING.md) for the full behaviour and per-game controls.' \
  '' \
  '> ⚠️ **Required engine-update step:** Installing the ZIP updates the plugin files, but does **not** by itself replace the private LSFG-VK layer. Open this plugin and select **Install Experimental LSFG-VK (developer build)** to install the version bundled in the new ZIP.' \
  '' \
  '> [!IMPORTANT]' \
  '> **Preferred clean update:** To prevent Decky retaining a previous plugin backend or bundled payload, especially when moving between local test ZIPs, uninstall **this experimental plugin** from Decky, install the newer ZIP, restart your Steam Deck or Steam Machine, then select **Install Experimental LSFG-VK (developer build)** in the plugin.' \
  '' \
  > "$notes_file"

if [[ "$has_flatpak_bundle" == "true" ]]; then
  printf '%s\n' \
    '> **First-time Heroic setup:** Read the [Heroic and other Flatpak applications guide](https://github.com/eugeniosegala/decky-lsfg-vk-experimental#heroic-and-other-flatpak-applications) in the README.' \
    '' \
    >> "$notes_file"
fi

printf '%s\n' \
  '## Installation' \
  '' \
  'New to Decky or installing this plugin for the first time? See the [full Install and use guide](https://github.com/eugeniosegala/decky-lsfg-vk-experimental#install-and-use) for Decky Loader setup and prerequisites.' \
  '' \
  "1. Download \`$(basename "$output_path")\` below." \
  "2. On the Steam OS, open Decky Loader's settings and enable **Developer Mode**." \
  '3. Choose **Developer** > **Install Plugin from Zip**, then select the downloaded ZIP.' \
  '4. In the plugin, select **Install Experimental LSFG-VK (developer build)**. For native Steam/Proton games, add `~/.local/bin/lsfg-vk-experimental %command%` to the game’s Steam launch options.' \
  '' \
  '> [!IMPORTANT]' \
  '> If Decky does not show or reload the plugin after installing a ZIP, uninstall **this experimental plugin** from Decky, install the ZIP again, then restart your Steam Deck or Steam Machine. Open the plugin afterwards and select **Install Experimental LSFG-VK (developer build)** again.' \
  '' \
  '## Updating an existing experimental installation' \
  '' \
  '1. Quit any game currently using `~/.local/bin/lsfg-vk-experimental`.' \
  '2. Uninstall **this experimental plugin** from Decky, then download the newer ZIP from [this fork’s releases](https://github.com/eugeniosegala/decky-lsfg-vk-experimental/releases).' \
  '3. In Game Mode, open Decky Loader’s settings, choose **Developer** > **Install Plugin from Zip**, then select the newer ZIP.' \
  '4. Restart your Steam Deck or Steam Machine.' \
  '5. ⚠️ **Required:** Open this plugin and select **Install Experimental LSFG-VK (developer build)** to install the version bundled in the new ZIP.' \
  '6. If you use Heroic, select **Flatpak Setup**, then select **Update** for Heroic’s matching runtime extension (usually **25.08**). This replaces its Flatpak layer with the engine bundled in the new ZIP; Heroic preparation and per-game Wrapper commands remain unchanged.' \
  '' \
  'Experimental profiles and Steam launch options are retained. The private native engine and launcher are re-created in step 5; shared Flatpak extensions are retained, then refreshed in step 6. The public/original plugin may remain installed, but use exactly one plugin wrapper per game.' \
  '' \
  "## Known limitations of lsfg-vk $engine_version" \
  '' \
  '- **HDR is in progress and unavailable in this Decky release:** The engine foundation is included, but the plugin locks HDR exposure off and does not provide a per-game opt-in. In-game HDR controls may be unavailable by design. A later release can unlock the path after activation, presentation, colour, and performance are validated across games.' \
  '- **Adaptive targets are not hard frame limiters:** Adaptive varies generated-frame count toward an average target. It cannot reduce a native framerate already above the target, exceed the configured multiplier/GPU/compositor capacity, or guarantee an unreachable output rate.' \
  '- **Image-quality and latency trade-offs remain game-dependent:** Higher multipliers and lower real-frame rates can increase ghosting and input latency. Smooth Cadence may improve motion consistency while reducing responsiveness.' \
  '' \
  '- **Layer coexistence:** The original and experimental Decky plugins may remain installed, but use exactly one wrapper per game. The experimental wrapper selects its uniquely named private layer and disables both public LSFG identities for that process. Its controlled SDR discovery keeps Gamescope WSI available for Heroic launches.' \
  '' \
  '## Before you play' \
  '' \
  '- This is experimental: test each game before relying on it.' \
  '- Confirm the detected `Lossless.dll` path before launching. Leaving it blank permits upstream discovery.' \
  '' \
  '## Engine payload' \
  '' \
  "- Bundles checksum-verified \`$archive_name\`." \
  >> "$notes_file"

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
