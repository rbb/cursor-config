#!/usr/bin/env python3
"""
Pin a source-repo or meta-layer commit into default.xml (and SRCREV when
applicable).

Source repo (src/<name>) — three steps:
1. Update SRCREV in the meta-judo recipe and align the meta-layer branch.
2. Pin the source repo SHA in default.xml.
3. Pin the meta-layer (recipe repo) SHA in default.xml.

Meta layer (oe/meta-judo*) — manifest-only:
1. Align the workspace branch to the meta-layer branch.
2. Pin the meta-layer HEAD SHA in default.xml (amend if revision-only).

Never runs git push; only prints suggested commands. Stdlib only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from skill_git import (
    ISSUE_RE,
    commit_or_amend,
    current_branch,
    eprint,
    extract_issue,
    find_workspace_root,
    git_ref_exists,
    git_try,
    head_is_kind,
    is_git_repo,
    is_revision_only_diff,
    is_srcrev_only_diff,
    path_is_dirty,
    push_branch_warnings,
    push_needed,
    repo_has_tracked_changes,
    repo_is_dirty,
    repo_is_untracked_only,
    repo_untracked_sample,
    run_git,
    workspace_rel,
)

SRC_PATH_RE = re.compile(r"src/([A-Za-z0-9_.-]+)")
SRCREV_LINE_RE = re.compile(
    r'^(SRCREV(?:_[\w-]+)?)(\s*(?:\?=|=)\s*)"([0-9a-fA-F]{7,40})"',
    re.MULTILINE,
)
NAME_PARAM_RE = re.compile(r"(?:^|;)\s*name=([A-Za-z0-9_.-]+)")
ATTR_NAME = re.compile(r'\bname="([^"]*)"')
ATTR_PATH = re.compile(r'\bpath="([^"]*)"')
REVISION_ATTR_START = re.compile(r'\brevision="')
MANIFEST_JUDO_NAME = "manifest-judo"
MANIFEST_JUDO_PATH = "."


@dataclass
class PushHint:
    rel: str
    repo: Path
    branch: str


@dataclass
class RecipePin:
    path: Path
    rel: str
    var_name: str
    srcrev: str
    definite: bool


@dataclass
class RecipeResult:
    src_rel: str
    src_branch: str
    srcrev: str
    recipe_path: str
    meta_rel: str
    meta_head: str
    meta_note: str
    var_name: str
    old_rev: str
    changed: bool
    outcome: str
    push_hints: list[PushHint] = field(default_factory=list)
    issue: str | None = None
    split_pin_mismatches: list[str] = field(default_factory=list)


@dataclass
class ManifestPinResult:
    project_name: str
    project_path: str
    old_revision: str
    new_revision: str
    changed: bool
    outcome: str
    push_hints: list[PushHint] = field(default_factory=list)
    manifest_rel: str = "default.xml"


@dataclass
class RepoPreflightLine:
    label: str
    rel: str
    branch: str
    note: str


@dataclass
class PreflightResult:
    source_branch: str
    lines: list[RepoPreflightLine] = field(default_factory=list)
    meta_planned_head: str = ""
    meta_note: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class SkillContext:
    workspace: Path
    manifest: Path
    src_repo: Path | None
    meta_repo: Path
    manifest_repo: Path
    src_branch: str
    src_rel: str
    meta_rel: str
    manifest_repo_rel: str
    meta_layer_only: bool = False


@dataclass
class RepoTarget:
    mode: Literal["source", "meta_layer"]
    src_repo: Path | None
    meta_repo: Path | None
    layers: list[Path]


# --- pre-flight ---


def preflight_exit(paragraphs: list[str]) -> None:
    """Stop for agent AskQuestion; never mutate repos."""
    eprint("PREFLIGHT: action required")
    eprint("")
    for block in paragraphs:
        eprint(block)
        eprint("")
    raise SystemExit(2)


def branch_start_point(
    repo: Path, base_existing: bool
) -> tuple[str, str]:
    """Return (start_ref, sha) for a new branch from main or current."""
    if base_existing:
        current = current_branch(repo)
        start_ref = current if current else "HEAD"
        sha = run_git(["rev-parse", "HEAD"], repo)
        return start_ref, sha
    if git_ref_exists(repo, "refs/remotes/origin/main"):
        sha = run_git(["rev-parse", "refs/remotes/origin/main"], repo)
        return "origin/main", sha
    if git_ref_exists(repo, "refs/heads/main"):
        sha = run_git(["rev-parse", "refs/heads/main"], repo)
        return "main", sha
    raise SystemExit(
        "ERROR: no main or origin/main; pass --base-existing or fetch main"
    )


def remote_main_sha(repo: Path) -> str:
    """Return the current origin/main SHA, or an empty string."""
    result = git_try(["ls-remote", "origin", "refs/heads/main"], repo)
    if result.returncode != 0:
        return ""
    fields = result.stdout.strip().split()
    return fields[0] if fields else ""


MainSyncKind = Literal["behind", "diverged", "no_local", "no_remote"]

DIVERGED_MAIN_PLAYBOOK = [
    (
        "Diverged local main cannot be fixed by --fix-preflight "
        "(only fast-forward)."
    ),
    "Typical recovery in each affected repo:",
    "  git checkout main",
    "  git pull origin main",
    "  git checkout <your-feature-branch>",
    "  git rebase main",
    (
        "Re-run update-src-rev afterward; step 3 may need a new "
        "meta-layer manifest pin."
    ),
]


@dataclass(frozen=True)
class MainSyncProblem:
    kind: MainSyncKind
    label: str
    repo: Path
    message: str


def main_sync_problem(label: str, repo: Path) -> MainSyncProblem | None:
    """Classify why local main is not current with origin/main."""
    local_ref = "refs/heads/main"
    local_exists = git_ref_exists(repo, local_ref)
    remote_sha = remote_main_sha(repo)
    if not remote_sha:
        return MainSyncProblem(
            "no_remote",
            label,
            repo,
            f"{label} ({repo}): origin/main could not be read",
        )
    if not local_exists:
        return MainSyncProblem(
            "no_local",
            label,
            repo,
            f"{label} ({repo}): local main branch does not exist",
        )
    local_sha = run_git(["rev-parse", local_ref], repo)
    if local_sha == remote_sha:
        return None
    if git_try(
        ["merge-base", "--is-ancestor", local_sha, remote_sha], repo
    ).returncode == 0:
        return MainSyncProblem(
            "behind",
            label,
            repo,
            f"{label} ({repo}): local main is behind origin/main",
        )
    return MainSyncProblem(
        "diverged",
        label,
        repo,
        f"{label} ({repo}): local main has diverged from origin/main",
    )


def handle_main_sync_problems(
    repos: list[tuple[str, Path]],
    args: argparse.Namespace,
    dry_run: bool,
    warnings: list[str],
) -> None:
    """Fetch/ff main when fixable; stop or warn on diverged main."""
    problems = [
        p
        for label, repo in repos
        for p in [main_sync_problem(label, repo)]
        if p is not None
    ]
    if not problems:
        return

    messages = [p.message for p in problems]
    has_diverged = any(p.kind == "diverged" for p in problems)
    has_no_remote = any(p.kind == "no_remote" for p in problems)
    fixable_kinds = frozenset({"behind", "no_local"})
    manual_main = has_diverged or has_no_remote

    if manual_main and args.fix_preflight:
        eprint(
            "ERROR: --fix-preflight cannot fix diverged local main or "
            "unreadable origin/main; resolve manually or use "
            "--continue-preflight."
        )
        eprint("")
        if has_diverged:
            for line in DIVERGED_MAIN_PLAYBOOK:
                eprint(line)
        raise SystemExit(1)

    if manual_main:
        if args.continue_preflight:
            warnings.extend(messages)
            return
        paragraphs = [
            "The following main branches are not up to date:",
            *[f"  - {m}" for m in messages],
        ]
        if has_diverged:
            paragraphs.extend(DIVERGED_MAIN_PLAYBOOK)
        paragraphs.append(
            "Ask the user whether to abort or continue with "
            "--continue-preflight. Do not offer --fix-preflight when "
            "main has diverged or origin/main cannot be read."
        )
        preflight_exit(paragraphs)

    if args.fix_preflight:
        if not dry_run:
            for problem in problems:
                if problem.kind in fixable_kinds:
                    update_local_main(problem.repo)
        else:
            warnings.extend(messages)
        return

    if args.continue_preflight:
        warnings.extend(messages)
        return

    preflight_exit(
        [
            "The following main branches are not up to date:",
            *[f"  - {m}" for m in messages],
            (
                "Ask the user whether to fix them (fetch and "
                "fast-forward main), abort, or continue without "
                "changes."
            ),
        ]
    )


def check_source_workspace_branch_alignment(
    ctx: SkillContext,
    args: argparse.Namespace,
    warnings: list[str],
) -> None:
    """Stop when source and workspace are on different branch names."""
    if ctx.meta_layer_only or ctx.src_repo is None:
        return
    src_branch = current_branch(ctx.src_repo)
    ws_branch = current_branch(ctx.manifest_repo)
    if not src_branch or not ws_branch or src_branch == ws_branch:
        return
    rel = ctx.src_rel
    ws_rel = ctx.manifest_repo_rel
    detail = (
        f"Source repo {rel} is on {src_branch} but workspace "
        f"{ws_rel} is on {ws_branch}. Pins use the source branch "
        f"({src_branch}), not the workspace branch."
    )
    if args.continue_preflight:
        warnings.append(detail)
        return
    preflight_exit(
        [
            detail,
            (
                f"Check out {rel} on {ws_branch} (or the branch you "
                "intend to pin) before continuing."
            ),
            (
                "Ask the user whether to abort or continue with "
                "--continue-preflight if pinning from the source "
                "branch is intentional."
            ),
        ]
    )


def source_dirty_preflight(
    ctx: SkillContext,
    args: argparse.Namespace,
    target: str,
    lines: list[RepoPreflightLine],
    warnings: list[str],
) -> None:
    """Record source cleanliness; block on tracked edits, warn on untracked."""
    if ctx.src_repo is None:
        return
    rel = ctx.src_rel
    if not repo_is_dirty(ctx.src_repo):
        lines.append(
            RepoPreflightLine(
                label="Source",
                rel=rel,
                branch=target,
                note="clean",
            )
        )
        return

    if repo_is_untracked_only(ctx.src_repo):
        sample = repo_untracked_sample(ctx.src_repo)
        extra = ""
        if sample:
            shown = ", ".join(sample)
            if len(sample) >= 5:
                shown += ", ..."
            extra = f" (e.g. {shown})"
        warnings.append(
            f"Source repo {rel} has untracked files only{extra}; "
            "pin uses committed HEAD."
        )
        lines.append(
            RepoPreflightLine(
                label="Source",
                rel=rel,
                branch=target,
                note="untracked files only",
            )
        )
        return

    if not args.allow_dirty_source:
        preflight_exit(
            [
                (
                    f"Source repo {rel} has uncommitted tracked changes. "
                    "The pin will use the current HEAD, which may "
                    "include uncommitted work."
                ),
                (
                    "Ask the user whether to continue. Re-run with "
                    "--allow-dirty-source to pin the current HEAD, "
                    "or commit/stash in the source repo first."
                ),
            ]
        )
    lines.append(
        RepoPreflightLine(
            label="Source",
            rel=rel,
            branch=target,
            note="has uncommitted changes (--allow-dirty-source)",
        )
    )


def update_local_main(repo: Path) -> None:
    """Fetch origin/main and fast-forward the local main ref."""
    result = git_try(["fetch", "origin", "main"], repo)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(f"ERROR: could not fetch origin/main: {detail}")
    if not git_ref_exists(repo, "refs/heads/main"):
        run_git(["branch", "main", "origin/main"], repo)
        return
    if current_branch(repo) == "main":
        result = git_try(["merge", "--ff-only", "origin/main"], repo)
        if result.returncode != 0:
            raise SystemExit(
                "ERROR: local main diverged from origin/main; "
                "resolve it manually"
            )
        return
    result = git_try(["branch", "--ff-only", "main", "origin/main"], repo)
    if result.returncode != 0:
        raise SystemExit(
            "ERROR: local main diverged from origin/main; "
            "resolve it manually"
        )


def rename_current_branch(repo: Path, old: str, new: str) -> None:
    """Rename the current branch when it is the source branch."""
    current = current_branch(repo)
    if current != old or current == new:
        return
    if git_ref_exists(repo, f"refs/heads/{new}"):
        raise SystemExit(
            f"ERROR: cannot rename {old} to {new} in {repo}; "
            "the destination branch already exists"
        )
    run_git(["branch", "-m", new], repo)


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    """True when ancestor is contained in descendant's history."""
    return (
        git_try(
            ["merge-base", "--is-ancestor", ancestor, descendant], repo
        ).returncode
        == 0
    )


