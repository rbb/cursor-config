#!/usr/bin/env python3
"""
Update SRCREV in a Yocto recipe (.bb or .inc) from a src/* git repo HEAD.

Auto-discovers the recipe by searching oe/meta-judo* for src/<repo-name>.
For multi-SRCREV recipes, updates the SRCREV whose git URI matches the repo.
Stages and commits in the meta-layer repo unless --no-commit is passed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ISSUE_RE = re.compile(r"[A-Z][A-Z0-9]*-\d+")
SRC_PATH_RE = re.compile(r"src/([A-Za-z0-9_.-]+)")
SRCREV_LINE_RE = re.compile(
    r'^(SRCREV(?:_[\w-]+)?)(\s*(?:\?=|=)\s*)"([0-9a-fA-F]{7,40})"',
    re.MULTILINE,
)
NAME_PARAM_RE = re.compile(r"(?:^|;)\s*name=([A-Za-z0-9_.-]+)")


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


def resolve_src_repo(src_arg: str | None, cwd: Path, workspace: Path) -> Path:
    if src_arg:
        path = Path(src_arg)
        if not path.is_absolute():
            path = (cwd / path).resolve()
        else:
            path = path.resolve()
    else:
        resolved = cwd.resolve()
        try:
            rel = resolved.relative_to(workspace)
        except ValueError as exc:
            raise SystemExit(
                "ERROR: cwd is not under the workspace; pass --src-repo"
            ) from exc
        parts = rel.parts
        if len(parts) < 2 or parts[0] != "src":
            raise SystemExit(
                "ERROR: cwd is not under src/<repo>; pass --src-repo"
            )
        path = workspace / "src" / parts[1]

    if not (path / ".git").exists():
        raise SystemExit(f"ERROR: not a git repo: {path}")
    return path


def repo_name_from_src(src_repo: Path) -> str:
    return src_repo.name


def meta_layer_roots(workspace: Path) -> list[Path]:
    oe_dir = workspace / "oe"
    if not oe_dir.is_dir():
        raise SystemExit(f"ERROR: missing oe/ under workspace {workspace}")
    roots = sorted(oe_dir.glob("meta-judo*"))
    if not roots:
        raise SystemExit("ERROR: no oe/meta-judo* layers found")
    return roots


def recipe_references_repo(content: str, repo_name: str) -> bool:
    needle = f"src/{repo_name}"
    for match in SRC_PATH_RE.finditer(content):
        if match.group(1) == repo_name:
            return True
    return needle in content


def discover_recipes(workspace: Path, repo_name: str) -> list[Path]:
    matches: list[Path] = []
    for layer in meta_layer_roots(workspace):
        for path in layer.rglob("*"):
            if path.suffix not in {".bb", ".inc"}:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if recipe_references_repo(content, repo_name):
                if find_srcrev_targets(content, repo_name):
                    matches.append(path)
    return sorted(matches)


def git_entries_for_repo(content: str, repo_name: str) -> list[str]:
    entries: list[str] = []
    for line in content.splitlines():
        if f"src/{repo_name}" not in line:
            continue
        if "git://" in line or "GIT_URI" in line or "EXTERNALSRC" in line:
            entries.append(line)
    return entries


def srcrev_var_names(content: str, repo_name: str) -> list[str]:
    entries = git_entries_for_repo(content, repo_name)
    if not entries:
        return []

    names: list[str] = []
    for entry in entries:
        name_match = NAME_PARAM_RE.search(entry)
        if name_match:
            names.append(f"SRCREV_{name_match.group(1)}")
        elif "EXTERNALSRC" in entry or "GIT_URI" in entry:
            names.append("SRCREV")
        elif "git://" in entry:
            names.append("SRCREV")

    deduped: list[str] = []
    for name in names:
        if name not in deduped:
            deduped.append(name)
    return deduped


def srcrev_vars_in_file(content: str) -> set[str]:
    return {match.group(1) for match in SRCREV_LINE_RE.finditer(content)}


def find_srcrev_targets(content: str, repo_name: str) -> list[str]:
    candidates = srcrev_var_names(content, repo_name)
    if not candidates:
        return []

    present = srcrev_vars_in_file(content)
    resolved = [name for name in candidates if name in present]
    if not resolved:
        return []
    if len(resolved) > 1:
        raise SystemExit(
            "ERROR: ambiguous SRCREV targets for "
            f"src/{repo_name}: {', '.join(resolved)}"
        )
    return resolved


def choose_srcrev_vars(content: str, repo_name: str) -> list[str]:
    targets = find_srcrev_targets(content, repo_name)
    if targets:
        return targets

    candidates = srcrev_var_names(content, repo_name)
    if candidates:
        raise SystemExit(
            f"ERROR: recipe references src/{repo_name} but no matching "
            f"SRCREV vars found ({', '.join(candidates)})"
        )
    return []


def replace_srcrev(content: str, var_name: str, new_rev: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf'^({re.escape(var_name)})(\s*(?:\?=|=)\s*)"([0-9a-fA-F]{{7,40}})"',
        re.MULTILINE,
    )

    def repl(match: re.Match[str]) -> str:
        return f'{match.group(1)}{match.group(2)}"{new_rev}"'

    updated, count = pattern.subn(repl, content, count=1)
    return updated, count == 1


def recipe_display_name(path: Path) -> str:
    stem = path.stem
    if stem.endswith("_git"):
        return stem[: -len("_git")]
    return stem


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


def resolve_recipe(
    workspace: Path,
    repo_name: str,
    recipe_arg: str | None,
) -> Path:
    if recipe_arg:
        recipe = Path(recipe_arg)
        if not recipe.is_absolute():
            recipe = (workspace / recipe).resolve()
        else:
            recipe = recipe.resolve()
        if not recipe.is_file():
            raise SystemExit(f"ERROR: recipe not found: {recipe}")
        content = recipe.read_text(encoding="utf-8")
        if not recipe_references_repo(content, repo_name):
            eprint(
                f"WARNING: {recipe} does not reference src/{repo_name}; "
                "continuing because --recipe was provided"
            )
        return recipe

    matches = discover_recipes(workspace, repo_name)
    if not matches:
        raise SystemExit(
            f"ERROR: no .bb/.inc recipe found for src/{repo_name} "
            "under oe/meta-judo*"
        )
    if len(matches) > 1:
        listing = "\n".join(f"  - {path}" for path in matches)
        raise SystemExit(
            "ERROR: multiple recipes reference "
            f"src/{repo_name}; pass --recipe:\n{listing}"
        )
    return matches[0]


def commit_recipe(recipe: Path, issue: str, recipe_name: str) -> None:
    meta_repo = Path(run_git(["rev-parse", "--show-toplevel"], recipe.parent))
    rel = recipe.relative_to(meta_repo)
    run_git(["add", str(rel)], meta_repo)
    message = f"{issue}:{recipe_name} Update SRCREV"
    run_git(["commit", "-m", message], meta_repo)
    print(f"INFO: committed in {meta_repo}: {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update SRCREV in a meta-judo recipe from src repo HEAD.",
    )
    parser.add_argument(
        "--workspace",
        help="Repo workspace root (default: auto-detect via .repo or default.xml)",
    )
    parser.add_argument(
        "--src-repo",
        help="Path to src/<repo> git tree (default: infer from cwd under src/)",
    )
    parser.add_argument(
        "--recipe",
        help="Recipe .bb/.inc path override (default: auto-discover)",
    )
    parser.add_argument(
        "--srcrev",
        help="SRCREV value (default: git rev-parse HEAD in src repo)",
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
    workspace = Path(args.workspace).resolve() if args.workspace else find_workspace_root(cwd)

    src_repo = resolve_src_repo(args.src_repo, cwd, workspace)
    repo_name = repo_name_from_src(src_repo)
    srcrev = args.srcrev or run_git(["rev-parse", "HEAD"], src_repo)

    recipe = resolve_recipe(workspace, repo_name, args.recipe)
    content = recipe.read_text(encoding="utf-8")
    targets = choose_srcrev_vars(content, repo_name)
    if not targets:
        raise SystemExit(
            f"ERROR: could not determine SRCREV variable for src/{repo_name} "
            f"in {recipe}"
        )

    var_name = targets[0]
    old_rev = "?"
    for match in SRCREV_LINE_RE.finditer(content):
        if match.group(1) == var_name:
            old_rev = match.group(3)
            break

    print(f"INFO: src/{repo_name} HEAD {srcrev}")
    print(f"INFO: recipe {recipe}")
    print(f"INFO: {var_name}: {old_rev} -> {srcrev}")

    if old_rev == srcrev:
        print("INFO: SRCREV already up to date")
        return 0

    updated, changed = replace_srcrev(content, var_name, srcrev)
    if not changed:
        raise SystemExit(
            f"ERROR: failed to update {var_name} in {recipe}"
        )

    if args.dry_run:
        print("INFO: dry run; no files changed")
        return 0

    recipe.write_text(updated, encoding="utf-8")
    print(f"INFO: updated {recipe}")

    if args.no_commit:
        return 0

    issue = args.issue or extract_issue(recipe.parent, src_repo)
    if not issue:
        raise SystemExit(
            "ERROR: could not parse issue id from branch name; pass --issue"
        )

    recipe_name = recipe_display_name(recipe)
    commit_recipe(recipe, issue, recipe_name)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        eprint(f"ERROR: git command failed: {' '.join(exc.cmd)}")
        if exc.stderr:
            eprint(exc.stderr.strip())
        raise SystemExit(1) from exc
