#!/usr/bin/env python3
"""Download Bamboo build logs for Judo CI triage.

Uses devops/judo-devops/scripts/bamboo_client.py. Stdlib + requests only
(via bamboo_client). Never commits token.txt or bamboo_logs/.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Repo layout: .../judo/.agents/skills/bamboo-download-build-logs/scripts/
_SKILL_DIR = Path(__file__).resolve().parent
_JUDO_ROOT = _SKILL_DIR.parents[3]
_BAMBOO_CLIENT_DIR = _JUDO_ROOT / "devops" / "judo-devops" / "scripts"

DEFAULT_PLAN = "CC-JUDO"
DEFAULT_BASE_URL = "https://bamboo.trimble.tools"
DEFAULT_TOKEN_FILE = _JUDO_ROOT / "token.txt"
DEFAULT_OUT_DIR = _JUDO_ROOT / "bamboo_logs"
PREFIX_RE = re.compile(r"^CC-JUDO\d+$", re.IGNORECASE)
LOCK_JOB_SUFFIX = "GENERATELOCKEDMANIFEST"
LOCK_ARTIFACT = "default.lock.xml"


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def find_judo_root(start: Path | None = None) -> Path:
    """Return manifest-judo workspace root (contains default.xml)."""
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "default.xml").is_file():
            return candidate
    return _JUDO_ROOT


def setup_bamboo_env(token_file: Path, base_url: str) -> None:
    if not token_file.is_file():
        raise SystemExit(
            f"ERROR: Bamboo token file not found: {token_file}\n"
            "Create a PAT in Bamboo and save it to token.txt (gitignored)."
        )
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit(f"ERROR: Token file is empty: {token_file}")
    os.environ["BAMBOO_BASE_URL"] = base_url.rstrip("/")
    os.environ["BAMBOO_TOKEN"] = token
    if str(_BAMBOO_CLIENT_DIR) not in sys.path:
        sys.path.insert(0, str(_BAMBOO_CLIENT_DIR))


def current_git_branch(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(
            f"ERROR: Could not detect git branch in {repo_root}: {exc}"
        ) from exc
    branch = out.stdout.strip()
    if branch == "HEAD":
        raise SystemExit(
            "ERROR: Detached HEAD; pass --branch explicitly."
        )
    return branch


def list_build_jobs(build_result_key: str) -> list[dict]:
    import bamboo_client as bc

    session = bc._session()
    url = f"{bc.BAMBOO_BASE_URL}/rest/api/latest/result/{build_result_key}"
    resp = session.get(
        url,
        params={"expand": "stages.stage.results.result", "max-results": 100},
    )
    resp.raise_for_status()
    data = resp.json()
    stages = data.get("stages", {}).get("stage", [])
    if isinstance(stages, dict):
        stages = [stages]

    jobs: list[dict] = []
    for stage in stages:
        stage_name = stage.get("name", "Unknown")
        results_list = stage.get("results", {}).get("result", [])
        if isinstance(results_list, dict):
            results_list = [results_list]
        for row in results_list:
            jobs.append(
                {
                    "job_key": row.get("key", row.get("buildResultKey", "")),
                    "job_name": row.get(
                        "planName",
                        row.get("plan", {}).get("shortName", ""),
                    ),
                    "stage": stage_name,
                    "state": row.get(
                        "buildState", row.get("state", "Unknown")
                    ),
                }
            )
    return jobs


def resolve_build(
    *,
    plan_key: str,
    branch: str | None,
    build_number: int | None,
    prefix: str | None,
) -> tuple[str, int, str, dict]:
    import bamboo_client as bc

    if prefix:
        if build_number is None:
            raise SystemExit(
                "ERROR: --prefix requires --build <number>."
            )
        build_result_key = f"{prefix.upper()}-{build_number}"
        status = {
            "build_result_key": build_result_key,
            "build_number": build_number,
            "state": "Unknown",
            "failed_jobs": [],
            "message": None,
        }
        vcs_branch = branch or "(prefix mode)"
        return build_result_key, build_number, vcs_branch, status

    if not branch:
        raise SystemExit("ERROR: --branch is required unless --prefix is set.")

    status = bc.get_build_status(plan_key, branch, build_number)
    if status.get("message") and not status.get("build_result_key"):
        raise SystemExit(f"ERROR: {status['message']}")

    build_result_key = status.get("build_result_key")
    resolved_build = status.get("build_number")
    if not build_result_key or resolved_build is None:
        raise SystemExit(
            "ERROR: Could not resolve build. "
            f"{status.get('message', '')}".strip()
        )
    return build_result_key, int(resolved_build), branch, status


def fetch_job_log_by_key(job_key: str) -> str:
    """Download a job log when only the job result key is known."""
    import bamboo_client as bc

    session = bc._session()
    job_plan_key = "-".join(job_key.split("-")[:-1])
    primary_url = (
        f"{bc.BAMBOO_BASE_URL}/download/{job_plan_key}"
        f"/build_logs/{job_key}.log"
    )
    primary_status, primary_text = bc._streamed_get_text(session, primary_url)
    if primary_status // 100 == 2 and len(primary_text.strip()) > len("simple"):
        log_text = primary_text
    else:
        rest_url = f"{bc.BAMBOO_BASE_URL}/rest/api/latest/result/{job_key}/log"
        rest_status, rest_text = bc._streamed_get_text(session, rest_url)
        if rest_status // 100 == 2:
            log_text = rest_text
        else:
            log_text = (
                f"Could not fetch logs for {job_key} "
                f"(HTTP {primary_status}, {rest_status})."
            )

    if len(log_text) > bc.BAMBOO_LOG_MAX_CHARS:
        head = log_text[: bc.BAMBOO_LOG_HEAD_CHARS]
        tail = log_text[-bc.BAMBOO_LOG_TAIL_CHARS :]
        dropped = (
            len(log_text) - bc.BAMBOO_LOG_HEAD_CHARS - bc.BAMBOO_LOG_TAIL_CHARS
        )
        log_text = (
            head
            + f"\n\n... [{dropped:,} chars truncated from middle] ...\n\n"
            + tail
        )
    return log_text


def download_job_logs(
    *,
    plan_key: str,
    branch: str,
    build_number: int,
    jobs: list[dict],
    out_dir: Path,
    failed_only: bool,
    prefix_mode: bool,
) -> list[Path]:
    import bamboo_client as bc

    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    targets = jobs
    if failed_only:
        targets = [j for j in jobs if j.get("state") == "Failed"]
        if not targets:
            eprint("INFO: No failed jobs; downloading all job logs.")
            targets = jobs

    for job in targets:
        job_key = job.get("job_key", "")
        if not job_key:
            continue
        eprint(f"INFO: Downloading {job_key} ({job.get('state', '?')})")
        if prefix_mode:
            log_text = fetch_job_log_by_key(job_key)
        else:
            log_text = bc.get_build_logs(
                plan_key,
                branch,
                build_number,
                job_key=job_key,
            )
        dest = out_dir / f"{job_key}.log"
        dest.write_text(log_text, encoding="utf-8")
        saved.append(dest)
        eprint(f"INFO: Wrote {dest} ({len(log_text):,} chars)")

    return saved


def download_lock_artifact(build_result_key: str, jobs: list[dict], out_dir: Path) -> Path | None:
    import bamboo_client as bc

    lock_jobs = [
        j for j in jobs
        if LOCK_JOB_SUFFIX in (j.get("job_key") or "").upper()
    ]
    if not lock_jobs:
        eprint(
            f"INFO: No {LOCK_JOB_SUFFIX} job in build; "
            f"skipping {LOCK_ARTIFACT}."
        )
        return None

    job_key = lock_jobs[0]["job_key"]
    try:
        files = bc.download_artifact(job_key, LOCK_ARTIFACT)
    except ValueError as exc:
        eprint(f"WARNING: Could not download {LOCK_ARTIFACT}: {exc}")
        return None

    dest = out_dir / LOCK_ARTIFACT
    for name, data in files.items():
        dest.write_bytes(data)
        eprint(f"INFO: Wrote artifact {dest} ({len(data):,} bytes)")
        return dest
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download Bamboo build logs for Judo CI. "
            "Uses token.txt and bamboo_client.py."
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Manifest-judo root (default: auto-detect or skill parent).",
    )
    parser.add_argument(
        "--plan",
        default=DEFAULT_PLAN,
        help=f"Bamboo plan key (default: {DEFAULT_PLAN}).",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help=(
            "VCS branch name. Default: current git branch when not using "
            "--prefix."
        ),
    )
    parser.add_argument(
        "--build",
        type=int,
        default=None,
        help="Build number. Default: latest for the branch.",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help=(
            "Branch plan result prefix, e.g. CC-JUDO1324. Requires --build. "
            "Skips VCS branch resolution."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "Output directory (default: bamboo_logs/build<N> under workspace)."
        ),
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help="Bamboo PAT file (default: token.txt in workspace root).",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Bamboo server URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Download only failed job logs (default: all jobs).",
    )
    parser.add_argument(
        "--no-artifact",
        action="store_true",
        help=f"Skip downloading {LOCK_ARTIFACT}.",
    )
    parser.add_argument(
        "positional",
        nargs="*",
        help=(
            "Optional shorthand: '<branch>' | 'build N' | "
            "'<prefix> <build>'."
        ),
    )
    return parser.parse_args(argv)


def apply_positional(args: argparse.Namespace) -> None:
    pos = list(args.positional or [])
    if not pos:
        return

    if len(pos) == 1:
        token = pos[0]
        lower = token.lower()
        if lower in ("current", "current-branch", "here"):
            return
        if lower.startswith("build"):
            parts = lower.split()
            if len(parts) == 2 and parts[1].isdigit():
                args.build = int(parts[1])
                return
        if PREFIX_RE.match(token):
            raise SystemExit(
                f"ERROR: Prefix {token} requires a build number "
                "(e.g. CC-JUDO1324 4)."
            )
        args.branch = token
        return

    if len(pos) == 2 and pos[1].isdigit() and PREFIX_RE.match(pos[0]):
        args.prefix = pos[0].upper()
        args.build = int(pos[1])
        return

    if len(pos) == 2 and pos[0].lower() == "build" and pos[1].isdigit():
        args.build = int(pos[1])
        return

    raise SystemExit(
        "ERROR: Unrecognized positional args: "
        + " ".join(pos)
        + ". See --help."
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    apply_positional(args)

    repo_root = find_judo_root(args.workspace)
    token_file = args.token_file or (repo_root / "token.txt")
    setup_bamboo_env(token_file, args.base_url)

    branch = args.branch
    if not args.prefix and not branch:
        branch = current_git_branch(repo_root)

    build_result_key, build_number, vcs_branch, status = resolve_build(
        plan_key=args.plan,
        branch=branch,
        build_number=args.build,
        prefix=args.prefix,
    )

    out_dir = args.out_dir or (repo_root / "bamboo_logs" / f"build{build_number}")

    print(f"Plan: {args.plan}")
    print(f"Branch: {vcs_branch}")
    print(f"Build: #{build_number} ({status.get('state', 'Unknown')})")
    print(f"Result key: {build_result_key}")
    print(f"Output: {out_dir}")
    browse = (
        f"{os.environ['BAMBOO_BASE_URL']}/browse/"
        f"{build_result_key.rsplit('-', 1)[0]}-{build_number}"
    )
    print(f"Browse: {browse}")

    jobs = list_build_jobs(build_result_key)
    if not jobs:
        raise SystemExit(
            f"ERROR: No jobs found for build result {build_result_key}."
        )

    print("\nJobs:")
    for job in jobs:
        print(
            f"  - {job['job_key']} | {job['stage']} | "
            f"{job['job_name']} | {job['state']}"
        )

    saved = download_job_logs(
        plan_key=args.plan,
        branch=vcs_branch,
        build_number=build_number,
        jobs=jobs,
        out_dir=out_dir,
        failed_only=args.failed_only,
        prefix_mode=bool(args.prefix),
    )

    artifact_path = None
    if not args.no_artifact:
        artifact_path = download_lock_artifact(
            build_result_key, jobs, out_dir
        )

    print("\nFinal result")
    print(f"  Downloaded {len(saved)} log file(s) to {out_dir}")
    if artifact_path:
        print(f"  Artifact: {artifact_path}")
    failed_jobs = status.get("failed_jobs") or [
        j["job_key"] for j in jobs if j.get("state") == "Failed"
    ]
    if failed_jobs:
        print("  Failed jobs:")
        for key in failed_jobs:
            print(f"    - {key}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
