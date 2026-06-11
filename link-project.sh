#!/usr/bin/env bash
# Symlink cursor-config files into a project directory (see README.md).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: link-project.sh DEST

Create symlinks under DEST for hooks.json and each file in skills/, rules/,
and hooks/, preserving the same relative paths. Example:

  ln -s skills/gcm/SKILL.md dest/skills/gcm/SKILL.md

Skips any path that already exists as a symlink or as a regular file/directory.
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

link_if_missing() {
  local target="$1"
  local link_name="$2"

  if [[ -L "$link_name" ]]; then
    echo "skip (symlink exists): $link_name"
    return 0
  fi

  if [[ -e "$link_name" ]]; then
    echo "skip (path exists): $link_name"
    return 0
  fi

  mkdir -p "$(dirname "$link_name")"
  ln -sr "$target" "$link_name"
  echo "linked: $link_name -> $(readlink "$link_name")"
}

for tree in skills rules hooks; do
  tree_dir="$REPO_ROOT/$tree"
  [[ -d "$tree_dir" ]] || continue

  while IFS= read -r -d '' file; do
    relpath="${file#$REPO_ROOT/}"
    link_if_missing "$file" "$dest/$relpath"
  done < <(
    find "$tree_dir" -type f \
      ! -path '*/__pycache__/*' \
      ! -path '*/.git/*' \
      -print0
  )
done

if [[ -f "$REPO_ROOT/hooks.json" ]]; then
  link_if_missing "$REPO_ROOT/hooks.json" "$dest/hooks.json"
fi
