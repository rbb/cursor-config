---
name: bamboo-download-build-logs
description: >-
  Downloads Bamboo CI build logs and default.lock.xml for Judo manifest-judo
  builds via the REST API. Resolves current git branch or an explicit branch,
  latest or numbered build, or a branch-plan prefix (e.g. CC-JUDO1324). Use when
  triaging CI failures, when the user mentions bamboo logs, build logs, or
  /bamboo-download-build-logs.
disable-model-invocation: true
---

# bamboo-download-build-logs

Download Bamboo build logs to `bamboo_logs/build<N>/` for local triage.

## Prerequisites

| Item | Value |
|------|-------|
| Server | `https://bamboo.trimble.tools` |
| Plan key | `CC-JUDO` |
| Token | `token.txt` at manifest-judo root (gitignored PAT) |
| Client | `devops/judo-devops/scripts/bamboo_client.py` |

Do **not** commit `token.txt` or `bamboo_logs/`.

## Script

`.agents/skills/bamboo-download-build-logs/scripts/bamboo_download_logs.py`

Run from manifest-judo root (or pass `--workspace`).

## Slash / natural-language mapping

| User says | Command |
|-----------|---------|
| `/bamboo-download-build-logs` | latest build, current git branch |
| `for the current branch` | same as above |
| `/bamboo-download-build-logs <branch>` | latest build for that VCS branch |
| `/bamboo-download-build-logs build 3` | build **3**, current git branch |
| `/bamboo-download-build-logs build 3 on <branch>` | build **3**, named branch |
| `/bamboo-download-build-logs CC-JUDO1324 4` | prefix mode: result `CC-JUDO1324-4` |

Positional shorthand (equivalent):

```bash
python3 .agents/skills/bamboo-download-build-logs/scripts/bamboo_download_logs.py
python3 ... feature/CSNMR-6399-fntest-loop
python3 ... build 3
python3 ... CC-JUDO1324 4
```

## CLI flags

| Flag | Meaning |
|------|---------|
| `--branch` | VCS branch (default: `git rev-parse --abbrev-ref HEAD`) |
| `--build N` | Build number (default: latest for branch) |
| `--prefix CC-JUDO1324` | Branch-plan prefix; requires `--build` |
| `--out-dir` | Override output dir (default: `bamboo_logs/build<N>/`) |
| `--token-file` | PAT file (default: `token.txt`) |
| `--failed-only` | Download only failed job logs |
| `--no-artifact` | Skip `default.lock.xml` |
| `--workspace` | Manifest-judo root when cwd is elsewhere |

## What gets downloaded

1. **Every job log** in the build (all stages), saved as
   `{job_key}.log` (e.g. `CC-JUDO1324-BUILDTSTBRDV1-4.log`).
2. **`default.lock.xml`** from the Generate Locked Manifest job when
   present.

Browse URL pattern:
`https://bamboo.trimble.tools/browse/CC-JUDO1324-<N>`

## Terminal

**Current branch, latest build:**

```bash
cd /path/to/judo
python3 .agents/skills/bamboo-download-build-logs/scripts/bamboo_download_logs.py
```

**Named branch, latest:**

```bash
python3 .agents/skills/bamboo-download-build-logs/scripts/bamboo_download_logs.py \
  --branch feature/CSNMR-6399-fntest-loop
```

**Current branch, build 3:**

```bash
python3 .agents/skills/bamboo-download-build-logs/scripts/bamboo_download_logs.py \
  build 3
```

**Prefix + build number (no VCS branch lookup):**

```bash
python3 .agents/skills/bamboo-download-build-logs/scripts/bamboo_download_logs.py \
  CC-JUDO1324 4
```

## Agent behavior

When the user invokes `/bamboo-download-build-logs` or asks to download
Bamboo logs:

1. **Read** this skill.
2. Map their phrase to CLI args (table above). Ask if branch or build
   number is ambiguous.
3. **Run** the script from the integrated terminal; show its stdout.
4. After download, **summarize** for the user:
   - build number, state, result key, output directory
   - failed jobs (if any) with log file paths
   - whether `default.lock.xml` was saved
5. For triage, read failed job logs under `bamboo_logs/build<N>/`
   (tail or search for `ERROR:`). Do not paste multi-MB logs inline.
6. **Never commit** downloaded logs or the token.

## Errors to expect

| Situation | Action |
|-----------|--------|
| Missing `token.txt` | Ask user to add Bamboo PAT to repo-root `token.txt`. |
| Detached HEAD, no `--branch` | Ask for branch name or use `--prefix`. |
| Build not found | Script lists recent build numbers; pick valid `--build`. |
| Prefix without build number | Pass both, e.g. `CC-JUDO1324 4`. |

## Related

- `devops/judo-devops/scripts/bamboo_client.py` — API client
- `scripts/bamboo_fetch_default_xml.py` — bulk lock manifest fetch
- `copy-manifest-revisions` — sync lock pins into `default.xml`
