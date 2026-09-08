#!/usr/bin/env python3
"""
Update SRCREV in a Yocto recipe (.bb or .inc) from a source repo HEAD.

Recipes always live under oe/meta-judo*; the source repo whose HEAD is pinned
is currently always under src/<name> (matched via SRC_URI/EXTERNALSRC).

Checks out (or creates) a meta-layer branch with the same name as the source
repo branch before writing SRCREV and committing. New branches start from
origin/main (or main) unless --base-existing is set. Never runs git push.

The required repo argument names either the source repo (HEAD source) or an
oe/meta-judo* meta layer (recipe search and commit target). The other side is
inferred from cwd when possible.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from skill_git import commit_or_amend, is_srcrev_only_diff

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


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


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


def resolve_repos(
    repo_arg: str, cwd: Path, workspace: Path
) -> tuple[Path, list[Path]]:
    src_from_arg, meta_from_arg = parse_repo_arg(repo_arg, workspace)
    src_from_cwd, meta_from_cwd = infer_from_cwd(cwd, workspace)

    src_repo = src_from_arg or src_from_cwd
    meta_layer = meta_from_arg or meta_from_cwd

    if not src_repo:
        raise SystemExit(
            "ERROR: source repo not resolved; pass a source repo name "
            "(e.g. mqtt-api, src/mqtt-api) or cd to src/<repo>"
        )
    if not is_git_repo(src_repo):
        raise SystemExit(f"ERROR: not a git repo: {src_repo}")

    if meta_layer:
        if not is_git_repo(meta_layer):
            raise SystemExit(f"ERROR: not a git repo: {meta_layer}")
        if not meta_layer.name.startswith("meta-judo"):
            raise SystemExit(
                f"ERROR: oe repo must be a meta-judo* layer: {meta_layer}"
            )
        layers = [meta_layer]
    else:
        layers = meta_layer_roots(workspace)

    return src_repo, layers


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


def recipe_display_path(recipe: Path, workspace: Path) -> str:
    resolved = recipe.resolve()
    try:
        return str(resolved.relative_to(workspace.resolve()))
    except ValueError:
        return str(resolved)


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
    if len(matches) > 1:
        listing = "\n".join(f"  - {path}" for path in matches)
        raise SystemExit(
            "ERROR: multiple recipes reference "
            f"src/{repo_name}; pass --recipe:\n{listing}"
        )
    return matches[0]


def git_ref_exists(repo: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


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


def recipe_branch_start_point(
    meta_repo: Path, base_existing: bool
) -> tuple[str, str]:
    """Return (start_ref, sha) for a new recipe-repo branch."""
    if base_existing:
        current = run_git(["branch", "--show-current"], meta_repo)
        start_ref = current if current else "HEAD"
        sha = run_git(["rev-parse", "HEAD"], meta_repo)
        return start_ref, sha
    if git_ref_exists(meta_repo, "refs/remotes/origin/main"):
        sha = run_git(["rev-parse", "refs/remotes/origin/main"], meta_repo)
        return "origin/main", sha
    if git_ref_exists(meta_repo, "refs/heads/main"):
        sha = run_git(["rev-parse", "refs/heads/main"], meta_repo)
        return "main", sha
    raise SystemExit(
        "ERROR: no main or origin/main in recipe repo; "
        "pass --base-existing or fetch main"
    )


def ensure_matching_branch(
    meta_repo: Path,
    branch: str,
    dry_run: bool,
    base_existing: bool,
) -> str:
    """Checkout or create branch. Return that branch's HEAD SHA.

    New branches start from origin/main (or main) unless base_existing.
    """
    local_ref = f"refs/heads/{branch}"
    remote_ref = f"refs/remotes/origin/{branch}"
    current = run_git(["branch", "--show-current"], meta_repo)

    if current == branch:
        sha = run_git(["rev-parse", "HEAD"], meta_repo)
        print(f"INFO: meta-layer already on {branch}")
        return sha

    if git_ref_exists(meta_repo, local_ref):
        sha = run_git(["rev-parse", local_ref], meta_repo)
        if dry_run:
            print(f"INFO: would checkout existing branch {branch}")
            return sha
        run_git(["checkout", branch], meta_repo)
        print(f"INFO: checked out existing branch {branch}")
        return run_git(["rev-parse", "HEAD"], meta_repo)

    if git_ref_exists(meta_repo, remote_ref):
        sha = run_git(["rev-parse", remote_ref], meta_repo)
        if dry_run:
            print(f"INFO: would checkout existing origin/{branch}")
            return sha
        run_git(
            ["checkout", "-B", branch, f"origin/{branch}"],
            meta_repo,
        )
        print(f"INFO: checked out existing origin/{branch}")
        return run_git(["rev-parse", "HEAD"], meta_repo)

    start_ref, sha = recipe_branch_start_point(
        meta_repo, base_existing
    )
    if dry_run:
        print(f"INFO: would create branch {branch} from {start_ref}")
        return sha
    run_git(["checkout", "-b", branch, start_ref], meta_repo)
    print(f"INFO: created branch {branch} from {start_ref}")
    return run_git(["rev-parse", "HEAD"], meta_repo)


def require_commit_in_source(src_repo: Path, sha: str) -> None:
    """Fail if sha is not a commit in the source repo history."""
    if not sha or sha == "?":
        raise SystemExit(
            "ERROR: existing SRCREV is missing or unreadable; "
            "cannot verify it in source history"
        )
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
        cwd=src_repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"ERROR: existing SRCREV {sha} is not a commit in "
            f"{src_repo} history; fetch or check the recipe pin"
        )
    resolved = result.stdout.strip() or sha
    print(f"INFO: existing SRCREV {resolved} is in source history")


def commit_recipe(recipe: Path, issue: str, recipe_name: str) -> None:
    meta_repo = Path(run_git(["rev-parse", "--show-toplevel"], recipe.parent))
    rel = str(recipe.relative_to(meta_repo))
    message = f"{issue}:{recipe_name} Update SRCREV"
    kind = commit_or_amend(
        meta_repo, rel, message, is_srcrev_only_diff
    )
    if kind == "amended":
        print(f"INFO: reused SRCREV commit in {meta_repo}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="update_src_rev_bb",
        description=(
            "Update SRCREV in a meta-judo recipe from source repo HEAD. "
            "The required repo argument names the source repo or oe/meta-judo* "
            "meta layer; infer the other from cwd when possible."
        ),
    )
    parser.add_argument(
        "repo",
        help=(
            "Repo name (required). Source repo: mqtt-api, src/mqtt-api. "
            "Meta layer: meta-judo-proprietary, oe/meta-judo-proprietary"
        ),
    )
    parser.add_argument(
        "--workspace",
        help="Repo workspace root (default: auto-detect via .repo or default.xml)",
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

    src_repo, layers = resolve_repos(args.repo, cwd, workspace)
    repo_name = repo_name_from_src(src_repo)
    srcrev = args.srcrev or run_git(["rev-parse", "HEAD"], src_repo)
    src_branch = source_branch_name(src_repo)

    recipe = resolve_recipe(layers, repo_name, args.recipe, workspace)
    recipe_path = recipe_display_path(recipe, workspace)
    meta_repo = meta_repo_for_recipe(recipe)
    meta_rel = recipe_display_path(meta_repo, workspace)

    print(f"INFO: src/{repo_name} HEAD {srcrev}")
    print(f"INFO: source branch {src_branch}")
    print(f"INFO: recipe {recipe_path}")
    print(f"INFO: meta layer {meta_rel}")
    print(f"INFO: push {recipe_display_path(src_repo, workspace)}: "
          f"git push origin {src_branch}")
    print(f"INFO: push {meta_rel}: git push origin {src_branch}")

    meta_head = ensure_matching_branch(
        meta_repo,
        src_branch,
        args.dry_run,
        args.base_existing,
    )
    if not args.dry_run and not recipe.is_file():
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

    print(f"INFO: {var_name}: {old_rev} -> {srcrev}")
    require_commit_in_source(src_repo, old_rev)

    if old_rev == srcrev:
        print(f"INFO: meta-layer HEAD {meta_head}")
        print(
            f"RESULT: recipe {recipe_path} already matches "
            f"src/{repo_name} HEAD ({srcrev})"
        )
        return 0

    updated, changed = replace_srcrev(content, var_name, srcrev)
    if not changed:
        raise SystemExit(
            f"ERROR: failed to update {var_name} in {recipe_path}"
        )

    if args.dry_run:
        print(f"INFO: meta-layer HEAD {meta_head}")
        print(f"RESULT: would update recipe {recipe_path}")
        return 0

    recipe.write_text(updated, encoding="utf-8")

    if args.no_commit:
        meta_head = run_git(["rev-parse", "HEAD"], meta_repo)
        print(f"INFO: meta-layer HEAD {meta_head}")
        print(f"RESULT: updated recipe {recipe_path}")
        return 0

    issue = args.issue or extract_issue(recipe.parent, src_repo)
    if not issue:
        raise SystemExit(
            "ERROR: could not parse issue id from branch name; pass --issue"
        )

    recipe_name = recipe_display_name(recipe)
    commit_recipe(recipe, issue, recipe_name)
    meta_head = run_git(["rev-parse", "HEAD"], meta_repo)
    print(f"INFO: meta-layer HEAD {meta_head}")
    print(f"RESULT: updated and committed recipe {recipe_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        eprint(f"ERROR: git command failed: {' '.join(exc.cmd)}")
        if exc.stderr:
            eprint(exc.stderr.strip())
        raise SystemExit(1) from exc
