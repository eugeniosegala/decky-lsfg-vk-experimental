# Shared output-path safety for local packaging and release publishing.

canonicalize_existing_package_path() {
  node -e '
    const fs = require("node:fs");
    process.stdout.write(fs.realpathSync.native(process.argv[1]));
  ' "$1"
}

canonicalize_package_output_path() {
  local requested_path="$1"
  local output_parent output_name parent_suffix="" parent_name next_parent
  requested_path="$(node -e '
    const path = require("node:path");
    process.stdout.write(path.resolve(process.argv[1]));
  ' "$requested_path")"
  output_parent="$(dirname -- "$requested_path")"
  output_name="$(basename -- "$requested_path")"
  if [[ -z "$output_name" || "$output_name" == "." || "$output_name" == ".." ]]; then
    echo "Invalid package output path: $requested_path" >&2
    return 1
  fi
  while [[ ! -e "$output_parent" && ! -L "$output_parent" ]]; do
    parent_name="$(basename -- "$output_parent")"
    next_parent="$(dirname -- "$output_parent")"
    if [[ -z "$parent_name" || "$next_parent" == "$output_parent" ]]; then
      echo "Could not resolve package output parent: $requested_path" >&2
      return 1
    fi
    parent_suffix="/$parent_name$parent_suffix"
    output_parent="$next_parent"
  done
  if [[ ! -d "$output_parent" ]]; then
    echo "Package output parent is not a directory: $output_parent" >&2
    return 1
  fi
  output_parent="$(canonicalize_existing_package_path "$output_parent")"
  printf '%s%s/%s\n' "$output_parent" "$parent_suffix" "$output_name"
}

reject_unsafe_repository_output() {
  local project_dir="$1"
  local candidate="$2"
  local operation="$3"
  local relative_path status
  project_dir="$(canonicalize_existing_package_path "$project_dir")"
  if [[ "$candidate" != "$project_dir/"* ]]; then
    return 0
  fi
  relative_path="${candidate#"$project_dir/"}"
  if [[ "$relative_path" == ".git" || "$relative_path" == .git/* ]]; then
    echo "Refusing to $operation inside repository metadata: $candidate" >&2
    return 1
  fi
  if git -C "$project_dir" ls-files --error-unmatch -- \
      ":(icase,literal)$relative_path" >/dev/null 2>&1; then
    echo "Refusing to $operation to tracked output path: $candidate" >&2
    return 1
  else
    status=$?
    if [[ "$status" -ne 1 ]]; then
      echo "Could not classify the in-repository output path: $candidate" >&2
      return 1
    fi
  fi
}
