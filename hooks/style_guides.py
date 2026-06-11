#!/usr/bin/env python3
"""Shared helpers for style-guide enforcement hooks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent / "style-guides.json"
CONTEXT_CAP = 3500
KEY_RULE_LINES = 12

_LINT_CONFIG: dict[str, tuple[str, ...]] = {
    "python": ("pyproject.toml",),
    "rust": ("Cargo.toml",),
    "cpp": ("pyproject.toml", ".clang-format"),
}


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text.strip()
    match = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    if match:
        return text[match.end() :].strip()
    return text.strip()


def resolve_language(path: str | Path, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    config = config or load_config()
    suffix = Path(path).suffix.lower()
    if not suffix:
        return None
    for entry in config.get("languages", []):
        if suffix in entry.get("extensions", []):
            return entry
    return None


def find_rule_path(rule_file: str, workspace_root: Path, config: dict[str, Any] | None = None) -> Path | None:
    config = config or load_config()
    for rule_dir in config.get("rule_dirs", []):
        candidate = workspace_root / rule_dir / rule_file
        if candidate.is_file():
            return candidate
    return None


def load_rule_text(rule_file: str, workspace_root: Path, config: dict[str, Any] | None = None) -> tuple[str, Path] | None:
    path = find_rule_path(rule_file, workspace_root, config)
    if path is None:
        return None
    body = strip_frontmatter(path.read_text(encoding="utf-8"))
    return body, path


def extract_key_rules(body: str, max_lines: int = KEY_RULE_LINES) -> str:
    bullets: list[str] = []
    for line in body.splitlines():
        if re.match(r"^- ", line):
            bullets.append(line.strip())
            if len(bullets) >= max_lines:
                break
    if bullets:
        return "Key rules:\n" + "\n".join(bullets)
    excerpt = body[:800].strip()
    if len(body) > 800:
        excerpt += "\n..."
    return f"Key rules:\n{excerpt}"


def substitute_path(cmd: list[str], file_path: Path) -> list[str]:
    path_str = str(file_path)
    return [part.replace("{path}", path_str) for part in cmd]


def command_binary(cmd: list[str] | None) -> str | None:
    if not cmd:
        return None
    return cmd[0]


def has_lint_config(language_id: str, workspace_root: Path) -> bool:
    markers = _LINT_CONFIG.get(language_id)
    if not markers:
        return True
    return any((workspace_root / marker).exists() for marker in markers)


def run_cmd(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        combined = "\n".join(part for part in (stdout, stderr) if part)
        return result.returncode, combined, combined
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except OSError as exc:
        return -1, "", str(exc)


def run_format(
    entry: dict[str, Any],
    file_path: Path,
    workspace_root: Path,
    timeout: float,
) -> str | None:
    fmt = entry.get("format")
    if not fmt:
        return None
    binary = command_binary(fmt)
    if not binary or not shutil.which(binary):
        return None
    cmd = substitute_path(fmt, file_path)
    run_cmd(cmd, timeout)
    rel = file_path.relative_to(workspace_root) if file_path.is_relative_to(workspace_root) else file_path
    return f"Formatter: {binary} applied to {rel}"


def run_lint(
    entry: dict[str, Any],
    file_path: Path,
    workspace_root: Path,
    timeout: float,
) -> str | None:
    lint = entry.get("lint")
    if not lint:
        return None
    language_id = entry.get("id", "")
    if not has_lint_config(language_id, workspace_root):
        return None
    binary = command_binary(lint)
    if not binary or not shutil.which(binary):
        return None
    cmd = substitute_path(lint, file_path)
    returncode, output, _ = run_cmd(cmd, timeout)
    if not output and returncode == 0:
        return None
    label = " ".join(lint[:2]) if len(lint) >= 2 else binary
    header = f"Linter ({label}):"
    if returncode == 0 and not output:
        return None
    return f"{header}\n{output}" if output else header


def missing_hard_tools(config: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    config = config or load_config()
    missing: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in config.get("languages", []):
        if entry.get("mode") != "hard":
            continue
        for key in ("format", "lint"):
            cmd = entry.get(key)
            binary = command_binary(cmd)
            if not binary or binary in seen:
                continue
            seen.add(binary)
            if not shutil.which(binary):
                lang_id = entry.get("id", "unknown")
                purpose = f"{lang_id} {key}"
                missing.append((binary, purpose))
    return missing


def format_tooling_warning(missing: list[tuple[str, str]]) -> str:
    lines = [
        "Style hook tooling: hard-mode auto-format is degraded.",
        "Missing on PATH: " + ", ".join(f"{name} ({purpose})" for name, purpose in missing),
        "Install these for automatic post-edit formatting. "
        "Soft-mode rules (TS/JS, Markdown) are unaffected.",
    ]
    return "\n".join(lines)


def extract_file_path(tool_input: dict[str, Any]) -> str | None:
    for key in ("path", "file_path", "target_file"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_workspace_root(payload: dict[str, Any], file_path: Path | None = None) -> Path:
    roots = payload.get("workspace_roots") or payload.get("workspace_root")
    if isinstance(roots, list) and roots:
        return Path(roots[0]).resolve()
    if isinstance(roots, str) and roots:
        return Path(roots).resolve()
    if file_path is not None and file_path.is_absolute():
        return file_path.parent.resolve()
    return Path.cwd().resolve()


def build_additional_context(
    entry: dict[str, Any],
    rule_path: Path | None,
    rule_body: str | None,
    file_path: Path,
    workspace_root: Path,
    format_note: str | None = None,
    lint_note: str | None = None,
) -> str:
    rel_file = file_path.relative_to(workspace_root) if file_path.is_relative_to(workspace_root) else file_path
    rule_name = entry.get("rule_file", "style guide")
    if rule_path is not None:
        rel_rule = (
            rule_path.relative_to(workspace_root)
            if rule_path.is_relative_to(workspace_root)
            else rule_path
        )
        header = f"Style guide applied: {rule_name} ({rel_rule})"
    else:
        header = f"Style guide applied: {rule_name}"

    parts = [header, ""]
    mode = entry.get("mode", "soft")

    if rule_body:
        parts.append(extract_key_rules(rule_body))
        parts.append("")
    elif mode == "soft":
        parts.append(f"Follow this guide for {rel_file}.")
        parts.append("")

    if format_note:
        parts.append(format_note)
    if lint_note:
        parts.append(lint_note)
        parts.append("")
        parts.append("Fix any linter issues in your next edit. Re-read the file after formatting.")
    elif mode == "soft":
        parts.append(f"Re-read the file and align your next edit with the full guide above.")

    text = "\n".join(parts).strip()
    if len(text) > CONTEXT_CAP:
        text = text[: CONTEXT_CAP - 3].rstrip() + "..."
    return text


def emit_response(additional_context: str | None = None) -> None:
    if additional_context:
        print(json.dumps({"additional_context": additional_context}))
    else:
        print("{}")


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)
