#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
generated_paths=(
  src/config/generatedConfigSchema.ts
  py_modules/lsfg_vk/config_schema_generated.py
  src/i18n/languages.json
)

for generated_path in "${generated_paths[@]}"; do
  if ! git -C "$project_dir" ls-files --error-unmatch -- "$generated_path" >/dev/null 2>&1; then
    echo "Generated output must remain tracked: $generated_path" >&2
    exit 1
  fi
done

python3 "$project_dir/scripts/generate_ts_schema.py"
(
  cd "$project_dir"
  ./scripts/build_i18n_json.sh
)

if ! git -C "$project_dir" diff --exit-code -- "${generated_paths[@]}"; then
  echo "Generated configuration bindings or translations are stale. Regenerate and commit them." >&2
  exit 1
fi

echo "Generated configuration bindings and translations are current."
