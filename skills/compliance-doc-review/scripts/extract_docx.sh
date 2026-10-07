#!/usr/bin/env bash
# Extract plain markdown from a .docx for agent review (pandoc required).
set -euo pipefail

usage() {
  echo "Usage: extract_docx.sh <input.docx> [output.md]" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage
in="$1"
[[ -f "$in" ]] || { echo "ERROR: not a file: $in" >&2; exit 1; }

if [[ $# -ge 2 ]]; then
  out="$2"
else
  base="$(basename "$in" .docx)"
  out="/tmp/${base}_extract.md"
fi

pandoc "$in" -t markdown -o "$out"
echo "$out"
