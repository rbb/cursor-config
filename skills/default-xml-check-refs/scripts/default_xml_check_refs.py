#!/usr/bin/env python3
"""Verify SHA1 pins in a Repo manifest exist locally and on origin.

Parses default.xml (or another manifest), finds 40-character hex
revision attributes, and checks each project checkout under the
workspace. Origin and branch checks fetch into a temporary repo so
``--depth`` cannot shallow the project checkout. When the manifest
repo has a current branch, each pin must exist on a remote branch
with the same name. When that branch exists, the pin must equal the branch
tip on origin (not merely be an ancestor).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SKILL_DIR = Path(__file__).resolve().parent
_JUDO_ROOT = _SKILL_DIR.parents[3]


def is_sha1_revision(revision: str) -> bool:
    """True when revision is a full Git object name (pin), not a branch or tag."""
    return bool(SHA1_RE.match(revision))


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def find_workspace(start: Path | None = None) -> Path:
    """Return manifest-judo root (contains default.xml)."""
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "default.xml").is_file():
            return candidate
    return _JUDO_ROOT


def git_run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def is_git_dir(path: Path) -> bool:
    return (path / ".git").exists()


def cat_file_commit(repo: Path, sha: str) -> bool:
    result = git_run(["cat-file", "-t", sha], repo)
    return result.returncode == 0 and result.stdout.strip() == "commit"


def origin_url(repo: Path) -> str | None:
    result = git_run(["remote", "get-url", "origin"], repo)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def manifest_project_url(fetch: str, project_name: str) -> str:
    base = fetch.rstrip("/")
    suffix = "" if base.endswith(".git") else ".git"
    return f"{base}/{project_name}{suffix}"


def remote_branch_ref(branch: str) -> str:
    return f"refs/heads/{branch}"


def parse_ls_remote_head(stdout: str, ref: str) -> str | None:
    """Return commit SHA for ``ref`` from ``git ls-remote`` output."""
    needle = f"\t{ref}"
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == ref:
            sha = parts[0].lower()
            if is_sha1_revision(sha):
                return sha
        if line.endswith(ref) and len(parts) >= 1:
            sha = parts[0].lower()
            if is_sha1_revision(sha):
                return sha
    if needle in stdout:
        for line in stdout.splitlines():
            if needle in line:
                sha = line.split()[0].lower()
                if is_sha1_revision(sha):
                    return sha
    return None


def remote_branch_tip(url: str, branch: str) -> str | None:
    """Return tip SHA of ``branch`` on ``url``, or None if the branch is absent."""
    ref = remote_branch_ref(branch)
    result = git_run(["ls-remote", "--heads", url, ref], Path.cwd())
    if result.returncode != 0:
        return None
    return parse_ls_remote_head(result.stdout, ref)


def remote_branch_exists(url: str, branch: str) -> bool:
    return remote_branch_tip(url, branch) is not None


def fetch_commit_into_repo(repo: Path, remote: str, sha: str) -> bool:
    """Fetch one commit into ``repo``.

    ``--depth=1`` writes ``.git/shallow``. Call this only on a throwaway
    repo, never on a project checkout.
    """
    result = git_run(
        ["fetch", "--quiet", "--depth=1", remote, sha],
        repo,
    )
    return result.returncode == 0


def remote_tracking_ref(branch: str) -> str:
    return f"refs/remotes/origin/{branch}"


def fetch_remote_branch(repo: Path, remote: str, branch: str) -> bool:
    """Fetch origin branch tip into refs/remotes/origin/<branch>."""
    refspec = f"refs/heads/{branch}:{remote_tracking_ref(branch)}"
    result = git_run(["fetch", "--quiet", remote, refspec], repo)
    return result.returncode == 0


def commit_on_branch(repo: Path, sha: str, branch: str) -> bool:
    """True when sha is an ancestor of origin/<branch> (inclusive)."""
    tip = remote_tracking_ref(branch)
    tip_check = git_run(["rev-parse", "--verify", "--quiet", tip], repo)
    if tip_check.returncode != 0:
        return False
    if not cat_file_commit(repo, sha):
        return False
    ancestor = git_run(
        ["merge-base", "--is-ancestor", sha, tip],
        repo,
    )
    return ancestor.returncode == 0


def prepare_repo_for_branch_check(
    repo: Path,
    remote: str,
    sha: str,
    branch: str,
) -> bool:
    if not fetch_commit_into_repo(repo, remote, sha):
        return False
    if not fetch_remote_branch(repo, remote, branch):
        return False
    if commit_on_branch(repo, sha, branch):
        return True
    # Shallow fetch may omit history between sha and branch tip; deepen once.
    deepen = git_run(["fetch", "--quiet", "--deepen=500", remote, branch], repo)
    if deepen.returncode != 0:
        return False
    return commit_on_branch(repo, sha, branch)


def probe_remote_url(url: str, sha: str) -> bool:
    """Fetch sha from url into a throwaway repo; return True if commit exists."""
    tmp = Path(tempfile.mkdtemp(prefix="default-xml-check-refs-"))
    try:
        init = git_run(["init", "-q"], tmp)
        if init.returncode != 0:
            return False
        fetched = git_run(
            ["fetch", "--quiet", "--depth=1", url, sha],
            tmp,
        )
        if fetched.returncode != 0:
            return False
        return cat_file_commit(tmp, sha)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def probe_branch_alignment(
    url: str,
    sha: str,
    branch: str,
    *,
    require_tip: bool = True,
) -> tuple[str, str]:
    """Verify pin against origin/<branch>.

    Returns (branch_status, detail). When ``require_tip`` is true (default),
    ``ok`` only if the pin equals the branch tip. Otherwise ``ok`` when the
    pin is an ancestor of the tip (inclusive).
    """
    sha = sha.lower()
    tip = remote_branch_tip(url, branch)
    if tip is None:
        return "not_on_branch", f"origin has no branch {branch!r}"
    if sha == tip:
        return "ok", ""
    if not require_tip:
        tmp = Path(tempfile.mkdtemp(prefix="default-xml-check-refs-branch-"))
        try:
            init = git_run(["init", "-q"], tmp)
            if init.returncode != 0:
                return "not_on_branch", "could not init temp repo"
            add = git_run(["remote", "add", "origin", url], tmp)
            if add.returncode != 0:
                return "not_on_branch", "could not add origin"
            if prepare_repo_for_branch_check(tmp, "origin", sha, branch):
                return "ok", ""
            return "not_on_branch", f"pin not on origin/{branch}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    tmp = Path(tempfile.mkdtemp(prefix="default-xml-check-refs-branch-"))
    try:
        init = git_run(["init", "-q"], tmp)
        if init.returncode != 0:
            return "not_on_branch", "could not init temp repo"
        add = git_run(["remote", "add", "origin", url], tmp)
        if add.returncode != 0:
            return "not_on_branch", "could not add origin"
        if not prepare_repo_for_branch_check(tmp, "origin", sha, branch):
            return "not_on_branch", f"pin not on origin/{branch}"
        return (
            "behind_tip",
            f"pin not at origin/{branch} tip (tip {tip[:12]}…)",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def manifest_git_branch(workspace: Path, override: str | None) -> str | None:
    if override:
        return override
    if not is_git_dir(workspace):
        eprint("WARNING: workspace is not a git checkout; skip branch alignment")
        return None
    result = git_run(["branch", "--show-current"], workspace)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        eprint(
            "WARNING: detached HEAD on manifest; pass --manifest-branch "
            "to verify branch alignment"
        )
        return None
    return branch


@dataclass(frozen=True)
class ProjectPin:
    name: str
    path: str
    remote_name: str
    revision: str


@dataclass
class PinResult:
    pin: ProjectPin
    local_status: str
    origin_status: str
    branch_status: str
    origin_url: str
    detail: str = ""
    branch_detail: str = ""

    @property
    def ok(self) -> bool:
        if self.origin_status not in ("ok", "skipped"):
            return False
        if self.branch_status not in ("ok", "skipped", "n/a"):
            return False
        if self.local_status in ("missing", "error", "not_git"):
            return False
        return True


def load_pins(
    manifest_path: Path,
) -> tuple[dict[str, str], list[ProjectPin], int]:
    root = ET.parse(manifest_path).getroot()
    remotes: dict[str, str] = {}
    for node in root.findall("remote"):
        name = node.attrib.get("name")
        fetch = node.attrib.get("fetch")
        if name and fetch:
            remotes[name] = fetch

    pins: list[ProjectPin] = []
    skipped_non_hash = 0
    for node in root.findall("project"):
        revision = node.attrib.get("revision", "")
        if not is_sha1_revision(revision):
            if revision:
                skipped_non_hash += 1
            continue
        name = node.attrib.get("name")
        path = node.attrib.get("path")
        remote_name = node.attrib.get("remote")
        if not name or not path or not remote_name:
            continue
        if remote_name not in remotes:
            eprint(f"WARNING: unknown remote {remote_name!r} for {name}")
            continue
        pins.append(
            ProjectPin(
                name=name,
                path=path,
                remote_name=remote_name,
                revision=revision.lower(),
            )
        )
    return remotes, pins, skipped_non_hash


def check_pin(
    pin: ProjectPin,
    workspace: Path,
    remotes: dict[str, str],
    manifest_branch: str | None,
    *,
    skip_remote: bool,
    skip_tip: bool,
) -> PinResult:
    rel = Path(pin.path)
    checkout = workspace if rel == Path(".") else workspace / rel
    manifest_url = manifest_project_url(remotes[pin.remote_name], pin.name)

    local_status = "not_checked_out"
    if is_git_dir(checkout):
        if cat_file_commit(checkout, pin.revision):
            local_status = "ok"
        else:
            local_status = "missing"
    elif checkout.exists() and not is_git_dir(checkout):
        local_status = "not_git"

    origin_status = "skipped" if skip_remote else "pending"
    branch_status = "skipped" if skip_remote else "pending"
    origin_used = manifest_url
    detail = ""
    branch_detail = ""

    if skip_remote:
        if manifest_branch is None:
            branch_status = "n/a"
        return PinResult(
            pin,
            local_status,
            origin_status,
            branch_status,
            origin_used,
            detail,
            branch_detail,
        )

    # Origin and branch checks use a throwaway repo. Fetching --depth
    # into the project checkout records the pin in .git/shallow.
    if is_git_dir(checkout):
        url = origin_url(checkout)
        if url:
            origin_used = url
        else:
            detail = "no origin remote; using manifest URL"
            origin_used = manifest_url
    origin_status = (
        "ok" if probe_remote_url(origin_used, pin.revision) else "missing"
    )

    # Branch alignment runs only for SHA1 pins (see load_pins).
    if manifest_branch is None:
        branch_status = "n/a"
    elif origin_status != "ok":
        branch_status = "skipped"
        branch_detail = "origin pin check failed"
    else:
        has_branch = remote_branch_exists(origin_used, manifest_branch)
        if not has_branch:
            if manifest_branch == "main":
                branch_status = "no_branch"
                branch_detail = "no origin/main"
            else:
                branch_status = "n/a"
                branch_detail = (
                    f"no origin/{manifest_branch}; upstream pin"
                )
        else:
            branch_status, branch_detail = probe_branch_alignment(
                origin_used,
                pin.revision,
                manifest_branch,
                require_tip=not skip_tip,
            )
            if not branch_detail and branch_status != "ok":
                branch_detail = f"not on origin/{manifest_branch}"

    return PinResult(
        pin,
        local_status,
        origin_status,
        branch_status,
        origin_used,
        detail,
        branch_detail,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify manifest SHA1 revision pins (local + origin).",
    )
    parser.add_argument(
        "-m",
        "--manifest",
        type=Path,
        default=None,
        help="Manifest XML (default: <workspace>/default.xml).",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        type=Path,
        default=None,
        help="Repo workspace root (default: auto-detect).",
    )
    parser.add_argument(
        "--manifest-branch",
        default=None,
        help="Branch name for alignment checks (default: git branch in workspace).",
    )
    parser.add_argument(
        "--skip-remote",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Only inspect local checkouts; skip origin, branch, and tip checks."
        ),
    )
    parser.add_argument(
        "--skip-tip",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "When origin/{manifest-branch} exists, require pin equals branch "
            "tip (default). Use --skip-tip to only require pin is on branch."
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print failures and summary.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = (args.workspace or find_workspace()).resolve()
    manifest = (args.manifest or workspace / "default.xml").resolve()
    if not manifest.is_file():
        eprint(f"ERROR: manifest not found: {manifest}")
        return 2

    manifest_branch = manifest_git_branch(workspace, args.manifest_branch)
    remotes, pins, skipped_non_hash = load_pins(manifest)
    if not pins:
        print("No SHA1 revision pins found.")
        return 0

    if not args.quiet and skipped_non_hash:
        print(
            f"INFO: skipped {skipped_non_hash} project(s) with non-hash "
            "revision (no ref or branch checks).\n"
        )

    if manifest_branch and not args.quiet:
        print(f"Manifest branch: {manifest_branch}\n")

    results: list[PinResult] = []
    for pin in pins:
        results.append(
            check_pin(
                pin,
                workspace,
                remotes,
                manifest_branch,
                skip_remote=args.skip_remote,
                skip_tip=args.skip_tip,
            )
        )

    failures = [r for r in results if not r.ok]
    for res in results:
        if args.quiet and res.ok:
            continue
        p = res.pin
        line = (
            f"{p.name:28} {p.revision[:12]}…  "
            f"local={res.local_status:16} origin={res.origin_status:8} "
            f"branch={res.branch_status}"
        )
        if not res.ok:
            line = f"FAIL {line}"
        print(line)
        if res.detail and (not args.quiet or not res.ok):
            print(f"     {res.detail}")
        if res.branch_detail and (not args.quiet or not res.ok):
            print(f"     branch: {res.branch_detail}")
        if res.origin_status == "missing" and (not args.quiet or not res.ok):
            print(f"     origin: {res.origin_url}")

    print(
        f"\nChecked {len(results)} pin(s): "
        f"{len(results) - len(failures)} ok, {len(failures)} failed."
    )
    if args.skip_remote:
        print(
            "NOTE: --skip-remote; origin, branch tip, and alignment not "
            "verified."
        )
    elif args.skip_tip:
        print("NOTE: --skip-tip; pins may be behind origin branch tips.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
