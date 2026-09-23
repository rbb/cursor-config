#!/usr/bin/env python3
"""Git helpers for update-src-rev commits.

Amend HEAD when it only changed SRCREV lines (recipe) or revision
attributes (manifest). Never runs git push.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

ISSUE_RE = re.compile(r"[A-Z][A-Z0-9]*-\d+")
REVISION_ATTR = re.compile(r'\brevision="[^"]*"')
SRCREV_LINE = re.compile(
    r'^(SRCREV(?:_[\w-]+)?)(\s*(?:\?=|=)\s*)"[0-9a-fA-F]{7,40}"'
)


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


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


def git_try(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def git_ref_exists(repo: Path, ref: str) -> bool:
    return git_try(["show-ref", "--verify", "--quiet", ref], repo).returncode == 0


def extract_issue(*repos: Path) -> str | None:
    for repo in repos:
        result = git_try(["branch", "--show-current"], repo)
        if result.returncode != 0:
            continue
        match = ISSUE_RE.search(result.stdout.strip())
        if match:
            return match.group(0)
    return None


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


def head_has_parent(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def path_is_dirty(repo: Path, rel: str) -> bool:
    out = run_git(["status", "--porcelain", "--", rel], repo)
    return bool(out.strip())


def repo_porcelain_lines(repo: Path) -> list[str]:
    """Return non-empty ``git status --porcelain`` lines."""
    out = run_git(["status", "--porcelain"], repo)
    return [line for line in out.splitlines() if line.strip()]


def repo_is_dirty(repo: Path) -> bool:
    """True when the repo has any uncommitted changes."""
    return bool(repo_porcelain_lines(repo))


def repo_is_untracked_only(repo: Path) -> bool:
    """True when dirty state is only untracked files (``??``)."""
    lines = repo_porcelain_lines(repo)
    if not lines:
        return False
    return all(line.startswith("??") for line in lines)


def repo_has_tracked_changes(repo: Path) -> bool:
    """True when index or worktree has non-untracked changes."""
    for line in repo_porcelain_lines(repo):
        if line.startswith("??"):
            continue
        return True
    return False


def repo_untracked_sample(repo: Path, limit: int = 5) -> list[str]:
    """Paths from untracked porcelain lines, at most ``limit``."""
    paths: list[str] = []
    for line in repo_porcelain_lines(repo):
        if not line.startswith("??"):
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def current_branch(repo: Path) -> str:
    """Return the current branch name, or empty string on detached HEAD."""
    return run_git(["branch", "--show-current"], repo)


def push_needed(repo: Path, branch: str) -> bool:
    """True when local branch is not already on origin."""
    local_ref = f"refs/heads/{branch}"
    if not git_ref_exists(repo, local_ref):
        return False
    remote_ref = f"refs/remotes/origin/{branch}"
    if not git_ref_exists(repo, remote_ref):
        return True
    local_sha = run_git(["rev-parse", local_ref], repo)
    remote_sha = run_git(["rev-parse", remote_ref], repo)
    return local_sha != remote_sha


def push_branch_warnings(repo: Path, branch: str) -> list[str]:
    """Warnings for push hints when local branch may not match remote."""
    warnings: list[str] = []
    remote_ref = f"refs/remotes/origin/{branch}"
    if not git_ref_exists(repo, remote_ref):
        warnings.append(
            f"origin/{branch} does not exist yet (first push for this repo)"
        )
        return warnings
    local_ref = f"refs/heads/{branch}"
    if not git_ref_exists(repo, local_ref):
        return warnings
    local_sha = run_git(["rev-parse", local_ref], repo)
    remote_sha = run_git(["rev-parse", remote_ref], repo)
    if local_sha != remote_sha:
        warnings.append(
            f"local {branch} differs from origin/{branch}; "
            "push may need --force-with-lease"
        )
    return warnings


def parse_unified_diff(
    diff: str,
) -> tuple[list[str], list[str], list[str]]:
    """Return (files, minus_lines, plus_lines) from a unified diff."""
    files: list[str] = []
    minus: list[str] = []
    plus: list[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3]
                if path.startswith("b/"):
                    path = path[2:]
                files.append(path)
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("@@") or line.startswith("\\"):
            continue
        if line.startswith("+"):
            plus.append(line[1:])
        elif line.startswith("-"):
            minus.append(line[1:])
    return files, minus, plus


def is_revision_only_diff(diff: str) -> bool:
    """True if the diff only changes revision attributes in default.xml."""
    files, minus, plus = parse_unified_diff(diff)
    if not files or not minus or not plus:
        return False
    for path in files:
        if Path(path).name != "default.xml":
            return False

    def norm(text: str) -> str:
        return REVISION_ATTR.sub('revision=""', text)

    if Counter(norm(x) for x in minus) != Counter(norm(x) for x in plus):
        return False
    return any(REVISION_ATTR.search(x) for x in minus + plus)


def is_srcrev_only_diff(diff: str) -> bool:
    """True if the diff only changes SRCREV lines in .bb/.inc files."""
    files, minus, plus = parse_unified_diff(diff)
    if not files or not minus or not plus:
        return False
    for path in files:
        if Path(path).suffix not in {".bb", ".inc"}:
            return False

    def norm(text: str) -> str:
        return SRCREV_LINE.sub(r'\1\2"SHA"', text)

    if Counter(norm(x) for x in minus) != Counter(norm(x) for x in plus):
        return False
    return any(SRCREV_LINE.search(x) for x in minus + plus)


def head_is_kind(repo: Path, predicate: Callable[[str], bool]) -> bool:
    if not head_has_parent(repo):
        return False
    diff = run_git(["diff", "HEAD^", "HEAD"], repo)
    return predicate(diff)


def head_equals_upstream(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "@{u}"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    head = run_git(["rev-parse", "HEAD"], repo)
    upstream = run_git(["rev-parse", "@{u}"], repo)
    return head == upstream


def commit_or_amend(
    repo: Path,
    rel: str,
    message: str,
    predicate: Callable[[str], bool],
    *,
    quiet: bool = False,
) -> str:
    """Commit rel, or amend HEAD if HEAD is a matching skill-only commit.

    Returns 'amended' or 'committed'. Never pushes.
    """
    amend = head_is_kind(repo, predicate)
    subject, sep, body = message.partition("\n\n")
    cmd = ["commit"]
    if amend:
        if head_equals_upstream(repo) and not quiet:
            print(
                "INFO: amending a commit that matches origin; "
                "push may need --force-with-lease"
            )
        cmd.append("--amend")
    cmd.extend(["-m", subject])
    if sep and body:
        cmd.extend(["-m", body])
    cmd.extend(["--only", "--", rel])
    run_git(cmd, repo)
    kind = "amended" if amend else "committed"
    if not quiet:
        print(f"INFO: {kind} in {repo}: {subject}")
    return kind