def existing_target_ref(repo: Path, target_branch: str) -> str | None:
    """Return local or origin ref for target_branch, or None."""
    local_ref = f"refs/heads/{target_branch}"
    if git_ref_exists(repo, local_ref):
        return target_branch
    remote_ref = f"refs/remotes/origin/{target_branch}"
    if git_ref_exists(repo, remote_ref):
        return f"origin/{target_branch}"
    return None


def branch_histories_compatible(
    repo: Path, current: str, target_ref: str
) -> bool:
    """True when checking out target_ref does not abandon current."""
    if is_ancestor(repo, current, target_ref):
        return True
    if is_ancestor(repo, target_ref, current):
        return True
    return False


def recreate_branch_from_current(
    repo: Path,
    target_branch: str,
    current: str,
    dry_run: bool,
) -> tuple[str, str]:
    """Reset target_branch to the current checkout."""
    sha = run_git(["rev-parse", "HEAD"], repo)
    if dry_run:
        return sha, (
            f"would recreate branch {target_branch} from {current}"
        )
    run_git(["checkout", "-B", target_branch], repo)
    return run_git(["rev-parse", "HEAD"], repo), (
        f"recreated branch {target_branch} from {current}"
    )


def check_branch_divergence(
    repo: Path,
    label: str,
    rel: str,
    current: str,
    target: str,
    args: argparse.Namespace,
) -> None:
    """Stop when an existing target branch diverges from current."""
    if current == target:
        return
    target_ref = existing_target_ref(repo, target)
    if not target_ref:
        return
    if branch_histories_compatible(repo, current, target_ref):
        return
    if args.recreate_branch or args.continue_preflight:
        return
    current_sha = run_git(["rev-parse", current], repo)
    target_sha = run_git(["rev-parse", target_ref], repo)
    preflight_exit(
        [
            (
                f"{label} ({rel}) is on {current} but {target} has "
                "diverged history (not stacked on the current checkout)."
            ),
            f"  current: {current_sha[:12]} ({current})",
            f"  target:  {target_sha[:12]} ({target_ref})",
            "Ask the user:",
            (
                f"  - recreate: re-run with --recreate-branch to reset "
                f"{target} from the current checkout ({current})"
            ),
            (
                "  - continue: re-run with --continue-preflight to "
                "checkout the existing branch as-is (may drop work "
                "from the current checkout)"
            ),
            "  - abort: stop without changes",
        ]
    )


def branch_alignment_plan(
    repo: Path,
    target_branch: str,
    base_existing: bool,
    dry_run: bool,
    recreate_branch: bool = False,
) -> tuple[str, str]:
    """Plan or apply branch alignment. Return (HEAD SHA, human note)."""
    current = current_branch(repo)
    if not current:
        raise SystemExit(
            "ERROR: detached HEAD; check out a named branch before continuing"
        )

    if current == target_branch:
        sha = run_git(["rev-parse", "HEAD"], repo)
        return sha, "already on matching branch"

    local_ref = f"refs/heads/{target_branch}"
    remote_ref = f"refs/remotes/origin/{target_branch}"

    if git_ref_exists(repo, local_ref):
        if not branch_histories_compatible(repo, current, target_branch):
            if recreate_branch:
                return recreate_branch_from_current(
                    repo, target_branch, current, dry_run
                )
        sha = run_git(["rev-parse", local_ref], repo)
        if dry_run:
            return sha, f"would checkout existing branch {target_branch}"
        run_git(["checkout", target_branch], repo)
        return run_git(["rev-parse", "HEAD"], repo), (
            f"checked out existing branch {target_branch}"
        )

    if git_ref_exists(repo, remote_ref):
        origin_ref = f"origin/{target_branch}"
        if not branch_histories_compatible(repo, current, origin_ref):
            if recreate_branch:
                return recreate_branch_from_current(
                    repo, target_branch, current, dry_run
                )
        sha = run_git(["rev-parse", remote_ref], repo)
        if dry_run:
            return sha, f"would checkout existing origin/{target_branch}"
        run_git(["checkout", "-B", target_branch, origin_ref], repo)
        return run_git(["rev-parse", "HEAD"], repo), (
            f"checked out existing origin/{target_branch}"
        )

    start_ref, sha = branch_start_point(repo, base_existing)
    if dry_run:
        return sha, f"would create branch {target_branch} from {start_ref}"
    run_git(["checkout", "-b", target_branch, start_ref], repo)
    return run_git(["rev-parse", "HEAD"], repo), (
        f"created branch {target_branch} from {start_ref}"
    )


def needs_branch_base_choice(
    repo: Path, target_branch: str, base_existing: bool
) -> bool:
    """True when a new branch needs main vs current choice from the user."""
    current = current_branch(repo)
    if not current or current == target_branch:
        return False
    if existing_target_ref(repo, target_branch):
        return False
    if current == "main":
        return False
    return not base_existing


