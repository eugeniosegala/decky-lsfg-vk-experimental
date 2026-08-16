#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source_dir="$project_dir/defaults/i18n"
output_dir="$project_dir/src/i18n"
output_path="$output_dir/languages.json"

if [[ ! -d "$source_dir" ]]; then
  echo "Error: Directory $source_dir not found." >&2
  exit 1
fi

mkdir -p "$output_dir"
temporary_path="$(mktemp "$output_dir/.languages.json.XXXXXX")"
cleanup() {
  rm -f "$temporary_path"
}
trap cleanup EXIT

node --input-type=module - "$source_dir" > "$temporary_path" <<'NODE'
import { basename, extname, join } from "node:path";
import { readdirSync, readFileSync } from "node:fs";

const sourceDirectory = process.argv[2];
const files = readdirSync(sourceDirectory)
  .filter((name) => extname(name) === ".json")
  .sort();
const languages = {};

for (const name of files) {
  const key = basename(name, ".json");
  languages[key] = JSON.parse(readFileSync(join(sourceDirectory, name), "utf8"));
}

process.stdout.write(`${JSON.stringify(languages, null, 2)}\n`);
NODE

chmod 0644 "$temporary_path"
mv -f "$temporary_path" "$output_path"
trap - EXIT
