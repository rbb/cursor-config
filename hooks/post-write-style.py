#!/usr/bin/env python3
"""postToolUse hook: inject style guides; format/lint hard-mode languages."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_guides as sg

SUBPROCESS_TIMEOUT = 9.0


def main() -> int:
    try:
        payload = sg.read_stdin_json()
        tool_input = payload.get("tool_input") or {}
        raw_path = sg.extract_file_path(tool_input)
        if not raw_path:
            sg.emit_response()
            return 0

        file_path = Path(raw_path)
        if not file_path.is_file():
            sg.emit_response()
            return 0

        config = sg.load_config()
        entry = sg.resolve_language(file_path, config)
        if entry is None:
            sg.emit_response()
            return 0

        workspace_root = sg.resolve_workspace_root(payload, file_path)
        rule_result = sg.load_rule_text(entry["rule_file"], workspace_root, config)
        rule_body = rule_result[0] if rule_result else None
        rule_path = rule_result[1] if rule_result else None

        format_note = None
        lint_note = None
        if entry.get("mode") == "hard":
            format_note = sg.run_format(
                entry, file_path, workspace_root, SUBPROCESS_TIMEOUT
            )
            lint_note = sg.run_lint(
                entry, file_path, workspace_root, SUBPROCESS_TIMEOUT
            )

        if not rule_body and not format_note and not lint_note:
            sg.emit_response()
            return 0

        context = sg.build_additional_context(
            entry,
            rule_path,
            rule_body,
            file_path,
            workspace_root,
            format_note=format_note,
            lint_note=lint_note,
        )
        sg.emit_response(context)
        return 0
    except Exception as exc:  # noqa: BLE001 — hooks must fail open
        print(f"post-write-style: {exc}", file=sys.stderr)
        sg.emit_response()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
