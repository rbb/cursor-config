#!/usr/bin/env python3
"""Synchronize shared skills and rules across Cursor config copies.

Uses this repo (cursor-config) as the name inventory. Finds matching
skills and rules under ~/.cursor and ~/Documents/projects/*/{.cursor,.agents}
when those copies already exist.

When copies diverge, reconciles file-by-file with git merge-file (three-way
merge). Oldest copy is the base, cursor-config is preferred as "ours", newest
copy is "theirs". On merge conflicts, newest wins for file content.

After reconciliation, writes the merged result here and copies it to every
other existing location. Creates local-only git commits in this repo (one per
changed skill or rule): clean merges on main, conflicted merges on
sync/<name>/<project>. With --push, pushes main when it is ahead of upstream.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIR_NAMES = {"__pycache__", ".git"}
SKIP_FILE_SUFFIXES = {".pyc", ".pyo"}
SINGLE_FILE = Path(".")


@dataclass(frozen=True)
class Item:
    kind: str  # "skill" or "rule"
    name: str
    canonical: Path

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.name}"

    @property
    def is_single_file(self) -> bool:
        return self.kind == "rule"


@dataclass(frozen=True)
class FileVersion:
    location: Path
    content: bytes
    mtime: float


@dataclass
class MergeStats:
    identical: int = 0
    git_merge: int = 0
    single_side: int = 0
    merge_conflicts: int = 0
    conflict_source: Path | None = None
    conflict_source_mtime: float = 0.0

    def record_conflict(self, source: FileVersion) -> None:
        self.merge_conflicts += 1
        if source.mtime >= self.conflict_source_mtime:
            self.conflict_source = source.location
            self.conflict_source_mtime = source.mtime

    @property
    def had_merge_conflicts(self) -> bool:
        return self.merge_conflicts > 0


@dataclass
class SyncReport:
    summary: str = ""
    detail_lines: list[str] = field(default_factory=list)
    branch_commits: list[str] = field(default_factory=list)
    had_error: bool = False
    had_conflicts: bool = False

    @property
    def needs_alert(self) -> bool:
        return self.had_error or self.had_conflicts or bool(self.branch_commits)

    def notification_body(self) -> str:
        parts = [self.summary]
        if self.detail_lines:
            parts.append("")
            parts.extend(self.detail_lines)
        if self.branch_commits:
            parts.append("")
            parts.append("Branch commits:")
            parts.extend(f"  {line}" for line in self.branch_commits)
        return "\n".join(parts)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def projects_root() -> Path:
    return Path.home() / "Documents" / "projects"


def iter_project_dirs() -> list[Path]:
    root = projects_root()
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def should_skip_file(path: Path) -> bool:
    return path.suffix in SKIP_FILE_SUFFIXES


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES


def iter_tree_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [] if should_skip_file(root) else [root]

    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        base = Path(dirpath)
        for filename in filenames:
            path = base / filename
            if not should_skip_file(path):
                files.append(path)
    return sorted(files)


def tree_digest_from_files(files: dict[Path, bytes]) -> str:
    hasher = hashlib.sha256()
    for rel in sorted(files):
        hasher.update(rel.as_posix().encode())
        hasher.update(b"\0")
        hasher.update(files[rel])
        hasher.update(b"\0")
    return hasher.hexdigest()


def tree_digest(root: Path) -> tuple[str, float]:
    """Return (sha256, max_mtime) for a file or directory tree."""
    if not root.exists():
        return "", 0.0

    if root.is_file():
        data = root.read_bytes()
        return hashlib.sha256(data).hexdigest(), root.stat().st_mtime

    files = {
        path.relative_to(root): path.read_bytes()
        for path in iter_tree_files(root)
    }
    max_mtime = 0.0
    for path in iter_tree_files(root):
        max_mtime = max(max_mtime, path.stat().st_mtime)
    return tree_digest_from_files(files), max_mtime


def collect_file_versions(
    locations: list[Path], item: Item
) -> dict[Path, list[FileVersion]]:
    versions: dict[Path, list[FileVersion]] = {}
    for location in locations:
        if item.is_single_file:
            rel = SINGLE_FILE
            files = {rel: location.read_bytes()}
            mtime = location.stat().st_mtime
            versions.setdefault(rel, []).append(
                FileVersion(location, files[rel], mtime)
            )
            continue

        for path in iter_tree_files(location):
            rel = path.relative_to(location)
            versions.setdefault(rel, []).append(
                FileVersion(
                    location,
                    path.read_bytes(),
                    path.stat().st_mtime,
                )
            )
    return versions


def unique_versions(versions: list[FileVersion]) -> list[FileVersion]:
    seen: set[bytes] = set()
    unique: list[FileVersion] = []
    for version in sorted(versions, key=lambda entry: entry.mtime):
        if version.content in seen:
            continue
        seen.add(version.content)
        unique.append(version)
    return unique


def pick_ours(
    versions: list[FileVersion],
    canonical: Path,
    base: FileVersion,
) -> FileVersion:
    for version in versions:
        if version.location.resolve() == canonical.resolve():
            return version

    for version in reversed(unique_versions(versions)):
        if version.content != base.content:
            return version
    return base


def git_merge_file(base: bytes, ours: bytes, theirs: bytes) -> tuple[bytes, int]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = {
            name: root / name
            for name in ("base", "ours", "theirs")
        }
        paths["base"].write_bytes(base)
        paths["ours"].write_bytes(ours)
        paths["theirs"].write_bytes(theirs)
        result = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                str(paths["ours"]),
                str(paths["base"]),
                str(paths["theirs"]),
            ],
            capture_output=True,
            check=False,
        )
        return result.stdout, result.returncode


def resolve_file_content(
    rel: Path,
    versions: list[FileVersion],
    canonical: Path,
    stats: MergeStats,
    item: Item,
) -> bytes:
    unique = unique_versions(versions)
    if len(unique) == 1:
        stats.identical += 1
        return unique[0].content

    base = unique[0]
    newest = unique[-1]
    ours = pick_ours(versions, canonical, base)

    if base.content == newest.content:
        stats.identical += 1
        return newest.content
    if base.content == ours.content:
        stats.single_side += 1
        return newest.content
    if base.content == newest.content:
        stats.single_side += 1
        return ours.content
    if ours.content == newest.content:
        return newest.content

    merged, rc = git_merge_file(base.content, ours.content, newest.content)
    if rc == 0:
        stats.git_merge += 1
        return merged

    stats.record_conflict(newest)
    branch = sync_branch_name(item, newest.location, repo_root())
    label = item_file_label(rel)
    print(
        f"  merge conflict in {label}; using newest copy; "
        f"commit will use branch {branch}"
    )
    return newest.content


def item_file_label(rel: Path) -> str:
    return "file" if rel == SINGLE_FILE else rel.as_posix()


def merge_item_files(
    locations: list[Path],
    item: Item,
) -> tuple[dict[Path, bytes], MergeStats]:
    file_versions = collect_file_versions(locations, item)
    merged: dict[Path, bytes] = {}
    stats = MergeStats()

    for rel in sorted(file_versions, key=lambda path: path.as_posix()):
        merged[rel] = resolve_file_content(
            rel,
            file_versions[rel],
            item.canonical,
            stats,
            item,
        )
    return merged, stats


def remove_tree(path: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    if dry_run:
        print(f"  would remove {path}")
        return
    if path.is_file() or path.is_symlink():
        path.unlink()
    else:
        shutil.rmtree(path)


def ensure_parent(path: Path, dry_run: bool) -> None:
    parent = path.parent
    if parent.exists() or dry_run:
        return
    parent.mkdir(parents=True, exist_ok=True)


def write_bytes(path: Path, content: bytes, dry_run: bool) -> None:
    ensure_parent(path, dry_run)
    if dry_run:
        print(f"  would write {path}")
        return
    path.write_bytes(content)


def write_merged_tree(
    item: Item,
    merged: dict[Path, bytes],
    dry_run: bool,
) -> None:
    if item.is_single_file:
        write_bytes(item.canonical, merged[SINGLE_FILE], dry_run)
        return

    existing = {
        path.relative_to(item.canonical)
        for path in iter_tree_files(item.canonical)
    }
    for rel in sorted(existing - set(merged)):
        remove_tree(item.canonical / rel, dry_run)

    for rel, content in sorted(merged.items()):
        write_bytes(item.canonical / rel, content, dry_run)


def mirror_to_external(
    item: Item,
    merged: dict[Path, bytes],
    external: list[Path],
    dry_run: bool,
) -> None:
    for location in external:
        if item.is_single_file:
            write_bytes(location, merged[SINGLE_FILE], dry_run)
            continue

        existing = {
            path.relative_to(location)
            for path in iter_tree_files(location)
        }
        for rel in sorted(existing - set(merged)):
            remove_tree(location / rel, dry_run)
        for rel, content in sorted(merged.items()):
            write_bytes(location / rel, content, dry_run)


def inventory(root: Path) -> list[Item]:
    items: list[Item] = []

    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for path in sorted(skills_dir.iterdir()):
            if path.is_dir() and not path.name.startswith("."):
                items.append(Item("skill", path.name, path))

    rules_dir = root / "rules"
    if rules_dir.is_dir():
        for path in sorted(rules_dir.glob("*.mdc")):
            items.append(Item("rule", path.stem, path))

    return items


def skill_locations(item: Item) -> list[Path]:
    locations = [item.canonical]
    home_skill = Path.home() / ".cursor" / "skills" / item.name
    if home_skill.exists():
        locations.append(home_skill)

    for project in iter_project_dirs():
        for subpath in (
            project / ".cursor" / "skills" / item.name,
            project / ".agents" / "skills" / item.name,
        ):
            if subpath.exists():
                locations.append(subpath)

    return dedupe_paths(locations)


def rule_locations(item: Item) -> list[Path]:
    locations = [item.canonical]
    home_rule = Path.home() / ".cursor" / "rules" / f"{item.name}.mdc"
    if home_rule.exists():
        locations.append(home_rule)

    for project in iter_project_dirs():
        rule_path = project / ".cursor" / "rules" / f"{item.name}.mdc"
        if rule_path.exists():
            locations.append(rule_path)

    return dedupe_paths(locations)


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(path)
    return ordered


def external_locations(item: Item, locations: list[Path]) -> list[Path]:
    canonical = item.canonical.resolve()
    return [
        path
        for path in locations
        if path.resolve() != canonical
    ]


def project_name_from_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
        return "cursor-config"
    except ValueError:
        pass

    projects = projects_root()
    try:
        rel = resolved.relative_to(projects)
        if rel.parts:
            return rel.parts[0]
    except ValueError:
        pass

    cursor_home = Path.home() / ".cursor"
    try:
        resolved.relative_to(cursor_home)
        return "cursor"
    except ValueError:
        return "external"


def sync_branch_name(item: Item, source: Path, root: Path) -> str:
    project = project_name_from_path(source, root)
    return f"sync/{item.name}/{project}"


def item_rel_paths(item: Item) -> list[str]:
    if item.kind == "skill":
        return [f"skills/{item.name}"]
    return [f"rules/{item.name}.mdc"]


def run_git(args: list[str], cwd: Path, *, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_try(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def main_push_target(root: Path) -> tuple[str, str] | None:
    """Return (remote, branch) for main's upstream, e.g. ('github', 'main')."""
    result = git_try(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        root,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    upstream = result.stdout.strip()
    if "/" not in upstream:
        return None
    remote, branch = upstream.split("/", 1)
    return remote, branch


def main_push_needed(root: Path) -> bool:
    target = main_push_target(root)
    if target is None:
        return False
    remote, branch = target
    local = git_try(["rev-parse", f"refs/heads/{branch}"], root)
    if local.returncode != 0:
        return False
    remote_ref = f"refs/remotes/{remote}/{branch}"
    remote_sha = git_try(["rev-parse", remote_ref], root)
    if remote_sha.returncode != 0:
        return True
    return local.stdout.strip() != remote_sha.stdout.strip()


def maybe_push_main(
    root: Path,
    report: SyncReport,
    *,
    enabled: bool,
    dry_run: bool,
) -> None:
    if not enabled:
        return

    run_git(["checkout", "main"], root)
    target = main_push_target(root)
    if target is None:
        message = "ERROR: main has no upstream configured; cannot push"
        print(message)
        report.had_error = True
        report.detail_lines.append(message)
        return

    remote, branch = target
    if not main_push_needed(root):
        print(f"main: already up to date with {remote}/{branch}")
        return

    if dry_run:
        print(f"would push main to {remote}/{branch}")
        return

    result = git_try(["push", remote, branch], root)
    if result.returncode == 0:
        print(f"pushed main to {remote}/{branch}")
        return

    output = "\n".join(
        part for part in (result.stdout.strip(), result.stderr.strip()) if part
    )
    message = f"ERROR: push to {remote}/{branch} failed"
    print(message)
    if output:
        print(output)
    report.had_error = True
    report.detail_lines.append(message)
    if output:
        report.detail_lines.append(output)


def init_desktop_notify() -> bool:
    """Initialize libnotify via PyGObject (same stack as notify-send)."""
    try:
        import gi

        gi.require_version("Notify", "0.7")
        from gi.repository import Notify

        if not Notify.is_initted():
            Notify.init("sync-skills-rules")
        return True
    except Exception as exc:
        print(
            f"WARNING: desktop notify unavailable: {exc}",
            file=sys.stderr,
        )
        return False


def send_desktop_notify(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    persistent: bool = True,
) -> bool:
    """Send a libnotify toast (D-Bus → GNOME notification daemon).

    Uses EXPIRES_NEVER by default so cron-run summaries stay until dismissed.
    """
    try:
        import gi

        gi.require_version("Notify", "0.7")
        from gi.repository import Notify

        if not Notify.is_initted():
            Notify.init("sync-skills-rules")

        icon = "dialog-error" if urgency == "critical" else "dialog-information"
        notification = Notify.Notification.new(title, body, icon)
        if persistent:
            notification.set_timeout(Notify.EXPIRES_NEVER)
        urgency_map = {
            "low": Notify.Urgency.LOW,
            "normal": Notify.Urgency.NORMAL,
            "critical": Notify.Urgency.CRITICAL,
        }
        notification.set_urgency(urgency_map.get(urgency, Notify.Urgency.NORMAL))
        notification.show()
        return True
    except Exception as exc:
        print(f"WARNING: failed to send desktop notify: {exc}", file=sys.stderr)
        return False


def maybe_send_sync_report(report: SyncReport, *, enabled: bool) -> None:
    if not enabled or not report.needs_alert:
        return
    if not init_desktop_notify():
        return

    if report.had_error:
        title = "Sync skills/rules failed"
    else:
        title = "Sync skills/rules: merge conflicts"
    send_desktop_notify(
        title,
        report.notification_body(),
        urgency="critical",
        persistent=True,
    )


def format_merge_stats(stats: MergeStats) -> str:
    parts: list[str] = []
    if stats.git_merge:
        parts.append(f"{stats.git_merge} git-merged")
    if stats.merge_conflicts:
        parts.append(f"{stats.merge_conflicts} conflict(s)")
    if stats.single_side:
        parts.append(f"{stats.single_side} one-sided")
    if stats.identical:
        parts.append(f"{stats.identical} unchanged")
    return ", ".join(parts) if parts else "no file changes"


def sync_item(
    item: Item,
    locations: list[Path],
    dry_run: bool,
    report: SyncReport | None = None,
) -> tuple[bool, bool, MergeStats | None]:
    """Reconcile copies and propagate to all external locations.

    Returns (canonical_changed, did_sync, merge_stats).
    """
    unique_digests = {tree_digest(path)[0] for path in locations}
    if len(unique_digests) <= 1:
        print(f"{item.label}: already in sync ({len(locations)} copies)")
        return False, False, None

    canonical_before, _ = tree_digest(item.canonical)
    merged, stats = merge_item_files(locations, item)
    merged_digest = tree_digest_from_files(merged)

    print(
        f"{item.label}: reconciling {len(locations)} copies "
        f"({format_merge_stats(stats)})"
    )
    if stats.had_merge_conflicts and stats.conflict_source:
        branch = sync_branch_name(
            item, stats.conflict_source, repo_root()
        )
        project = project_name_from_path(stats.conflict_source, repo_root())
        conflict_line = (
            f"  merge conflicts detected; commit will use branch "
            f"{branch} (from {project})"
        )
        print(conflict_line)
        if report is not None:
            report.had_conflicts = True
            report.detail_lines.append(f"{item.label}: {branch} ({project})")

    write_merged_tree(item, merged, dry_run)
    mirror_to_external(
        item,
        merged,
        external_locations(item, locations),
        dry_run,
    )

    if dry_run:
        return merged_digest != canonical_before, True, stats

    canonical_after, _ = tree_digest(item.canonical)
    return canonical_before != canonical_after, True, stats


def git_commit_item(
    root: Path,
    item: Item,
    stats: MergeStats | None,
    locations: list[Path],
    report: SyncReport | None = None,
) -> bool:
    rel_paths = item_rel_paths(item)

    status = git_try(["status", "--porcelain", "--", *rel_paths], root)
    if status.returncode != 0 or not status.stdout.strip():
        return False

    branch: str | None = None
    if stats and stats.had_merge_conflicts:
        source = stats.conflict_source
        if source is None:
            external = external_locations(item, locations)
            if external:
                source = max(external, key=lambda path: tree_digest(path)[1])
        if source is None:
            raise SystemExit(
                f"ERROR: merge conflicts for {item.label} but no external "
                "source location was found"
            )
        branch = sync_branch_name(item, source, root)

    run_git(["checkout", "main"], root)
    if branch:
        run_git(["checkout", "-B", branch], root)
    run_git(["add", "--", *rel_paths], root)

    detail = ""
    if stats and stats.git_merge:
        detail = f" ({stats.git_merge} file(s) git-merged)"
    if stats and stats.merge_conflicts:
        detail = (
            f" ({stats.merge_conflicts} merge conflict(s), newest wins)"
        )

    message = f"sync({item.kind}): {item.name}{detail}"
    run_git(["commit", "-m", message], root)

    if branch:
        project = project_name_from_path(
            stats.conflict_source if stats and stats.conflict_source else root,
            root,
        )
        commit_line = f"committed on branch {branch} (from {project}): {message}"
        print(commit_line)
        if report is not None:
            report.branch_commits.append(commit_line)
        run_git(["checkout", "main"], root)
        run_git(["restore", "--staged", "--worktree", "--", *rel_paths], root)
    else:
        print(f"committed on main: {message}")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize skills and rules that share names with this repo "
            "across ~/.cursor and ~/Documents/projects/* copies."
        )
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show actions without writing files or creating commits",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Sync files but do not create git commits in this repo",
    )
    parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        metavar="NAME",
        help="Limit to one skill (repeatable)",
    )
    parser.add_argument(
        "--rule",
        action="append",
        dest="rules",
        metavar="NAME",
        help="Limit to one rule without .mdc suffix (repeatable)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help=(
            "Send a persistent libnotify alert on failures only: script errors "
            "or merge conflicts saved to sync/<name>/<project> branches "
            "(same D-Bus path as notify-send). For cron, set DISPLAY and "
            "DBUS_SESSION_BUS_ADDRESS to your graphical session."
        ),
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help=(
            "Push main when it is ahead of its upstream remote. On push "
            "failure, print to stdout and send a notify alert when --notify "
            "is also set."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    report = SyncReport()

    if not (root / ".git").is_dir():
        print("ERROR: cursor-config git repo not found", file=sys.stderr)
        report.had_error = True
        report.summary = "cursor-config git repo not found"
        maybe_send_sync_report(report, enabled=args.notify)
        return 1

    if shutil.which("git") is None:
        print("ERROR: git is required for three-way merges", file=sys.stderr)
        report.had_error = True
        report.summary = "git is required for three-way merges"
        maybe_send_sync_report(report, enabled=args.notify)
        return 1

    items = inventory(root)
    if args.skills:
        wanted = set(args.skills)
        items = [
            item
            for item in items
            if item.kind != "skill" or item.name in wanted
        ]
    if args.rules:
        wanted = set(args.rules)
        items = [
            item
            for item in items
            if item.kind != "rule" or item.name in wanted
        ]

    if not items:
        print("No skills or rules matched.")
        return 0

    changed_items: list[tuple[Item, MergeStats | None, list[Path]]] = []
    synced = 0
    skipped = 0
    for item in items:
        if item.kind == "skill":
            locations = skill_locations(item)
        else:
            locations = rule_locations(item)

        if len(locations) < 2:
            skipped += 1
            continue

        changed, did_sync, stats = sync_item(
            item,
            locations,
            args.dry_run,
            report,
        )
        if did_sync:
            synced += 1
        if changed:
            changed_items.append((item, stats, locations))

    report.summary = (
        f"Summary: {len(items)} inventoried, "
        f"{skipped} with no peer copy, "
        f"{synced} reconciled, "
        f"{len(changed_items)} changed in this repo"
    )
    print(report.summary)

    if not args.dry_run and not args.no_commit and changed_items:
        for item, stats, locations in changed_items:
            git_commit_item(root, item, stats, locations, report)

    maybe_push_main(root, report, enabled=args.push, dry_run=args.dry_run)

    maybe_send_sync_report(report, enabled=args.notify)
    return 1 if report.had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
