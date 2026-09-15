#!/usr/bin/env bash
# Synchronize shared skills and rules across Cursor config copies.
#
# Nightly cron example (persistent libnotify toast in the morning):
#
#   0 2 * * * DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
#     /home/russ/Documents/cursor-config/sync-skills-rules.sh --notify --push >>/tmp/sync-skills-rules.log 2>&1
#
# Replace 1000 with your UID (`id -u`). Alerts only on errors or merge-conflict branches.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$REPO_ROOT/scripts/sync_skills_rules.py" "$@"