def run_preflight_meta_layer(
    ctx: SkillContext,
    args: argparse.Namespace,
    dry_run: bool,
) -> PreflightResult:
    """Pre-flight for oe/meta-judo*: align workspace; pin layer HEAD only."""
    lines: list[RepoPreflightLine] = []
    target = ctx.src_branch
    warnings: list[str] = []

    handle_main_sync_problems(
        (
            ("Meta layer", ctx.meta_repo),
            ("Workspace", ctx.manifest_repo),
        ),
        args,
        dry_run,
        warnings,
    )

    if "_" in target:
        replacement = target.replace("_", "-")
        message = (
            f"Meta-layer branch {target} contains underscores; "
            f"the required branch name is {replacement}."
        )
        if args.fix_preflight:
            if not dry_run:
                for repo in (ctx.meta_repo, ctx.manifest_repo):
                    rename_current_branch(repo, target, replacement)
            target = replacement
            warnings.append(message + f" Renaming to {replacement}.")
        elif args.continue_preflight:
            warnings.append(message)
        else:
            preflight_exit(
                [
                    message,
                    (
                        "Ask the user whether to rename the local branches, "
                        "abort, or continue without changes."
                    ),
                ]
            )

    ctx.src_branch = target
    meta_planned_head = run_git(["rev-parse", "HEAD"], ctx.meta_repo)
    meta_note = "defines target branch"

    if repo_has_tracked_changes(ctx.meta_repo):
        if not args.allow_dirty_source:
            preflight_exit(
                [
                    (
                        f"Meta layer {ctx.meta_rel} has uncommitted "
                        "tracked changes. The pin uses committed HEAD only."
                    ),
                    (
                        "Ask the user whether to continue. Re-run with "
                        "--allow-dirty-source to continue, or commit/stash "
                        "in the meta layer first."
                    ),
                ]
            )
        lines.append(
            RepoPreflightLine(
                label="Meta layer",
                rel=ctx.meta_rel,
                branch=target,
                note="has uncommitted changes (--allow-dirty-source)",
            )
        )
    elif repo_is_untracked_only(ctx.meta_repo):
        warnings.append(
            f"Meta layer {ctx.meta_rel} has untracked files only; "
            "pin uses committed HEAD."
        )
        lines.append(
            RepoPreflightLine(
                label="Meta layer",
                rel=ctx.meta_rel,
                branch=target,
                note="untracked files only",
            )
        )
    else:
        lines.append(
            RepoPreflightLine(
                label="Meta layer",
                rel=ctx.meta_rel,
                branch=target,
                note="clean",
            )
        )

    repo = ctx.manifest_repo
    rel = ctx.manifest_repo_rel
    label = "Workspace"
    current = current_branch(repo)
    if not current:
        raise SystemExit(
            f"ERROR: {label} ({rel}) is on detached HEAD; "
            "check out a named branch first"
        )

    if current != target:
        if repo_has_tracked_changes(repo):
            preflight_exit(
                [
                    (
                        f"{label} ({rel}) is on {current} but the "
                        f"meta-layer branch is {target}, and the repo "
                        "has uncommitted tracked changes."
                    ),
                    (
                        "Commit or stash changes in that repo, then "
                        "re-run the skill."
                    ),
                ]
            )

        check_branch_divergence(
            repo, label, rel, current, target, args
        )

        if needs_branch_base_choice(repo, target, args.base_existing):
            preflight_exit(
                [
                    (
                        f"{label} ({rel}) is on {current} but the "
                        f"meta-layer branch is {target}. Branch "
                        f"{target} does not exist locally or on "
                        "origin."
                    ),
                    (
                        "Ask the user which base to use for the new "
                        f"branch {target}:"
                    ),
                    (
                        "  - main: re-run without --base-existing "
                        "(default)"
                    ),
                    (
                        f"  - current checkout ({current}): re-run "
                        "with --base-existing"
                    ),
                ]
            )

    _, note = branch_alignment_plan(
        repo,
        target,
        args.base_existing,
        dry_run,
        recreate_branch=args.recreate_branch,
    )
    lines.append(
        RepoPreflightLine(
            label=label,
            rel=rel,
            branch=target,
            note=note,
        )
    )

    return PreflightResult(
        source_branch=target,
        lines=lines,
        meta_planned_head=meta_planned_head,
        meta_note=meta_note,
        warnings=warnings,
    )


def run_preflight(
    ctx: SkillContext,
    args: argparse.Namespace,
    dry_run: bool,
) -> PreflightResult:
    """Validate branch alignment and source cleanliness before steps 1–3."""
    if ctx.meta_layer_only:
        return run_preflight_meta_layer(ctx, args, dry_run)

    if ctx.src_repo is None:
        raise SystemExit("ERROR: source repo is required for SRCREV updates")

    lines: list[RepoPreflightLine] = []
    original_target = ctx.src_branch
    target = original_target
    warnings: list[str] = []

    check_source_workspace_branch_alignment(ctx, args, warnings)

    handle_main_sync_problems(
        (
            ("Source repo", ctx.src_repo),
            ("Meta layer", ctx.meta_repo),
            ("Workspace", ctx.manifest_repo),
        ),
        args,
        dry_run,
        warnings,
    )

    if "_" in target:
        replacement = target.replace("_", "-")
        message = (
            f"Source branch {target} contains underscores; "
            f"the required branch name is {replacement}."
        )
        if args.fix_preflight:
            if not dry_run:
                for repo in (
                    ctx.src_repo,
                    ctx.meta_repo,
                    ctx.manifest_repo,
                ):
                    rename_current_branch(repo, target, replacement)
            target = replacement
            warnings.append(message + f" Renaming to {replacement}.")
        elif args.continue_preflight:
            warnings.append(message)
        else:
            preflight_exit(
                [
                    message,
                    (
                        "Ask the user whether to rename the local branches, "
                        "abort, or continue without changes."
                    ),
                ]
            )

    ctx.src_branch = target
    meta_planned_head = run_git(["rev-parse", "HEAD"], ctx.meta_repo)
    meta_note = "already on matching branch"

    source_dirty_preflight(ctx, args, target, lines, warnings)

    for label, repo, rel in (
        ("Meta layer", ctx.meta_repo, ctx.meta_rel),
        ("Workspace", ctx.manifest_repo, ctx.manifest_repo_rel),
    ):
        current = current_branch(repo)
        if not current:
            raise SystemExit(
                f"ERROR: {label} ({rel}) is on detached HEAD; "
                "check out a named branch first"
            )

        if current != target:
            if repo_has_tracked_changes(repo):
                preflight_exit(
                    [
                        (
                            f"{label} ({rel}) is on {current} but the "
                            f"source branch is {target}, and the repo "
                            "has uncommitted changes."
                        ),
                        (
                            "Commit or stash changes in that repo, then "
                            "re-run the skill."
                        ),
                    ]
                )

            check_branch_divergence(
                repo, label, rel, current, target, args
            )

            if needs_branch_base_choice(repo, target, args.base_existing):
                preflight_exit(
                    [
                        (
                            f"{label} ({rel}) is on {current} but the "
                            f"source branch is {target}. Branch "
                            f"{target} does not exist locally or on "
                            "origin."
                        ),
                        (
                            "Ask the user which base to use for the new "
                            f"branch {target}:"
                        ),
                        (
                            "  - main: re-run without --base-existing "
                            "(default)"
                        ),
                        (
                            f"  - current checkout ({current}): re-run "
                            "with --base-existing"
                        ),
                    ]
                )

        head, note = branch_alignment_plan(
            repo,
            target,
            args.base_existing,
            dry_run,
            recreate_branch=args.recreate_branch,
        )
        line = RepoPreflightLine(
            label=label,
            rel=rel,
            branch=target,
            note=note,
        )
        lines.append(line)
        if label == "Meta layer":
            meta_planned_head = head
            meta_note = note

    return PreflightResult(
        source_branch=target,
        lines=lines,
        meta_planned_head=meta_planned_head,
        meta_note=meta_note,
        warnings=warnings,
    )


def resolve_repo_target(
    repo_arg: str, cwd: Path, workspace: Path
) -> RepoTarget:
    """Classify repo arg as a source repo or oe/meta-judo* layer."""
    src_from_arg, meta_from_arg = parse_repo_arg(repo_arg, workspace)
    src_from_cwd, meta_from_cwd = infer_from_cwd(cwd, workspace)

    src_repo = src_from_arg or src_from_cwd
    meta_hint = meta_from_arg or meta_from_cwd

    if src_repo:
        if not is_git_repo(src_repo):
            raise SystemExit(f"ERROR: not a git repo: {src_repo}")
        if meta_hint:
            if not is_git_repo(meta_hint):
                raise SystemExit(f"ERROR: not a git repo: {meta_hint}")
            if not meta_hint.name.startswith("meta-judo"):
                raise SystemExit(
                    f"ERROR: oe repo must be a meta-judo* layer: {meta_hint}"
                )
            layers = [meta_hint]
        else:
            layers = meta_layer_roots(workspace)
        return RepoTarget("source", src_repo, None, layers)

    if meta_hint:
        if not is_git_repo(meta_hint):
            raise SystemExit(f"ERROR: not a git repo: {meta_hint}")
        if not meta_hint.name.startswith("meta-judo"):
            raise SystemExit(
                f"ERROR: oe repo {meta_hint.name!r} is not a meta-judo* layer"
            )
        return RepoTarget("meta_layer", None, meta_hint, [meta_hint])

    raise SystemExit(
        f"ERROR: repo not found under src/ or oe/: {repo_arg!r} "
        "(examples: mqtt-api, src/mqtt-api, meta-judo, "
        "oe/meta-judo-proprietary)"
    )


