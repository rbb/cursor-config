#!/usr/bin/env python3
"""
Update a single <project revision="..."> in default.xml from source repo HEAD.

Matches one project line by name or path. Preserves manifest formatting;
validates XML after write. Commits in the manifest git repository.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from skill_git import commit_or_amend, is_revision_only_diff

ISSUE_RE = re.compile(r"[A-Z][A-Z0-9]*-\d+")
ATTR_NAME = re.compile(r'\bname="([^"]*)"')
ATTR_PATH = re.compile(r'\bpath="([^"]*)"')
REVISION_ATTR_START = re.compile(r'\brevision="')


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def find_workspace_root(start: Path) -> Path:
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".repo").is_dir():
            return parent
        if (parent / "default.xml").is_file() and (parent / "oe").is_dir():
            return parent
    raise SystemExit(f"ERROR: no repo workspace found above {start}")


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def workspace_rel(path: Path, workspace: Path) -> str:
    resolved = path.resolve()
    root = workspace.resolve()
    if resolved == root:
        return "."
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def print_push_hint(repo_rel: str, branch: str) -> None:
    if not branch:
        return
    print(f"INFO: push {repo_rel}: git push origin {branch}")


def normalize_project_arg(project_arg: str) -> tuple[str | None, str | None]:
    """Return (name, path) hints from the project argument."""
    raw = project_arg.strip().strip("/")
    if not raw:
        raise SystemExit("ERROR: project name is required")

    if raw.startswith("src/") or raw.startswith("oe/") or raw.startswith(
        "test/"
    ) or raw.startswith("devops/") or raw.startswith("extras/"):
        return None, raw

    return raw, f"src/{raw}"


def infer_project_from_cwd(
    cwd: Path, workspace: Path
) -> tuple[str | None, str | None]:
    resolved = cwd.resolve()
    try:
        rel = resolved.relative_to(workspace)
    except ValueError:
        return None, None

    parts = rel.parts
    if len(parts) >= 2:
        return None, "/".join(parts[:2])
    if len(parts) == 1 and parts[0] != ".":
        return parts[0], None
    return None, None


def is_project_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("<project"):
        return False
    return "/>" in stripped


def parse_project_attrs(line: str) -> tuple[str, str] | None:
    nm = ATTR_NAME.search(line)
    pm = ATTR_PATH.search(line)
    if not nm or not pm:
        return None
    return (nm.group(1), pm.group(1))


def revision_value_span(line: str) -> tuple[int, int] | None:
    match = REVISION_ATTR_START.search(line)
    if not match:
        return None
    value_start = match.end()
    value_end = line.find('"', value_start)
    if value_end < 0:
        return None
    return (value_start, value_end)


def parse_revision(line: str) -> str | None:
    span = revision_value_span(line)
    if not span:
        return None
    return line[span[0] : span[1]]


def escape_attr_value(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
    )


def merge_revision_into_line(line: str, new_revision: str) -> str:
    esc = escape_attr_value(new_revision)
    span = revision_value_span(line)
    if span:
        value_start, value_end = span
        return line[:value_start] + esc + line[value_end:]

    closing = line.rfind("/>")
    if closing < 0:
        return line
    before = line[:closing]
    after = line[closing:]
    sep = "" if before.endswith((" ", "\t")) else " "
    return f'{before}{sep}revision="{esc}" {after}'


def project_matches(
    name: str,
    path: str,
    name_hint: str | None,
    path_hint: str | None,
) -> bool:
    if name_hint and name == name_hint:
        return True
    if path_hint and path == path_hint:
        return True
    return False


def find_project_matches(
    manifest_text: str,
    name_hint: str | None,
    path_hint: str | None,
) -> list[tuple[int, str, str, str]]:
    matches: list[tuple[int, str, str, str]] = []
    for index, line in enumerate(manifest_text.splitlines(keepends=True)):
        raw = line.rstrip("\r\n")
        if not is_project_line(raw):
            continue
        attrs = parse_project_attrs(raw)
        if not attrs:
            continue
        name, path = attrs
        if project_matches(name, path, name_hint, path_hint):
            revision = parse_revision(raw) or ""
            matches.append((index, name, path, revision))
    return matches


def validate_manifest(path: Path) -> None:
    try:
        ET.parse(path)
    except ET.ParseError as exc:
        raise SystemExit(f"ERROR: invalid XML after write: {exc}") from exc


def extract_issue(*repos: Path) -> str | None:
    for repo in repos:
        try:
            branch = run_git(["branch", "--show-current"], repo)
        except subprocess.CalledProcessError:
            continue
        match = ISSUE_RE.search(branch)
        if match:
            return match.group(0)
    return None


def commit_manifest(
    manifest: Path, issue: str, project_name: str
) -> None:
    manifest_repo = Path(
        run_git(["rev-parse", "--show-toplevel"], manifest.parent)
    )
    rel = str(manifest.relative_to(manifest_repo))
    message = f"{issue}:{project_name} Update revision"
    kind = commit_or_amend(
        manifest_repo, rel, message, is_revision_only_diff
    )
    if kind == "amended":
        print(f"INFO: reused revision commit in {manifest_repo}")


def resolve_source_repo(
    workspace: Path, project_path: str, cwd: Path
) -> Path:
    candidate = workspace / project_path
    if candidate.is_dir() and is_git_repo(candidate):
        return candidate

    inferred_name, inferred_path = infer_project_from_cwd(cwd, workspace)
    if inferred_path and inferred_path == project_path:
        if candidate.is_dir() and is_git_repo(candidate):
            return candidate

    raise SystemExit(
        f"ERROR: source repo not found or not a git repo: {candidate}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="update_src_rev_xml",
        description=(
            "Update one <project revision=...> in default.xml from source "
            "repo HEAD. The required project argument names the project by "
            "name or path; infer from cwd when possible."
        ),
    )
    parser.add_argument(
        "project",
        help=(
            "Project name or path (required). Examples: mqtt-api, "
            "src/mqtt-api"
        ),
    )
    parser.add_argument(
        "--workspace",
        help="Repo workspace root (default: auto-detect via .repo or default.xml)",
    )
    parser.add_argument(
        "--manifest",
        help="Manifest path (default: <workspace>/default.xml)",
    )
    parser.add_argument(
        "--revision",
        help="Revision value (default: git rev-parse HEAD in source repo)",
    )
    parser.add_argument(
        "--issue",
        help="Issue id for commit message (default: parse from branch name)",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Update file only; do not stage or commit",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing or committing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd()
    workspace = (
        Path(args.workspace).resolve()
        if args.workspace
        else find_workspace_root(cwd)
    )
    manifest = (
        Path(args.manifest).resolve()
        if args.manifest
        else (workspace / "default.xml").resolve()
    )
    if not manifest.is_file():
        raise SystemExit(f"ERROR: manifest not found: {manifest}")

    name_hint, path_hint = normalize_project_arg(args.project)
    cwd_name, cwd_path = infer_project_from_cwd(cwd, workspace)
    name_hint = name_hint or cwd_name
    path_hint = path_hint or cwd_path

    if not name_hint and not path_hint:
        raise SystemExit(
            "ERROR: project not resolved; pass a project name "
            "(e.g. mqtt-api, src/mqtt-api) or cd to the source repo"
        )

    manifest_text = manifest.read_text(encoding="utf-8")
    matches = find_project_matches(manifest_text, name_hint, path_hint)
    if not matches:
        raise SystemExit(
            f"ERROR: no <project> found in {manifest} for "
            f"name={name_hint!r} path={path_hint!r}"
        )
    if len(matches) > 1:
        listing = "\n".join(
            f"  - name={name} path={path}" for _, name, path, _ in matches
        )
        raise SystemExit(
            "ERROR: multiple manifest projects match; be more specific:\n"
            f"{listing}"
        )

    line_index, project_name, project_path, old_revision = matches[0]
    src_repo = resolve_source_repo(workspace, project_path, cwd)
    new_revision = args.revision or run_git(["rev-parse", "HEAD"], src_repo)

    manifest_rel = manifest
    try:
        manifest_rel = manifest.relative_to(workspace)
    except ValueError:
        pass

    print(f"INFO: {project_path} HEAD {new_revision}")
    print(f"INFO: manifest {manifest_rel}")
    print(f"INFO: project name={project_name} path={project_path}")
    print(f"INFO: revision: {old_revision} -> {new_revision}")
    manifest_repo = Path(
        run_git(["rev-parse", "--show-toplevel"], manifest.parent)
    )
    manifest_repo_rel = workspace_rel(manifest_repo, workspace)
    manifest_branch = run_git(["branch", "--show-current"], manifest_repo)
    print_push_hint(manifest_repo_rel, manifest_branch)

    if old_revision == new_revision:
        print(
            f"RESULT: manifest {manifest_rel} already matches "
            f"{project_path} HEAD ({new_revision})"
        )
        return 0

    lines = manifest_text.splitlines(keepends=True)
    updated_line = merge_revision_into_line(
        lines[line_index].rstrip("\r\n"),
        new_revision,
    )
    if not updated_line.endswith("\n"):
        updated_line += "\n"
    lines[line_index] = updated_line
    updated_text = "".join(lines)

    if args.dry_run:
        print(f"RESULT: would update manifest {manifest_rel}")
        return 0

    manifest.write_text(updated_text, encoding="utf-8")
    validate_manifest(manifest)

    if args.no_commit:
        print(f"RESULT: updated manifest {manifest_rel}")
        return 0

    issue = args.issue or extract_issue(manifest.parent, src_repo)
    if not issue:
        raise SystemExit(
            "ERROR: could not parse issue id from branch name; pass --issue"
        )

    commit_manifest(manifest, issue, project_name)
    print(f"RESULT: updated and committed manifest {manifest_rel}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        eprint(f"ERROR: git command failed: {' '.join(exc.cmd)}")
        if exc.stderr:
            eprint(exc.stderr.strip())
        raise SystemExit(1) from exc
