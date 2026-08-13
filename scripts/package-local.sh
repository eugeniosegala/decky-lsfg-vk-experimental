#!/usr/bin/env bash
# Build a complete, manually installable Decky plugin archive.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path=""
output_path_set=false
engine_archive_path=""
flatpak_archive_path=""
local_engine_repo=""
local_engine_mode=false
local_engine_commit=""
local_engine_dirty=false
local_engine_label=""

usage() {
  cat <<'EOF'
Usage: scripts/package-local.sh [options] [output-path]

Builds a verified Decky plugin ZIP for local installation. It never creates a
tag, pushes commits, or changes GitHub.

Options:
  --engine-archive PATH   Use a local engine archive instead of downloading it.
  --flatpak-archive PATH  Use a local Flatpak archive instead of downloading it.
  --local-engine-repo PATH
                          Build and bundle the engine checkout at PATH. Its
                          commit and generated checksums are recorded only in
                          the ZIP; tracked package.json is not changed.
  -h, --help              Show this help.
EOF
}

while (($#)); do
  case "$1" in
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
    --publish)
      echo "Use scripts/publish-package.sh to publish a GitHub pre-release." >&2
      exit 2
      ;;
    --engine-archive)
      if (($# < 2)); then
        echo "--engine-archive requires a path" >&2
        exit 2
      fi
      engine_archive_path="$2"
      shift 2
      continue
      ;;
    --flatpak-archive)
      if (($# < 2)); then
        echo "--flatpak-archive requires a path" >&2
        exit 2
      fi
      flatpak_archive_path="$2"
      shift 2
      continue
      ;;
    --local-engine-repo)
      if (($# < 2)); then
        echo "--local-engine-repo requires a path" >&2
        exit 2
      fi
      local_engine_repo="$2"
      shift 2
      continue
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

if [[ -n "$local_engine_repo" &&
      ( -n "$engine_archive_path" || -n "$flatpak_archive_path" ) ]]; then
  echo "--local-engine-repo cannot be combined with archive override options" >&2
  exit 2
fi

for command in curl node npm python3 tar zip unzip; do
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

read -r archive_name archive_version archive_url archive_checksum flatpak_archive_name flatpak_archive_url flatpak_archive_checksum < <(
  node -e '
    const manifest = require(process.argv[1]);
    const [binary] = manifest.remote_binary ?? [];
    if (!binary?.name || !binary?.version || !binary?.url || !binary?.sha256hash) {
      process.exitCode = 1;
      throw new Error("package.json must define one versioned, verified remote_binary entry");
    }
    const flatpak = binary.flatpak_bundle;
    if (flatpak && (!flatpak.name || !flatpak.url || !flatpak.sha256hash)) {
      process.exitCode = 1;
      throw new Error("flatpak_bundle must define name, url, and sha256hash when present");
    }
    process.stdout.write([
      binary.name,
      binary.version,
      binary.url,
      binary.sha256hash,
      flatpak?.name ?? "",
      flatpak?.url ?? "",
      flatpak?.sha256hash ?? "",
    ].join("\t") + "\n");
  ' "$project_dir/package.json"
)

if [[ -n "$local_engine_repo" ]]; then
  local_engine_mode=true
  if ! command -v git >/dev/null 2>&1; then
    echo "Local engine packaging requires command: git" >&2
    exit 1
  fi
  if [[ ! -d "$local_engine_repo" ]]; then
    echo "Local engine repository not found: $local_engine_repo" >&2
    exit 1
  fi
  local_engine_repo="$(cd "$local_engine_repo" && pwd)"
  for required_path in VERSION scripts/package-local.sh scripts/package-flatpaks.sh; do
    if [[ ! -f "$local_engine_repo/$required_path" ]]; then
      echo "Local engine repository is missing $required_path: $local_engine_repo" >&2
      exit 1
    fi
  done

  local_engine_version="$(tr -d '[:space:]' < "$local_engine_repo/VERSION")"
  if [[ "$local_engine_version" != "$archive_version" ]]; then
    echo "Local engine VERSION does not match Decky's configured engine line" >&2
    echo "Decky:  $archive_version" >&2
    echo "Engine: $local_engine_version" >&2
    exit 1
  fi
  local_engine_commit="$(git -C "$local_engine_repo" rev-parse HEAD)"
  local_engine_short_commit="${local_engine_commit:0:7}"
  local_engine_label="$local_engine_short_commit"
  if [[ -n "$(git -C "$local_engine_repo" status --porcelain --untracked-files=normal)" ]]; then
    local_engine_dirty=true
    local_engine_label="$local_engine_label.dirty"
  fi

  engine_archive_path="$local_engine_repo/out/lsfg-vk-$archive_version-local.$local_engine_label-linux.tar.xz"
  flatpak_archive_path="$local_engine_repo/out/lsfg-vk-$archive_version-local.$local_engine_label-flatpaks.tar.xz"
  archive_name="$(basename "$engine_archive_path")"
  flatpak_archive_name="$(basename "$flatpak_archive_path")"

  echo "Building local engine checkout $local_engine_label..."
  "$local_engine_repo/scripts/package-local.sh" "$engine_archive_path"
  "$local_engine_repo/scripts/package-flatpaks.sh" "$flatpak_archive_path"
fi

for local_archive in "$engine_archive_path" "$flatpak_archive_path"; do
  if [[ -n "$local_archive" && ! -f "$local_archive" ]]; then
    echo "Local archive not found: $local_archive" >&2
    exit 1
  fi
done

if [[ "$output_path_set" == false ]]; then
  if [[ "$local_engine_mode" == true ]]; then
    output_path="$project_dir/out/Decky.LSFG-VK.Experimental-local.$local_engine_label.zip"
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

echo "Testing launch-wrapper environment..."
npm --prefix "$project_dir" test

echo "Building frontend..."
npm --prefix "$project_dir" run build

mkdir -p "$package_dir/bin" "$package_dir/dist" "$package_dir/py_modules"
cp "$project_dir/scripts/lsfg-vk-experimental-diagnostics" \
  "$package_dir/bin/lsfg-vk-experimental-diagnostics"
chmod 0755 "$package_dir/bin/lsfg-vk-experimental-diagnostics"
if [[ -n "$engine_archive_path" ]]; then
  echo "Using local lsfg-vk $archive_version payload..."
  cp "$engine_archive_path" "$package_dir/bin/$archive_name"
else
  echo "Downloading verified lsfg-vk $archive_version payload..."
  curl --fail --location --silent --show-error "$archive_url" \
    --output "$package_dir/bin/$archive_name"
fi

actual_checksum="$(${checksum_command[@]} "$package_dir/bin/$archive_name" | awk '{print $1}')"
if [[ "$local_engine_mode" == true ]]; then
  archive_checksum="$actual_checksum"
elif [[ "$actual_checksum" != "$archive_checksum" ]]; then
  echo "Checksum mismatch for $archive_name" >&2
  echo "Expected: $archive_checksum" >&2
  echo "Actual:   $actual_checksum" >&2
  exit 1
fi

if [[ -n "$flatpak_archive_name" ]]; then
  if [[ -n "$flatpak_archive_path" ]]; then
    echo "Using local experimental Flatpak extensions..."
    cp "$flatpak_archive_path" "$package_dir/bin/$flatpak_archive_name"
  else
    echo "Downloading verified experimental Flatpak extensions..."
    curl --fail --location --silent --show-error "$flatpak_archive_url" \
      --output "$package_dir/bin/$flatpak_archive_name"
  fi

  actual_flatpak_checksum="$(${checksum_command[@]} "$package_dir/bin/$flatpak_archive_name" | awk '{print $1}')"
  if [[ "$local_engine_mode" == true ]]; then
    flatpak_archive_checksum="$actual_flatpak_checksum"
  elif [[ "$actual_flatpak_checksum" != "$flatpak_archive_checksum" ]]; then
    echo "Checksum mismatch for $flatpak_archive_name" >&2
    echo "Expected: $flatpak_archive_checksum" >&2
    echo "Actual:   $actual_flatpak_checksum" >&2
    exit 1
  fi

  tar -xJf "$package_dir/bin/$flatpak_archive_name" -C "$package_dir/bin"
  rm -f "$package_dir/bin/$flatpak_archive_name"

  for flatpak_bundle in \
    org.freedesktop.Platform.VulkanLayer.lsfgvkexperimental-23.08.flatpak \
    org.freedesktop.Platform.VulkanLayer.lsfgvkexperimental-24.08.flatpak \
    org.freedesktop.Platform.VulkanLayer.lsfgvkexperimental-25.08.flatpak; do
    if [[ ! -s "$package_dir/bin/$flatpak_bundle" ]]; then
      echo "Flatpak bundle archive is missing $flatpak_bundle" >&2
      exit 1
    fi
  done
fi

echo "Assembling Decky archive..."
cp "$project_dir/LICENSE" "$project_dir/README.md" "$project_dir/main.py" \
  "$project_dir/package.json" "$project_dir/plugin.json" "$project_dir/shared_config.py" \
  "$package_dir/"
if [[ "$local_engine_mode" == true ]]; then
  node -e '
    const fs = require("node:fs");
    const manifestPath = process.argv[1];
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    const [binary] = manifest.remote_binary ?? [];
    if (!binary) throw new Error("package.json has no remote_binary entry");
    const [archiveName, engineVersion, archiveChecksum, sourceCommit,
      sourceDirty, flatpakName, flatpakChecksum] = process.argv.slice(2);
    const shortCommit = sourceCommit.slice(0, 7);
    const localLabel = `${shortCommit}${sourceDirty === "true" ? ".dirty" : ""}`;
    binary.name = archiveName;
    binary.version = `${engineVersion}-local.${localLabel}`;
    binary.release_tag = `local-worktree-${localLabel}`;
    binary.source_commit = sourceCommit;
    binary.local_worktree_dirty = sourceDirty === "true";
    binary.url = `local-worktree://${archiveName}`;
    binary.sha256hash = archiveChecksum;
    if (binary.flatpak_bundle) {
      binary.flatpak_bundle.name = flatpakName;
      binary.flatpak_bundle.url = `local-worktree://${flatpakName}`;
      binary.flatpak_bundle.sha256hash = flatpakChecksum;
    }
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
  ' "$package_dir/package.json" "$archive_name" "$archive_version" \
    "$archive_checksum" "$local_engine_commit" "$local_engine_dirty" \
    "$flatpak_archive_name" "$flatpak_archive_checksum"
fi
cp -R "$project_dir/dist/." "$package_dir/dist/"
cp -R "$project_dir/py_modules/." "$package_dir/py_modules/"

# Python bytecode is host-version-specific and is regenerated on Steam OS.
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
