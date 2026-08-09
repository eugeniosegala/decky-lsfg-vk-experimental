#!/usr/bin/env bash
# Build a complete, manually installable Decky plugin archive.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path=""
output_path_set=false

usage() {
  cat <<'EOF'
Usage: scripts/package-local.sh [output-path]

Builds a verified Decky plugin ZIP for local installation. It never creates a
tag, pushes commits, or changes GitHub.
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

if [[ "$output_path_set" == false ]]; then
  output_path="$project_dir/out/Decky.LSFG-VK.Experimental.zip"
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

echo "Downloading verified lsfg-vk $archive_version payload..."
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

if [[ -n "$flatpak_archive_name" ]]; then
  echo "Downloading verified experimental Flatpak extensions..."
  curl --fail --location --silent --show-error "$flatpak_archive_url" \
    --output "$package_dir/bin/$flatpak_archive_name"

  actual_flatpak_checksum="$(${checksum_command[@]} "$package_dir/bin/$flatpak_archive_name" | awk '{print $1}')"
  if [[ "$actual_flatpak_checksum" != "$flatpak_archive_checksum" ]]; then
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
