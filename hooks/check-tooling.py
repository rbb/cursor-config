#!/usr/bin/env python3
"""sessionStart hook: warn when hard-mode formatter/linter binaries are missing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_guides as sg


def main() -> int:
    try:
        missing = sg.missing_hard_tools()
        if not missing:
            sg.emit_response()
            return 0

        message = sg.format_tooling_warning(missing)
        print(message, file=sys.stderr)
        sg.emit_response(message)
        return 0
    except Exception as exc:  # noqa: BLE001 — hooks must fail open
        print(f"check-tooling: {exc}", file=sys.stderr)
        sg.emit_response()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
