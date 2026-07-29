#!/usr/bin/env bash
# Build a complete, manually installable Decky plugin archive.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path="${1:-$project_dir/out/Decky.LSFG-VK.Experimental.zip}"

case "$output_path" in
  /*) ;;
  *) output_path="$project_dir/$output_path" ;;
esac

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

read -r archive_name archive_url archive_checksum < <(
  node -e '
    const manifest = require(process.argv[1]);
    const [binary] = manifest.remote_binary ?? [];
    if (!binary?.name || !binary?.url || !binary?.sha256hash) {
      process.exitCode = 1;
      throw new Error("package.json must define one verified remote_binary entry");
    }
    process.stdout.write(`${binary.name}\t${binary.url}\t${binary.sha256hash}\n`);
  ' "$project_dir/package.json"
)

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

mkdir -p "$(dirname "$output_path")"
rm -f "$output_path"
(
  cd "$staging_dir"
  zip -qr "$output_path" "$package_name"
)

unzip -t "$output_path" >/dev/null
echo "Created and verified: $output_path"