def resolve_skill_context(
    args: argparse.Namespace, workspace: Path, manifest: Path
) -> SkillContext:
    """Resolve repos and branches used by pre-flight and the three steps."""
    cwd = Path.cwd()
    target = resolve_repo_target(args.repo, cwd, workspace)
    manifest_repo = Path(
        run_git(["rev-parse", "--show-toplevel"], manifest.parent)
    )
    manifest_repo_rel = recipe_display_path(manifest_repo, workspace)

    if target.mode == "meta_layer":
        assert target.meta_repo is not None
        meta_repo = target.meta_repo
        src_branch = source_branch_name(meta_repo)
        return SkillContext(
            workspace=workspace,
            manifest=manifest,
            src_repo=None,
            meta_repo=meta_repo,
            manifest_repo=manifest_repo,
            src_branch=src_branch,
            src_rel="",
            meta_rel=recipe_display_path(meta_repo, workspace),
            manifest_repo_rel=manifest_repo_rel,
            meta_layer_only=True,
        )

    assert target.src_repo is not None
    src_repo = target.src_repo
    recipe = resolve_recipe(
        target.layers, src_repo.name, args.recipe, workspace
    )
    meta_repo = meta_repo_for_recipe(recipe)
    src_branch = source_branch_name(src_repo)
    return SkillContext(
        workspace=workspace,
        manifest=manifest,
        src_repo=src_repo,
        meta_repo=meta_repo,
        manifest_repo=manifest_repo,
        src_branch=src_branch,
        src_rel=recipe_display_path(src_repo, workspace),
        meta_rel=recipe_display_path(meta_repo, workspace),
        manifest_repo_rel=manifest_repo_rel,
        meta_layer_only=False,
    )


# --- recipe ---


def parse_repo_arg(
    repo_arg: str, workspace: Path
) -> tuple[Path | None, Path | None]:
    """Return (src_repo, meta_layer) paths implied by repo_arg."""
    raw = repo_arg.strip().strip("/")
    if not raw:
        raise SystemExit("ERROR: repo name is required")

    if raw.startswith("src/"):
        name = raw[len("src/") :]
        return workspace / "src" / name, None

    if raw.startswith("oe/"):
        name = raw[len("oe/") :]
        return None, workspace / "oe" / name

    src_candidate = workspace / "src" / raw
    oe_candidate = workspace / "oe" / raw

    src_exists = src_candidate.is_dir() and is_git_repo(src_candidate)
    oe_exists = oe_candidate.is_dir() and is_git_repo(oe_candidate)

    if src_exists and oe_exists:
        raise SystemExit(
            f"ERROR: ambiguous repo name {raw!r}; use src/{raw} or oe/{raw}"
        )
    if src_exists:
        return src_candidate, None
    if oe_exists:
        if not raw.startswith("meta-judo"):
            raise SystemExit(
                f"ERROR: oe repo {raw!r} is not a meta-judo* layer"
            )
        return None, oe_candidate

    raise SystemExit(
        f"ERROR: repo not found under src/ or oe/: {raw!r} "
        "(examples: mqtt-api, src/mqtt-api, meta-judo-proprietary, "
        "oe/meta-judo-proprietary)"
    )


def infer_from_cwd(cwd: Path, workspace: Path) -> tuple[Path | None, Path | None]:
    resolved = cwd.resolve()
    try:
        rel = resolved.relative_to(workspace)
    except ValueError:
        return None, None

    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "src":
        src_repo = workspace / "src" / parts[1]
        if is_git_repo(src_repo):
            return src_repo, None

    if len(parts) >= 2 and parts[0] == "oe" and parts[1].startswith("meta-judo"):
        meta_layer = workspace / "oe" / parts[1]
        if is_git_repo(meta_layer):
            return None, meta_layer

    return None, None


def meta_layer_roots(workspace: Path) -> list[Path]:
    oe_dir = workspace / "oe"
    if not oe_dir.is_dir():
        raise SystemExit(f"ERROR: missing oe/ under workspace {workspace}")
    roots = sorted(oe_dir.glob("meta-judo*"))
    if not roots:
        raise SystemExit("ERROR: no oe/meta-judo* layers found")
    return roots


def resolve_repos(
    repo_arg: str, cwd: Path, workspace: Path
) -> tuple[Path, list[Path]]:
    """Resolve a source repo and meta-judo layers for recipe updates."""
    target = resolve_repo_target(repo_arg, cwd, workspace)
    if target.mode != "source" or target.src_repo is None:
        raise SystemExit(
            "ERROR: source repo not resolved; pass a source repo name "
            "(e.g. mqtt-api, src/mqtt-api) or cd to src/<repo>"
        )
    return target.src_repo, target.layers


def recipe_references_repo(content: str, repo_name: str) -> bool:
    needle = f"src/{repo_name}"
    for match in SRC_PATH_RE.finditer(content):
        if match.group(1) == repo_name:
            return True
    return needle in content


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


def is_primary_recipe_for_repo(path: Path, repo_name: str) -> bool:
    """True when the recipe file is the canonical owner for the source repo."""
    stem = path.stem
    if stem in {repo_name, f"{repo_name}_git"}:
        return True
    return path.parent.name == repo_name


def discover_recipes(layers: list[Path], repo_name: str) -> list[Path]:
    matches: list[Path] = []
    for layer in layers:
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


def choose_recipe_match(matches: list[Path], repo_name: str) -> Path:
    """Pick one recipe when several reference the same src path."""
    primary = [p for p in matches if is_primary_recipe_for_repo(p, repo_name)]
    if len(primary) == 1:
        return primary[0]
    if len(matches) == 1:
        return matches[0]
    listing = "\n".join(f"  - {path}" for path in matches)
    raise SystemExit(
        "ERROR: multiple recipes reference "
        f"src/{repo_name}; pass --recipe:\n{listing}"
    )


def read_recipe_pin(
    recipe: Path, repo_name: str, workspace: Path
) -> RecipePin | None:
    """Read the SRCREV pin for src/<repo_name> from one recipe file."""
    try:
        content = recipe.read_text(encoding="utf-8")
    except OSError:
        return None
    if not recipe_references_repo(content, repo_name):
        return None
    targets = find_srcrev_targets(content, repo_name)
    if not targets:
        return None
    var_name = targets[0]
    srcrev = "?"
    definite = False
    for match in SRCREV_LINE_RE.finditer(content):
        if match.group(1) != var_name:
            continue
        srcrev = match.group(3)
        definite = "?=" not in match.group(2)
        break
    return RecipePin(
        path=recipe.resolve(),
        rel=recipe_display_path(recipe, workspace),
        var_name=var_name,
        srcrev=srcrev,
        definite=definite,
    )


def collect_recipe_pins(
    layers: list[Path], repo_name: str, workspace: Path
) -> list[RecipePin]:
    pins: list[RecipePin] = []
    for path in discover_recipes(layers, repo_name):
        pin = read_recipe_pin(path, repo_name, workspace)
        if pin is not None:
            pins.append(pin)
    return pins


def definite_src_pin_mismatches(
    pins: list[RecipePin],
    chosen_recipe: Path,
    target_srcrev: str,
) -> list[str]:
    """Other recipes with SRCREV = that do not match the pin target."""
    chosen = chosen_recipe.resolve()
    lines: list[str] = []
    for pin in pins:
        if not pin.definite:
            continue
        if pin.path == chosen:
            continue
        if pin.srcrev == target_srcrev:
            continue
        lines.append(f"{pin.rel}: {pin.var_name}={pin.srcrev}")
    return lines


def check_definite_src_pin_consistency(
    args: argparse.Namespace,
    workspace: Path,
    repo_name: str,
    chosen_recipe: Path,
    target_srcrev: str,
    primary_old_rev: str,
) -> list[str]:
    """
    Fail when the primary recipe is in sync but other SRCREV = pins lag.

    Recipes that use SRCREV ?= are ignored (intentionally stale defaults).
    """
    cwd = Path.cwd()
    _, layers = resolve_repos(args.repo, cwd, workspace)
    pins = collect_recipe_pins(layers, repo_name, workspace)
    mismatches = definite_src_pin_mismatches(
        pins, chosen_recipe, target_srcrev
    )
    if not mismatches:
        return []

    primary_path = recipe_display_path(chosen_recipe, workspace)
    if primary_old_rev != target_srcrev:
        # This run updates the primary recipe; other definite pins still need
        # their own --recipe pass.
        if args.allow_split_src_pins:
            return [
                "Other definitive SRCREV = pins still differ from source "
                f"HEAD ({target_srcrev}):",
                *[f"  - {line}" for line in mismatches],
            ]
        eprint(
            f"ERROR: other recipes pin src/{repo_name} with SRCREV = but "
            f"this run only updates the primary recipe"
        )
        eprint(f"  Primary: {primary_path}")
        eprint(f"  Source HEAD: {target_srcrev}")
        eprint("")
        for line in mismatches:
            eprint(f"  - {line}")
        eprint("")
        eprint(
            "Update each with --recipe <path>, or pass "
            "--allow-split-src-pins to continue"
        )
        raise SystemExit(1)

    if args.allow_split_src_pins:
        return [
            "Other definitive SRCREV = pins differ from source HEAD "
            f"({target_srcrev}) while the primary recipe is already in "
            "sync:",
            *[f"  - {line}" for line in mismatches],
        ]

    eprint(
        f"ERROR: primary recipe is pinned to source HEAD but other recipes "
        f"use SRCREV = for src/{repo_name} at different SHAs"
    )
    eprint(f"  Primary: {primary_path}")
    eprint(f"  Source HEAD: {target_srcrev}")
    eprint("")
    for line in mismatches:
        eprint(f"  - {line}")
    eprint("")
    eprint(
        "The skill only updates one recipe per source repo (the canonical "
        f"{repo_name}_git.bb when present). Update each stale recipe with "
        "--recipe <path>, or pass --allow-split-src-pins to ignore."
    )
    raise SystemExit(1)


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


