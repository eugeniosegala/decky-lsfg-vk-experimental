#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--" ]]; then
  shift
fi
exec "$script_dir/package-release.sh" --publish "$@"
