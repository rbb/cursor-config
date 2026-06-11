#!/usr/bin/env python3
"""afterTabFileEdit hook: format Tab edits for hard-mode languages only."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_guides as sg

SUBPROCESS_TIMEOUT = 4.0


def main() -> int:
    try:
        payload = sg.read_stdin_json()
        raw_path = (
            payload.get("file_path")
            or payload.get("path")
            or sg.extract_file_path(payload.get("tool_input") or {})
        )
        if not raw_path:
            sg.emit_response()
            return 0

        file_path = Path(raw_path)
        if not file_path.is_file():
            sg.emit_response()
            return 0

        config = sg.load_config()
        entry = sg.resolve_language(file_path, config)
        if entry is None or entry.get("mode") != "hard":
            sg.emit_response()
            return 0

        workspace_root = sg.resolve_workspace_root(payload, file_path)
        sg.run_format(entry, file_path, workspace_root, SUBPROCESS_TIMEOUT)
        sg.emit_response()
        return 0
    except Exception as exc:  # noqa: BLE001 — hooks must fail open
        print(f"format-tab-edit: {exc}", file=sys.stderr)
        sg.emit_response()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