def recipe_display_path(recipe: Path, workspace: Path) -> str:
    return workspace_rel(recipe, workspace)


def resolve_recipe(
    layers: list[Path],
    repo_name: str,
    recipe_arg: str | None,
    workspace: Path,
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

    matches = discover_recipes(layers, repo_name)
    layer_hint = layers[0] if len(layers) == 1 else None
    scope = f" under {layer_hint}" if layer_hint else " under oe/meta-judo*"
    if not matches:
        raise SystemExit(
            f"ERROR: no .bb/.inc recipe found for src/{repo_name}{scope}"
        )
    return choose_recipe_match(matches, repo_name)


def source_branch_name(src_repo: Path) -> str:
    branch = run_git(["branch", "--show-current"], src_repo)
    if not branch:
        raise SystemExit(
            "ERROR: source repo is not on a named branch "
            "(detached HEAD); cannot match meta-layer branch"
        )
    return branch


def meta_repo_for_recipe(recipe: Path) -> Path:
    return Path(run_git(["rev-parse", "--show-toplevel"], recipe.parent))


def require_commit_in_source(src_repo: Path, sha: str) -> None:
    """Fail if sha is not a commit in the source repo history."""
    if not sha or sha == "?":
        raise SystemExit(
            "ERROR: existing SRCREV is missing or unreadable; "
            "cannot verify it in source history"
        )
    result = git_try(
        ["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
        src_repo,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"ERROR: existing SRCREV {sha} is not a commit in "
            f"{src_repo} history; fetch or check the recipe pin"
        )
    _ = result.stdout.strip() or sha


def commit_recipe(recipe: Path, issue: str, recipe_name: str) -> str:
    meta_repo = Path(run_git(["rev-parse", "--show-toplevel"], recipe.parent))
    rel = str(recipe.relative_to(meta_repo))
    message = f"{issue}:{recipe_name} Update SRCREV"
    return commit_or_amend(
        meta_repo, rel, message, is_srcrev_only_diff, quiet=True
    )


def update_recipe(
    args: argparse.Namespace,
    workspace: Path,
    dry_run: bool,
    preflight: PreflightResult | None = None,
) -> RecipeResult:
    cwd = Path.cwd()
    src_repo, layers = resolve_repos(args.repo, cwd, workspace)
    repo_name = src_repo.name
    srcrev = args.srcrev or run_git(["rev-parse", "HEAD"], src_repo)
    src_branch = source_branch_name(src_repo)

    recipe = resolve_recipe(layers, repo_name, args.recipe, workspace)
    recipe_path = recipe_display_path(recipe, workspace)
    meta_repo = meta_repo_for_recipe(recipe)
    meta_rel = recipe_display_path(meta_repo, workspace)
    src_rel = recipe_display_path(src_repo, workspace)
    pushes = [
        PushHint(rel=src_rel, repo=src_repo, branch=src_branch),
        PushHint(rel=meta_rel, repo=meta_repo, branch=src_branch),
    ]

    if dry_run and preflight:
        meta_head = preflight.meta_planned_head
        meta_note = preflight.meta_note
    else:
        meta_head = run_git(["rev-parse", "HEAD"], meta_repo)
        if current_branch(meta_repo) == src_branch:
            meta_note = "already on matching branch"
        else:
            meta_note = f"on {current_branch(meta_repo)}"
    if not dry_run and not recipe.is_file():
        raise SystemExit(
            f"ERROR: recipe missing after checkout {src_branch}: "
            f"{recipe_path}"
        )
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

    require_commit_in_source(src_repo, old_rev)

    result = RecipeResult(
        src_rel=src_rel,
        src_branch=src_branch,
        srcrev=srcrev,
        recipe_path=recipe_path,
        meta_rel=meta_rel,
        meta_head=meta_head,
        meta_note=meta_note,
        var_name=var_name,
        old_rev=old_rev,
        changed=old_rev != srcrev,
        outcome="",
        push_hints=pushes,
        issue=args.issue or extract_issue(recipe.parent, src_repo),
    )

    if old_rev == srcrev:
        result.outcome = (
            "SRCREV already matches source HEAD — no recipe commit "
            + ("would be made" if dry_run else "made")
        )
        return result

    updated, changed = replace_srcrev(content, var_name, srcrev)
    if not changed:
        raise SystemExit(
            f"ERROR: failed to update {var_name} in {recipe_path}"
        )

    if dry_run:
        result.outcome = (
            f"would update {var_name} {old_rev} -> {srcrev} and commit"
        )
        return result

    recipe.write_text(updated, encoding="utf-8")

    if args.no_commit:
        meta_head = run_git(["rev-parse", "HEAD"], meta_repo)
        result.meta_head = meta_head
        result.outcome = f"updated {var_name}; did not commit"
        return result

    if not result.issue:
        raise SystemExit(
            "ERROR: could not parse issue id from branch name; pass --issue"
        )

    kind = commit_recipe(recipe, result.issue, recipe_display_name(recipe))
    meta_head = run_git(["rev-parse", "HEAD"], meta_repo)
    result.meta_head = meta_head
    result.outcome = f"{kind} {var_name} {old_rev} -> {srcrev}"
    return result


# --- manifest ---


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


def manifest_self_revision_target(branch: str) -> str:
    """Return the default.xml revision for manifest-judo on this branch."""
    return "main" if branch == "main" else branch


def sync_manifest_self_pin(
    workspace: Path,
    manifest: Path,
    branch: str,
    dry_run: bool,
) -> ManifestPinResult:
    """Pin manifest-judo to the workspace branch (not main's HEAD)."""
    if not manifest.is_file():
        raise SystemExit(f"ERROR: manifest not found: {manifest}")

    manifest_text = manifest.read_text(encoding="utf-8")
    matches = find_project_matches(
        manifest_text, MANIFEST_JUDO_NAME, MANIFEST_JUDO_PATH
    )
    if not matches:
        raise SystemExit(
            f"ERROR: no <project> found in {manifest} for "
            f"name={MANIFEST_JUDO_NAME!r} path={MANIFEST_JUDO_PATH!r}"
        )
    if len(matches) > 1:
        raise SystemExit(
            "ERROR: multiple manifest-judo projects found in "
            f"{manifest}"
        )

    line_index, project_name, project_path, old_revision = matches[0]
    new_revision = manifest_self_revision_target(branch)
    manifest_rel = workspace_rel(manifest, workspace)

    manifest_repo = Path(
        run_git(["rev-parse", "--show-toplevel"], manifest.parent)
    )
    manifest_repo_rel = workspace_rel(manifest_repo, workspace)
    manifest_branch = run_git(["branch", "--show-current"], manifest_repo)
    pushes: list[PushHint] = []
    if manifest_branch:
        pushes.append(
            PushHint(
                rel=manifest_repo_rel,
                repo=manifest_repo,
                branch=manifest_branch,
            )
        )

    already = old_revision == new_revision
    if already:
        outcome = (
            f"{manifest_rel} manifest-judo revision already "
            f"matches branch {branch} — no change"
        )
    elif dry_run:
        outcome = (
            f"would update {manifest_rel} manifest-judo revision "
            f"{old_revision} -> {new_revision}"
        )
    else:
        outcome = (
            f"updated {manifest_rel} manifest-judo revision "
            f"{old_revision} -> {new_revision}"
        )

    result = ManifestPinResult(
        project_name=project_name,
        project_path=project_path,
        old_revision=old_revision,
        new_revision=new_revision,
        changed=not already,
        outcome=outcome,
        push_hints=pushes,
        manifest_rel=str(manifest_rel),
    )

    if already:
        return result

    lines = manifest_text.splitlines(keepends=True)
    updated_line = merge_revision_into_line(
        lines[line_index].rstrip("\r\n"),
        new_revision,
    )
    if not updated_line.endswith("\n"):
        updated_line += "\n"
    lines[line_index] = updated_line
    updated_text = "".join(lines)

    if dry_run:
        return result

    manifest.write_text(updated_text, encoding="utf-8")
    validate_manifest(manifest)
    return result


def update_manifest_pin(
    workspace: Path,
    manifest: Path,
    project: str,
    revision: str | None,
    dry_run: bool,
) -> ManifestPinResult:
    cwd = Path.cwd()
    if not manifest.is_file():
        raise SystemExit(f"ERROR: manifest not found: {manifest}")

    name_hint, path_hint = normalize_project_arg(project)
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
    new_revision = revision or run_git(["rev-parse", "HEAD"], src_repo)
    manifest_rel = workspace_rel(manifest, workspace)

    manifest_repo = Path(
        run_git(["rev-parse", "--show-toplevel"], manifest.parent)
    )
    manifest_repo_rel = workspace_rel(manifest_repo, workspace)
    manifest_branch = run_git(["branch", "--show-current"], manifest_repo)
    pushes: list[PushHint] = []
    if manifest_branch:
        pushes.append(
            PushHint(
                rel=manifest_repo_rel,
                repo=manifest_repo,
                branch=manifest_branch,
            )
        )

    already = old_revision == new_revision
    if already:
        outcome = (
            f"{manifest_rel} revision already matches "
            f"{project_path} HEAD — no change"
        )
    elif dry_run:
        outcome = (
            f"would update {manifest_rel} revision "
            f"{old_revision} -> {new_revision}"
        )
    else:
        outcome = (
            f"updated {manifest_rel} revision "
            f"{old_revision} -> {new_revision}"
        )

    result = ManifestPinResult(
        project_name=project_name,
        project_path=project_path,
        old_revision=old_revision,
        new_revision=new_revision,
        changed=not already,
        outcome=outcome,
        push_hints=pushes,
        manifest_rel=str(manifest_rel),
    )

    if already:
        return result

    lines = manifest_text.splitlines(keepends=True)
    updated_line = merge_revision_into_line(
        lines[line_index].rstrip("\r\n"),
        new_revision,
    )
    if not updated_line.endswith("\n"):
        updated_line += "\n"
    lines[line_index] = updated_line
    updated_text = "".join(lines)

    if dry_run:
        return result

    manifest.write_text(updated_text, encoding="utf-8")
    validate_manifest(manifest)
    return result


# --- orchestrator ---


def print_pushes(hints: list[PushHint]) -> None:
    """Print suggested push commands. Never run git push."""
    if not hints:
        return
    print("Push hints (informational only — not executed)")
    print()
    warnings: list[str] = []
    for hint in hints:
        if push_needed(hint.repo, hint.branch):
            print(f"  • {hint.rel}:")
            print(f"    git push origin {hint.branch}")
            for warning in push_branch_warnings(hint.repo, hint.branch):
                warnings.append(f"{hint.rel}: {warning}")
        else:
            print(f"  • {hint.rel}: remote already in sync")
    if warnings:
        print()
        print("Push warnings (local vs origin; informational only)")
        print()
        for warning in warnings:
            print(f"  • {warning}")
    print()


def print_preflight(preflight: PreflightResult) -> None:
    print("Pre-flight — branch alignment")
    print()
    for warning in preflight.warnings:
        print(f"  • Warning: {warning}")
    if preflight.warnings:
        print()
    for line in preflight.lines:
        print(
            f"  • {line.label}: {line.rel} on {line.branch} ({line.note})"
        )
    print()


def print_step(title: str, bullets: list[str]) -> None:
    print(title)
    print()
    for item in bullets:
        print(f"  • {item}")
    print()


def print_manifest_self_step(self_pin: ManifestPinResult) -> None:
    outcome = self_pin.outcome
    if not self_pin.changed:
        outcome = (
            "default.xml manifest-judo revision already matches "
            "workspace branch — no change"
        )
    print_step(
        "Step 4 — Manifest self project (manifest-judo)",
        [
            (
                f"Project: {self_pin.project_name} → "
                f"{self_pin.project_path} revision "
                f"{self_pin.new_revision}"
            ),
            f"Outcome: {outcome}",
        ],
    )


def print_meta_layer_report(
    ctx: SkillContext,
    recipe_pin: ManifestPinResult,
    self_pin: ManifestPinResult,
    dry_run: bool,
    applied: list[str] | None = None,
    incomplete: bool = False,
) -> None:
    print_step(
        "Step 1 — Recipe SRCREV",
        [
            "Skipped — meta-layer-only pin (no source repo / SRCREV)",
        ],
    )
    print_step(
        "Step 2 — Manifest source project",
        [
            "Skipped — meta-layer-only pin",
        ],
    )
    recipe_outcome = recipe_pin.outcome
    if not recipe_pin.changed:
        recipe_outcome = (
            "default.xml revision already matches meta-layer HEAD — no change"
        )
    print_step(
        "Step 3 — Manifest meta-layer project",
        [
            (
                f"Project: {recipe_pin.project_name} → "
                f"{recipe_pin.project_path} at {recipe_pin.new_revision}"
            ),
            f"Outcome: {recipe_outcome}",
        ],
    )
    print_manifest_self_step(self_pin)
    print()
    print("Final result")
    print()
    if incomplete:
        print("  RESULT: apply incomplete")
        print()
        return
    if dry_run:
        print("  RESULT: dry-run complete for meta-layer manifest pin")
        print()
        if not recipe_pin.changed and not self_pin.changed:
            print(
                "  Everything is already in sync, so an apply run would "
                "make no commits or file changes."
            )
            print()
        else:
            print(
                "  An apply run would use one default.xml commit "
                "(amend if HEAD only changed revision attrs)."
            )
            print()
        return
    targets = " and ".join(applied or [])
    print(f"  RESULT: apply complete ({targets})")
    print()


def print_report(
    recipe: RecipeResult,
    source_pin: ManifestPinResult,
    recipe_pin: ManifestPinResult,
    self_pin: ManifestPinResult,
    dry_run: bool,
    applied: list[str] | None = None,
    incomplete: bool = False,
) -> None:
    step1_bullets = [
        (
            f"Source: {recipe.src_rel} on {recipe.src_branch} "
            f"at {recipe.srcrev}"
        ),
        f"Recipe: {recipe.recipe_path}",
        f"Meta layer: {recipe.meta_rel} ({recipe.meta_note})",
        f"Outcome: {recipe.outcome}",
    ]
    if recipe.split_pin_mismatches:
        step1_bullets.append(
            "Split SRCREV pins (see pre-flight warnings)"
        )
    print_step(
        "Step 1 — Recipe SRCREV",
        step1_bullets,
    )
    source_outcome = source_pin.outcome
    if not source_pin.changed:
        source_outcome = (
            "default.xml revision already matches source HEAD — no change"
        )
    print_step(
        "Step 2 — Manifest source project",
        [
            f"Project: {source_pin.project_name} → {source_pin.project_path}",
            f"Outcome: {source_outcome}",
        ],
    )
    recipe_outcome = recipe_pin.outcome
    if not recipe_pin.changed:
        recipe_outcome = (
            "default.xml revision already matches meta-layer HEAD — no change"
        )
    print_step(
        "Step 3 — Manifest recipe project",
        [
            (
                f"Project: {recipe_pin.project_name} → "
                f"{recipe_pin.project_path} at {recipe_pin.new_revision}"
            ),
            f"Outcome: {recipe_outcome}",
        ],
    )
    print_manifest_self_step(self_pin)
    print()
    print("Final result")
    print()
    if incomplete:
        print("  RESULT: apply incomplete")
        print()
        return
    if dry_run:
        print("  RESULT: dry-run complete for all requested steps")
        print()
        if (
            not recipe.changed
            and not source_pin.changed
            and not recipe_pin.changed
            and not self_pin.changed
            and not recipe.split_pin_mismatches
        ):
            print(
                "  Everything is already in sync, so an apply run would "
                "make no commits or file changes."
            )
            print()
        elif recipe.split_pin_mismatches and not (
            recipe.changed
            or source_pin.changed
            or recipe_pin.changed
            or self_pin.changed
        ):
            print(
                "  Primary recipe and manifest pins are in sync, but other "
                "SRCREV = recipes still need updates (see pre-flight "
                "warnings)."
            )
            print()
        elif (
            source_pin.changed
            or recipe_pin.changed
            or self_pin.changed
        ):
            print(
                "  An apply run would use one default.xml commit "
                "(amend if HEAD only changed revision attrs)."
            )
            print()
        return
    targets = " and ".join(applied or [])
    print(f"  RESULT: apply complete ({targets})")
    print()


def collect_push_hints(*groups: list[PushHint]) -> list[PushHint]:
    seen: set[tuple[str, str]] = set()
    hints: list[PushHint] = []
    for group in groups:
        for hint in group:
            key = (hint.rel, hint.branch)
            if key not in seen:
                seen.add(key)
                hints.append(hint)
    return hints


def issue_for_manifest(
    args: argparse.Namespace, recipe: RecipeResult
) -> str:
    if args.issue:
        return args.issue
    found = ISSUE_RE.search(recipe.src_branch)
    if found:
        return found.group(0)
    if recipe.issue:
        return recipe.issue
    raise SystemExit(
        "ERROR: could not parse issue id from branch name; pass --issue"
    )


def issue_for_meta_layer(
    args: argparse.Namespace, ctx: SkillContext
) -> str:
    if args.issue:
        return args.issue
    found = ISSUE_RE.search(ctx.src_branch)
    if found:
        return found.group(0)
    extracted = extract_issue(ctx.meta_repo)
    if extracted:
        return extracted
    raise SystemExit(
        "ERROR: could not parse issue id from branch name; pass --issue"
    )


MANIFEST_BODY_FIELD_ORDER = ("name", "path", "revision", "recipe", "SRCREV")


@dataclass
class ManifestCommitSection:
    header: str
    fields: dict[str, str]

    @property
    def key(self) -> tuple[str, str]:
        return (self.header, self.fields.get("name", ""))


def parse_manifest_commit_body(body: str) -> list[ManifestCommitSection]:
    """Parse a manifest commit body into project sections."""
    sections: list[ManifestCommitSection] = []
    current_header = ""
    current_fields: dict[str, str] = {}

    def flush() -> None:
        nonlocal current_header, current_fields
        if current_header:
            sections.append(
                ManifestCommitSection(current_header, dict(current_fields))
            )
        current_header = ""
        current_fields = {}

    for line in body.splitlines():
        if line.endswith(":") and not line.startswith(" "):
            flush()
            current_header = line
            continue
        if not current_header or not line.startswith("  "):
            continue
        stripped = line.strip()
        if ": " not in stripped:
            continue
        key, value = stripped.split(": ", 1)
        current_fields[key] = value
    flush()
    return sections


def append_manifest_path(existing: str, new_path: str) -> str:
    """Append a path to an existing comma-separated path value."""
    paths = [part.strip() for part in existing.split(",") if part.strip()]
    if new_path not in paths:
        paths.append(new_path)
    return ", ".join(paths)


def render_manifest_commit_body(sections: list[ManifestCommitSection]) -> str:
    blocks: list[str] = []
    for section in sections:
        lines = [section.header]
        rendered: set[str] = set()
        for key in MANIFEST_BODY_FIELD_ORDER:
            if key not in section.fields:
                continue
            lines.append(f"  {key}: {section.fields[key]}")
            rendered.add(key)
        for key, value in section.fields.items():
            if key in rendered:
                continue
            lines.append(f"  {key}: {value}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def merge_manifest_commit_bodies(existing: str, new: str) -> str:
    """Merge manifest commit bodies, appending paths instead of replacing."""
    existing = existing.strip()
    new = new.strip()
    if not existing:
        return new
    if not new:
        return existing

    merged: dict[tuple[str, str], ManifestCommitSection] = {}
    order: list[tuple[str, str]] = []

    for section in parse_manifest_commit_body(existing):
        merged[section.key] = ManifestCommitSection(
            section.header, dict(section.fields)
        )
        order.append(section.key)

    for section in parse_manifest_commit_body(new):
        key = section.key
        if key in merged:
            target = merged[key]
            for field, value in section.fields.items():
                if field == "path":
                    current = target.fields.get("path", "")
                    target.fields["path"] = append_manifest_path(
                        current, value
                    )
                else:
                    target.fields[field] = value
            continue
        merged[key] = ManifestCommitSection(
            section.header, dict(section.fields)
        )
        order.append(key)

    return render_manifest_commit_body([merged[key] for key in order])


def with_amended_manifest_body(repo: Path, message: str) -> str:
    """When amending a revision-only manifest commit, merge commit bodies."""
    subject, sep, new_body = message.partition("\n\n")
    if not sep or not head_is_kind(repo, is_revision_only_diff):
        return message
    existing = run_git(["log", "-1", "--format=%B"], repo)
    _, _, existing_body = existing.partition("\n\n")
    merged_body = merge_manifest_commit_bodies(existing_body, new_body)
    return f"{subject}\n\n{merged_body}"


def manifest_self_body_lines(self_pin: ManifestPinResult) -> list[str]:
    if not self_pin.changed:
        return []
    return [
        "Manifest self project:",
        f"  name: {self_pin.project_name}",
        f"  path: {self_pin.project_path}",
        (
            f"  revision: {self_pin.old_revision} -> "
            f"{self_pin.new_revision}"
        ),
    ]


def manifest_commit_message_meta_layer(
    issue: str,
    branch: str,
    recipe_pin: ManifestPinResult,
    self_pin: ManifestPinResult,
) -> str:
    """Workspace commit for oe/meta-judo* manifest-only pins."""
    subject = f"{issue}:{branch} Update SRCREV"
    lines = [
        "Recipe project:",
        f"  name: {recipe_pin.project_name}",
        f"  path: {recipe_pin.project_path}",
        (
            f"  revision: {recipe_pin.old_revision} -> "
            f"{recipe_pin.new_revision}"
        ),
    ]
    self_lines = manifest_self_body_lines(self_pin)
    if self_lines:
        lines.extend([""] + self_lines)
    body = "\n".join(lines)
    return f"{subject}\n\n{body}"


def manifest_commit_message(
    issue: str,
    branch: str,
    recipe: RecipeResult,
    pins: list[ManifestPinResult],
    self_pin: ManifestPinResult,
) -> str:
    """Workspace commit: subject uses branch; body lists both projects."""
    subject = f"{issue}:{branch} Update SRCREV"
    lines: list[str] = []
    source = pins[0] if pins else None
    if source and source.project_path.startswith("src/"):
        lines.extend(
            [
                "Source project:",
                f"  name: {source.project_name}",
                f"  path: {source.project_path}",
                f"  revision: {source.old_revision} -> {source.new_revision}",
            ]
        )
    recipe_pin = pins[1] if len(pins) > 1 else (pins[0] if pins else None)
    if recipe_pin or recipe.recipe_path or recipe.var_name:
        if lines:
            lines.append("")
        lines.append("Recipe project:")
        if recipe_pin:
            lines.extend(
                [
                    f"  name: {recipe_pin.project_name}",
                    f"  path: {recipe_pin.project_path}",
                    f"  revision: {recipe_pin.old_revision} -> "
                    f"{recipe_pin.new_revision}",
                ]
            )
        if recipe.recipe_path:
            lines.append(f"  recipe: {recipe.recipe_path}")
        if recipe.var_name:
            lines.append(
                f"  {recipe.var_name}: {recipe.old_rev} -> {recipe.srcrev}"
            )
    self_lines = manifest_self_body_lines(self_pin)
    if self_lines:
        if lines:
            lines.append("")
        lines.extend(self_lines)
    body = "\n".join(lines).rstrip()
    if body:
        return f"{subject}\n\n{body}"
    return subject


def commit_meta_layer_manifest(
    args: argparse.Namespace,
    workspace: Path,
    ctx: SkillContext,
    recipe_pin: ManifestPinResult,
    self_pin: ManifestPinResult,
) -> None:
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
        return
    issue = issue_for_meta_layer(args, ctx)
    message = manifest_commit_message_meta_layer(
        issue, ctx.src_branch, recipe_pin, self_pin
    )
    message = with_amended_manifest_body(repo, message)
    commit_or_amend(
        repo, rel, message, is_revision_only_diff, quiet=True
    )


def commit_manifest_bundle(
    args: argparse.Namespace,
    workspace: Path,
    recipe: RecipeResult,
    pins: list[ManifestPinResult],
    self_pin: ManifestPinResult,
) -> None:
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
        return
    issue = issue_for_manifest(args, recipe)
    message = manifest_commit_message(
        issue, recipe.src_branch, recipe, pins, self_pin
    )
    message = with_amended_manifest_body(repo, message)
    commit_or_amend(
        repo, rel, message, is_revision_only_diff, quiet=True
    )


def repo_branch_info(
    repo_arg: str, cwd: Path, workspace: Path
) -> tuple[str, str]:
    """Return (display path, current branch) for a repo argument."""
    target = resolve_repo_target(repo_arg, cwd, workspace)
    if target.mode == "meta_layer":
        assert target.meta_repo is not None
        repo = target.meta_repo
    else:
        assert target.src_repo is not None
        repo = target.src_repo
    branch = current_branch(repo)
    rel = recipe_display_path(repo, workspace)
    if not branch:
        raise SystemExit(
            f"ERROR: {rel} is on detached HEAD; "
            "check out a named branch first"
        )
    return rel, branch


def run_multi_repo_branch_preflight(
    repos: list[str],
    cwd: Path,
    workspace: Path,
    args: argparse.Namespace,
) -> None:
    """Require every repo arg to be on the same branch name."""
    entries: list[tuple[str, str, str]] = []
    for repo_arg in repos:
        rel, branch = repo_branch_info(repo_arg, cwd, workspace)
        entries.append((repo_arg, rel, branch))

    branches = {branch for _, _, branch in entries}
    if len(branches) == 1:
        branch = branches.pop()
        print("Pre-flight — multi-repo branch alignment")
        print()
        for repo_arg, rel, branch_name in entries:
            print(f"  • {repo_arg} ({rel}): {branch_name}")
        print()
        print(f"  All {len(repos)} repos on branch {branch}.")
        print()
        return

    if args.continue_preflight:
        listing = ", ".join(sorted(branches))
        print("Pre-flight — multi-repo branch alignment")
        print()
        for repo_arg, rel, branch_name in entries:
            print(f"  • {repo_arg} ({rel}): {branch_name}")
        print()
        print(
            f"  Warning: repos are on different branches ({listing}); "
            "continuing due to --continue-preflight."
        )
        print()
        return

    preflight_exit(
        [
            "The following repos are not on the same branch:",
            *[
                f"  - {repo_arg} ({rel}): {branch}"
                for repo_arg, rel, branch in entries
            ],
            (
                "Check out the same branch in each repo, then re-run. "
                "Or pass --continue-preflight to proceed anyway."
            ),
        ]
    )


def strip_repo_list_prefix(text: str) -> str:
    """Remove optional skill prefixes from a repo-list token."""
    lowered = text.lower()
    if lowered.startswith("for each of "):
        return text[len("for each of ") :].strip()
    if lowered.startswith("in order:"):
        return text[len("in order:") :].strip()
    if lowered.startswith("in order "):
        return text[len("in order ") :].strip()
    return text


def parse_repo_list(raw_repos: list[str]) -> list[str]:
    """Normalize repo CLI args; strip skill prefixes and commas."""
    repos: list[str] = []
    for raw in raw_repos:
        text = strip_repo_list_prefix(raw.strip())
        if not text:
            continue
        for part in text.replace(",", " ").split():
            token = part.strip()
            if token:
                repos.append(token)
    if not repos:
        raise SystemExit("ERROR: repo name is required")
    return repos


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="update_src_rev",
        description=(
            "Update recipe SRCREV and default.xml pins for src/<repo>, or "
            "pin oe/meta-judo* HEAD in default.xml only. Pass one or more "
            "repo names to run the skill on each."
        ),
    )
    parser.add_argument(
        "repos",
        nargs="+",
        metavar="repo",
        help=(
            "One or more repo names or paths. src/<name> runs SRCREV plus "
            "manifest pins; oe/meta-judo* pins the layer HEAD in "
            "default.xml only. Multiple repos run once per repo."
        ),
    )
    parser.add_argument(
        "--workspace",
        help="Repo workspace root (default: auto-detect)",
    )
    parser.add_argument(
        "--recipe",
        help="Recipe .bb/.inc path override",
    )
    parser.add_argument(
        "--manifest",
        help="Manifest path override",
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
            "Create a new meta-layer or workspace branch from the current "
            "checkout instead of main (default: False)"
        ),
    )
    parser.add_argument(
        "--recreate-branch",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "When an existing target branch diverges from the current "
            "checkout, recreate it from the current branch instead of "
            "checking out the stale ref (default: False)"
        ),
    )
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help=(
            "Continue when the source repo has uncommitted changes "
            "(pins current HEAD)"
        ),
    )
    parser.add_argument(
        "--fix-preflight",
        action="store_true",
        help=(
            "Fetch and fast-forward local main when behind origin/main "
            "(not when main has diverged), and rename branches to "
            "replace underscores with hyphens"
        ),
    )
    parser.add_argument(
        "--continue-preflight",
        action="store_true",
        help="Continue despite preflight issues without changing them",
    )
    parser.add_argument(
        "--allow-split-src-pins",
        action="store_true",
        help=(
            "Allow other recipes with SRCREV = for the same src/<repo> to "
            "differ from source HEAD (default: error)"
        ),
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Dry-run only; do not write or commit",
    )
    args = parser.parse_args()
    if args.fix_preflight and args.continue_preflight:
        parser.error(
            "--fix-preflight and --continue-preflight are mutually exclusive"
        )
    args.repos = parse_repo_list(args.repos)
    return args


