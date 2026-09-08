#!/usr/bin/env python3
"""
Pin a source-repo commit into the Yocto recipe and default.xml.

Steps:
1. Update SRCREV in the meta-judo recipe. Checkout or create a meta-layer
   branch matching the source repo branch (new branches from origin/main
   unless --base-existing), then commit the recipe.
2. Pin the source repo SHA in default.xml.
3. Pin the meta-layer (recipe repo) SHA in default.xml.

Never runs git push; only prints suggested commands. Stdlib only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from skill_git import (
    commit_or_amend,
    find_workspace_root,
    is_revision_only_diff,
    path_is_dirty,
    run_git,
)

SCRIPTS = Path(__file__).resolve().parent
BB_SCRIPT = SCRIPTS / "update_src_rev_bb.py"
XML_SCRIPT = SCRIPTS / "update_src_rev_xml.py"

META_LAYER_RE = re.compile(r"^INFO: meta layer (\S+)\s*$", re.MULTILINE)
META_HEAD_RE = re.compile(
    r"^INFO: meta-layer HEAD ([0-9a-fA-F]{7,40})\s*$",
    re.MULTILINE,
)
ISSUE_RE = re.compile(r"[A-Z][A-Z0-9]*-\d+")
SOURCE_BRANCH_RE = re.compile(r"^INFO: source branch (.+)$", re.MULTILINE)
PROJECT_LINE_RE = re.compile(
    r"^INFO: project name=(\S+) path=(\S+)\s*$",
    re.MULTILINE,
)
REVISION_LINE_RE = re.compile(
    r"^INFO: revision: (\S+) -> (\S+)\s*$",
    re.MULTILINE,
)
RECIPE_LINE_RE = re.compile(r"^INFO: recipe (\S+)\s*$", re.MULTILINE)
SRCREV_CHANGE_RE = re.compile(
    r"^INFO: (SRCREV(?:_[\w-]+)?): (\S+) -> (\S+)\s*$",
    re.MULTILINE,
)
XML_CHANGED_RE = re.compile(
    r"^RESULT: (?:updated|would update) manifest ",
    re.MULTILINE,
)
PUSH_RE = re.compile(r"^INFO: push (.+)$", re.MULTILINE)


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def run_step(label: str, cmd: list[str], dry_run: bool) -> tuple[int, str]:
    mode = "dry-run" if dry_run else "apply"
    print(f"=== {label} ({mode}) ===", flush=True)
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )
    print(flush=True)
    return result.returncode, result.stdout


def parse_bb_meta(stdout: str) -> tuple[str, str]:
    layer_match = META_LAYER_RE.search(stdout)
    head_match = META_HEAD_RE.search(stdout)
    if not layer_match:
        raise SystemExit(
            "ERROR: could not parse INFO: meta layer from BB output"
        )
    if not head_match:
        raise SystemExit(
            "ERROR: could not parse INFO: meta-layer HEAD from BB output"
        )
    return layer_match.group(1), head_match.group(1)


def collect_pushes(*stdouts: str) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for text in stdouts:
        for match in PUSH_RE.finditer(text):
            hint = match.group(1)
            if hint not in seen:
                seen.add(hint)
                lines.append(hint)
    return lines


def print_pushes(lines: list[str], dry_run: bool) -> None:
    """Print suggested push commands. Never run git push."""
    if not lines:
        return
    header = "PUSH (after apply):" if dry_run else "PUSH:"
    print(header, flush=True)
    for line in lines:
        print(line, flush=True)
    print("INFO: listed push commands only; did not push", flush=True)


def issue_from_bb(stdout: str, args: argparse.Namespace) -> str | None:
    if args.issue:
        return args.issue
    match = SOURCE_BRANCH_RE.search(stdout)
    if not match:
        return None
    found = ISSUE_RE.search(match.group(1))
    return found.group(0) if found else None


def branch_from_bb(stdout: str) -> str | None:
    match = SOURCE_BRANCH_RE.search(stdout)
    if not match:
        return None
    branch = match.group(1).strip()
    return branch or None


def parse_xml_project(stdout: str) -> dict[str, str] | None:
    project = PROJECT_LINE_RE.search(stdout)
    if not project:
        return None
    revision = REVISION_LINE_RE.search(stdout)
    return {
        "name": project.group(1),
        "path": project.group(2),
        "old": revision.group(1) if revision else "?",
        "new": revision.group(2) if revision else "?",
    }


def manifest_commit_message(
    issue: str,
    branch: str,
    bb_out: str,
    xml_outs: list[str],
) -> str:
    """Workspace commit: subject uses branch; body lists both projects."""
    subject = f"{issue}:{branch} Update SRCREV"
    lines: list[str] = []
    if xml_outs:
        source = parse_xml_project(xml_outs[0])
        if source:
            lines.extend(
                [
                    "Source project:",
                    f"  name: {source['name']}",
                    f"  path: {source['path']}",
                    f"  revision: {source['old']} -> {source['new']}",
                ]
            )
    recipe_proj = (
        parse_xml_project(xml_outs[1]) if len(xml_outs) > 1 else None
    )
    recipe_path = RECIPE_LINE_RE.search(bb_out)
    srcrev = SRCREV_CHANGE_RE.search(bb_out)
    if recipe_proj or recipe_path or srcrev:
        if lines:
            lines.append("")
        lines.append("Recipe project:")
        if recipe_proj:
            lines.extend(
                [
                    f"  name: {recipe_proj['name']}",
                    f"  path: {recipe_proj['path']}",
                    f"  revision: {recipe_proj['old']} -> "
                    f"{recipe_proj['new']}",
                ]
            )
        if recipe_path:
            lines.append(f"  recipe: {recipe_path.group(1)}")
        if srcrev:
            lines.append(
                f"  {srcrev.group(1)}: {srcrev.group(2)} -> "
                f"{srcrev.group(3)}"
            )
    body = "\n".join(lines).rstrip()
    if body:
        return f"{subject}\n\n{body}"
    return subject


def xml_changed(*stdouts: str) -> bool:
    return any(XML_CHANGED_RE.search(text) for text in stdouts)


def commit_manifest_bundle(
    args: argparse.Namespace,
    bb_out: str,
    xml_outs: list[str],
) -> None:
    workspace = (
        Path(args.workspace).resolve()
        if args.workspace
        else find_workspace_root(Path.cwd())
    )
    manifest = (
        Path(args.manifest).resolve()
        if args.manifest
        else (workspace / "default.xml").resolve()
    )
    repo = Path(run_git(["rev-parse", "--show-toplevel"], manifest.parent))
    try:
        rel = str(manifest.relative_to(repo))
    except ValueError:
        rel = str(manifest)
    if not path_is_dirty(repo, rel):
        print("INFO: no manifest changes to commit", flush=True)
        return
    issue = issue_from_bb(bb_out, args)
    if not issue:
        raise SystemExit(
            "ERROR: could not parse issue id from branch name; pass --issue"
        )
    branch = branch_from_bb(bb_out)
    if not branch:
        raise SystemExit(
            "ERROR: could not parse source branch name from recipe step"
        )
    message = manifest_commit_message(issue, branch, bb_out, xml_outs)
    kind = commit_or_amend(
        repo, rel, message, is_revision_only_diff
    )
    if kind == "amended":
        print("INFO: reused revision commit for default.xml", flush=True)
    print("RESULT: manifest commit complete", flush=True)


def build_common_args(args: argparse.Namespace) -> list[str]:
    common: list[str] = []
    if args.workspace:
        common.extend(["--workspace", args.workspace])
    if args.issue:
        common.extend(["--issue", args.issue])
    return common


def build_bb_cmd(
    args: argparse.Namespace, repo: str, dry_run: bool
) -> list[str]:
    cmd = [sys.executable, str(BB_SCRIPT), repo, *build_common_args(args)]
    if args.recipe:
        cmd.extend(["--recipe", args.recipe])
    if args.srcrev:
        cmd.extend(["--srcrev", args.srcrev])
    if args.base_existing:
        cmd.append("--base-existing")
    if args.no_commit:
        cmd.append("--no-commit")
    if dry_run:
        cmd.append("-n")
    return cmd


def build_xml_cmd(
    args: argparse.Namespace,
    project: str,
    dry_run: bool,
    revision: str | None = None,
) -> list[str]:
    cmd = [
        sys.executable,
        str(XML_SCRIPT),
        project,
        *build_common_args(args),
    ]
    if args.manifest:
        cmd.extend(["--manifest", args.manifest])
    if revision:
        cmd.extend(["--revision", revision])
    elif args.srcrev:
        cmd.extend(["--revision", args.srcrev])
    cmd.append("--no-commit")
    if dry_run:
        cmd.append("-n")
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="update_src_rev",
        description=(
            "Update recipe SRCREV, match the meta-layer branch to the "
            "source branch, and pin source plus recipe SHAs in default.xml."
        ),
    )
    parser.add_argument(
        "repo",
        help=(
            "Source repo name or path (required). Examples: mqtt-api, "
            "src/mqtt-api"
        ),
    )
    parser.add_argument(
        "--workspace",
        help="Repo workspace root (default: auto-detect in child scripts)",
    )
    parser.add_argument(
        "--recipe",
        help="Recipe .bb/.inc path override for BB step",
    )
    parser.add_argument(
        "--manifest",
        help="Manifest path override for XML steps",
    )
    parser.add_argument(
        "--srcrev",
        help="SHA for recipe and source-project pin (default: source HEAD)",
    )
    parser.add_argument(
        "--issue",
        help="Issue id for commit messages (default: parse from branch)",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Update files only; do not stage or commit",
    )
    parser.add_argument(
        "--base-existing",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Create a new recipe-repo branch from the current checkout "
            "instead of main (default: False)"
        ),
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Dry-run only; do not write or commit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not BB_SCRIPT.is_file():
        raise SystemExit(f"ERROR: BB script not found: {BB_SCRIPT}")
    if not XML_SCRIPT.is_file():
        raise SystemExit(f"ERROR: XML script not found: {XML_SCRIPT}")

    repo = args.repo

    code, bb_out = run_step(
        "recipe SRCREV",
        build_bb_cmd(args, repo, True),
        dry_run=True,
    )
    if code != 0:
        eprint(f"ERROR: recipe SRCREV dry-run failed (exit {code})")
        print("RESULT: aborted before apply", flush=True)
        return code

    meta_layer, meta_head = parse_bb_meta(bb_out)

    xml_source_cmd_dry = build_xml_cmd(args, repo, True)
    xml_meta_cmd_dry = build_xml_cmd(
        args, meta_layer, True, revision=meta_head
    )

    xml_outs: list[str] = []
    for label, cmd in (
        ("manifest source project", xml_source_cmd_dry),
        ("manifest recipe project", xml_meta_cmd_dry),
    ):
        code, xml_out = run_step(label, cmd, dry_run=True)
        if code != 0:
            eprint(f"ERROR: {label} dry-run failed (exit {code})")
            print("RESULT: aborted before apply", flush=True)
            return code
        xml_outs.append(xml_out)

    if args.dry_run:
        if xml_changed(*xml_outs):
            print(
                "INFO: would use one default.xml commit "
                "(amend if HEAD only changed revision attrs)",
                flush=True,
            )
        print("RESULT: dry-run complete for all requested steps", flush=True)
        print_pushes(collect_pushes(bb_out, *xml_outs), dry_run=True)
        return 0

    applied: list[str] = []

    code, bb_out = run_step(
        "recipe SRCREV",
        build_bb_cmd(args, repo, False),
        dry_run=False,
    )
    if code != 0:
        eprint(f"ERROR: recipe SRCREV apply failed (exit {code})")
        print("RESULT: apply incomplete", flush=True)
        return code
    applied.append("recipe SRCREV")
    meta_layer, meta_head = parse_bb_meta(bb_out)

    apply_xml: list[tuple[str, list[str]]] = [
        (
            "manifest source project",
            build_xml_cmd(args, repo, False),
        ),
        (
            "manifest recipe project",
            build_xml_cmd(args, meta_layer, False, revision=meta_head),
        ),
    ]
    xml_outs: list[str] = []
    for label, cmd in apply_xml:
        code, xml_out = run_step(label, cmd, dry_run=False)
        if code != 0:
            eprint(f"ERROR: {label} apply failed (exit {code})")
            if applied:
                eprint(
                    "WARNING: partial apply; earlier steps may have "
                    "committed: " + ", ".join(applied)
                )
            print("RESULT: apply incomplete", flush=True)
            print_pushes(collect_pushes(bb_out, *xml_outs), dry_run=False)
            return code
        applied.append(label)
        xml_outs.append(xml_out)

    if not args.no_commit:
        print("=== manifest commit (apply) ===", flush=True)
        commit_manifest_bundle(args, bb_out, xml_outs)
        print(flush=True)
        applied.append("manifest commit")

    targets = " and ".join(applied)
    print(f"RESULT: apply complete ({targets})", flush=True)
    print_pushes(collect_pushes(bb_out, *xml_outs), dry_run=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
