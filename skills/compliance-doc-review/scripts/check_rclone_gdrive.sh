#!/usr/bin/env bash
# Preflight for compliance-doc-review: gdrive remote (no secrets printed).
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HINTS="${SKILL_DIR}/setup-rclone.md"

ok=0
fail() {
  echo "FAIL: $*" >&2
  ok=1
}

if ! command -v rclone >/dev/null 2>&1; then
  fail "rclone not in PATH (see setup-rclone.md Install section)"
  echo "--- Setup hints: ${HINTS} ---"
  exit 1
fi

echo "OK: rclone at $(command -v rclone)"

if ! rclone listremotes 2>/dev/null | grep -qx 'gdrive:'; then
  fail "remote gdrive: not in rclone listremotes"
  echo "Configured remotes:"
  rclone listremotes 2>/dev/null || true
  echo "--- Setup hints (read and summarize in report; do not paste secrets): ---"
  sed -n '1,120p' "$HINTS"
  exit 1
fi

echo "OK: gdrive: listed in rclone listremotes"

if ! rclone config show gdrive >/dev/null 2>&1; then
  fail "rclone config show gdrive failed"
  echo "--- Setup hints: ${HINTS} ---"
  exit 1
fi

ty="$(rclone config show gdrive 2>/dev/null | awk -F' = ' '/^type =/{print $2; exit}')"
sc="$(rclone config show gdrive 2>/dev/null | awk -F' = ' '/^scope =/{print $2; exit}')"
echo "OK: gdrive type=${ty:-unknown} scope=${sc:-unknown}"

if [[ "$ty" != "drive" ]]; then
  fail "expected type = drive for gdrive (got ${ty:-empty})"
fi

if ! rclone lsd 'gdrive:' --max-depth 1 >/dev/null 2>&1; then
  fail "rclone lsd gdrive: failed (auth, network, or token expired)"
  echo "Try: rclone config reconnect gdrive:"
  echo "--- Setup hints: ${HINTS} ---"
  exit 1
fi

echo "OK: rclone lsd gdrive: succeeded"
exit "$ok"