def print_repo_banner(repo_name: str, index: int, total: int) -> None:
    if total <= 1:
        return
    print(f"Repository {index} of {total}: {repo_name}")
    print()


def process_meta_layer_repo(
    ctx: SkillContext,
    args: argparse.Namespace,
    workspace: Path,
    manifest: Path,
) -> int:
    """Pin oe/meta-judo* HEAD in default.xml only."""
    preflight = run_preflight(ctx, args, dry_run=True)
    meta_head = preflight.meta_planned_head or run_git(
        ["rev-parse", "HEAD"], ctx.meta_repo
    )
    recipe_pin = update_manifest_pin(
        workspace,
        manifest,
        ctx.meta_rel,
        meta_head,
        dry_run=True,
    )
    self_pin = sync_manifest_self_pin(
        workspace, manifest, ctx.src_branch, dry_run=True
    )
    push_hints = collect_push_hints(
        [
            PushHint(
                rel=ctx.meta_rel,
                repo=ctx.meta_repo,
                branch=ctx.src_branch,
            )
        ],
        recipe_pin.push_hints,
        self_pin.push_hints,
    )

    if args.dry_run:
        print_preflight(preflight)
        print_meta_layer_report(
            ctx, recipe_pin, self_pin, dry_run=True
        )
        print_pushes(push_hints)
        return 0

    run_preflight(ctx, args, dry_run=False)
    preflight = run_preflight(ctx, args, dry_run=True)
    meta_head = run_git(["rev-parse", "HEAD"], ctx.meta_repo)

    applied: list[str] = []
    try:
        recipe_pin = update_manifest_pin(
            workspace,
            manifest,
            ctx.meta_rel,
            meta_head,
            dry_run=False,
        )
        applied.append("manifest meta-layer project")
        self_pin = sync_manifest_self_pin(
            workspace, manifest, ctx.src_branch, dry_run=False
        )
        applied.append("manifest self project")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if isinstance(exc.code, str) and exc.code:
            eprint(exc.code)
            code = 1
        eprint("ERROR: apply failed")
        print_meta_layer_report(
            ctx,
            recipe_pin,
            self_pin,
            dry_run=False,
            applied=applied,
            incomplete=True,
        )
        print_pushes(push_hints)
        return code if code else 1

    push_hints = collect_push_hints(
        [
            PushHint(
                rel=ctx.meta_rel,
                repo=ctx.meta_repo,
                branch=ctx.src_branch,
            )
        ],
        recipe_pin.push_hints,
        self_pin.push_hints,
    )

    if not args.no_commit:
        commit_meta_layer_manifest(
            args, workspace, ctx, recipe_pin, self_pin
        )
        applied.append("manifest commit")

    print_preflight(preflight)
    print_meta_layer_report(
        ctx, recipe_pin, self_pin, dry_run=False, applied=applied
    )
    print_pushes(push_hints)
    return 0


