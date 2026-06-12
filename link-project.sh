#!/usr/bin/env bash
# Copy cursor-config files into a project directory (see README.md).
# Cursor does not reliably follow symlinks under .cursor/, so files are copied.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: link-project.sh DEST

Create directories under DEST and copy hooks.json plus each file in
skills/, rules/, and hooks/, preserving the same relative paths. Example:

  mkdir -p dest/skills/gcm
  cp skills/gcm/SKILL.md dest/skills/gcm/SKILL.md

Skips any destination path that already exists as a regular file.
Replaces symlinked files or directories with real copies/directories.
EOF
}

if [[ $# -ne 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  [[ $# -eq 1 && "${1:-}" != "-h" && "${1:-}" != "--help" ]] || exit 0
fi

dest="$1"
if [[ ! -d "$dest" ]]; then
  echo "link-project.sh: not a directory: $dest" >&2
  exit 1
fi

dest="$(cd "$dest" && pwd)"

ensure_real_dir() {
  local dir="$1"

  if [[ -L "$dir" ]]; then
    echo "mkdir (replaced symlink): $dir"
    rm "$dir"
    mkdir "$dir"
  elif [[ ! -d "$dir" ]]; then
    mkdir "$dir"
  fi
}

ensure_real_dirs_for() {
  local dir="$1"

  if [[ "$dir" == "$dest" || "$dir" == "/" ]]; then
    return 0
  fi

  ensure_real_dirs_for "$(dirname "$dir")"
  ensure_real_dir "$dir"
}

copy_file() {
  local source="$1"
  local dest_path="$2"

  if [[ -L "$dest_path" ]]; then
    echo "replacing symlink with copy: $dest_path"
    rm "$dest_path"
  elif [[ -f "$dest_path" ]]; then
    echo "skip (file exists): $dest_path"
    return 0
  elif [[ -e "$dest_path" ]]; then
    echo "skip (path exists): $dest_path"
    return 0
  fi

  ensure_real_dirs_for "$(dirname "$dest_path")"
  cp "$source" "$dest_path"
  echo "copied: $dest_path"
}

for tree in skills rules hooks; do
  tree_dir="$REPO_ROOT/$tree"
  [[ -d "$tree_dir" ]] || continue

  while IFS= read -r -d '' dir; do
    relpath="${dir#$REPO_ROOT/}"
    ensure_real_dirs_for "$dest/$relpath"
  done < <(find "$tree_dir" -type d -print0)

  while IFS= read -r -d '' file; do
    relpath="${file#$REPO_ROOT/}"
    copy_file "$file" "$dest/$relpath"
  done < <(
    find "$tree_dir" -type f \
      ! -path '*/__pycache__/*' \
      ! -path '*/.git/*' \
      -print0
  )
done

if [[ -f "$REPO_ROOT/hooks.json" ]]; then
  copy_file "$REPO_ROOT/hooks.json" "$dest/hooks.json"
fi