def process_repo(
    repo_name: str,
    args: argparse.Namespace,
    workspace: Path,
    manifest: Path,
) -> int:
    """Run the full skill (dry-run gate, then apply) for one repo arg."""
    args.repo = repo_name
    ctx = resolve_skill_context(args, workspace, manifest)
    if ctx.meta_layer_only:
        return process_meta_layer_repo(ctx, args, workspace, manifest)

    preflight = run_preflight(ctx, args, dry_run=True)

    recipe = update_recipe(
        args, workspace, dry_run=True, preflight=preflight
    )
    chosen_recipe = (workspace / recipe.recipe_path).resolve()
    src_repo, _ = resolve_repos(args.repo, Path.cwd(), workspace)
    split_notes = check_definite_src_pin_consistency(
        args,
        workspace,
        src_repo.name,
        chosen_recipe,
        recipe.srcrev,
        recipe.old_rev,
    )
    recipe.split_pin_mismatches = split_notes
    if split_notes:
        preflight.warnings.extend(split_notes)
    source_pin = update_manifest_pin(
        workspace,
        manifest,
        repo_name,
        args.srcrev,
        dry_run=True,
    )
    recipe_pin = update_manifest_pin(
        workspace,
        manifest,
        recipe.meta_rel,
        recipe.meta_head,
        dry_run=True,
    )
    self_pin = sync_manifest_self_pin(
        workspace, manifest, recipe.src_branch, dry_run=True
    )
    pins = [source_pin, recipe_pin]
    push_hints = collect_push_hints(
        recipe.push_hints,
        source_pin.push_hints,
        recipe_pin.push_hints,
        self_pin.push_hints,
    )

    if args.dry_run:
        print_preflight(preflight)
        print_report(
            recipe, source_pin, recipe_pin, self_pin, dry_run=True
        )
        print_pushes(push_hints)
        return 0

    run_preflight(ctx, args, dry_run=False)
    preflight = run_preflight(ctx, args, dry_run=True)

    applied: list[str] = []
    try:
        recipe = update_recipe(args, workspace, dry_run=False)
        applied.append("recipe SRCREV")
        source_pin = update_manifest_pin(
            workspace,
            manifest,
            repo_name,
            args.srcrev,
            dry_run=False,
        )
        applied.append("manifest source project")
        recipe_pin = update_manifest_pin(
            workspace,
            manifest,
            recipe.meta_rel,
            recipe.meta_head,
            dry_run=False,
        )
        applied.append("manifest recipe project")
        self_pin = sync_manifest_self_pin(
            workspace, manifest, recipe.src_branch, dry_run=False
        )
        applied.append("manifest self project")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if isinstance(exc.code, str) and exc.code:
            eprint(exc.code)
            code = 1
        eprint("ERROR: apply failed")
        if applied:
            eprint(
                "WARNING: partial apply; earlier steps may have "
                "committed: " + ", ".join(applied)
            )
        print_report(
            recipe,
            source_pin,
            recipe_pin,
            self_pin,
            dry_run=False,
            applied=applied,
            incomplete=True,
        )
        print_pushes(push_hints)
        return code if code else 1

    pins = [source_pin, recipe_pin]
    push_hints = collect_push_hints(
        recipe.push_hints,
        source_pin.push_hints,
        recipe_pin.push_hints,
        self_pin.push_hints,
    )

    if not args.no_commit:
        commit_manifest_bundle(args, workspace, recipe, pins, self_pin)
        applied.append("manifest commit")

    print_preflight(preflight)
    print_report(
        recipe,
        source_pin,
        recipe_pin,
        self_pin,
        dry_run=False,
        applied=applied,
    )
    print_pushes(push_hints)
    return 0


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

    repos = args.repos
    if len(repos) > 1:
        run_multi_repo_branch_preflight(repos, cwd, workspace, args)

    exit_code = 0
    for index, repo_name in enumerate(repos, start=1):
        if index > 1:
            print()
        print_repo_banner(repo_name, index, len(repos))
        try:
            code = process_repo(repo_name, args, workspace, manifest)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            if isinstance(exc.code, str) and exc.code:
                eprint(exc.code)
                code = 1
        if code:
            exit_code = code
            if len(repos) > 1:
                eprint(
                    f"ERROR: stopped after failure on {repo_name} "
                    f"({index} of {len(repos)})"
                )
            break

    if len(repos) > 1 and exit_code == 0:
        print()
        print("Final result")
        print()
        print(
            f"  RESULT: apply complete for all {len(repos)} repositories"
            if not args.dry_run
            else (
                f"  RESULT: dry-run complete for all {len(repos)} "
                "repositories"
            )
        )
        print()

    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        eprint(f"ERROR: git command failed: {' '.join(exc.cmd)}")
        if exc.stderr:
            eprint(exc.stderr.strip())
        raise SystemExit(1) from exc
