---
name: default-xml-check-refs
description: >-
  Verifies 40-character SHA1 revision pins in default.xml exist locally and on
  origin; for those pins only, checks alignment with the manifest git branch
  when that branch exists on the project remote (pin must equal branch tip).
  Ignores non-hash revisions (main, master, tags, etc.) for all checks. Use
  after update-src-rev, before pushing manifest changes, or for
  /default-xml-check-refs.
disable-model-invocation: true
---

# default-xml-check-refs

Only **40-character hex** `revision="…"` attributes are validated. Projects
pinned to a branch, tag, or other ref (`main`, `master`, `exp`,
`trimble/ccfs/v1.5.2`, `wrynose`, etc.) are **skipped** — no local, origin,
or branch-name checks for those lines.

## Script

`.agents/skills/default-xml-check-refs/scripts/default_xml_check_refs.py`

Run from manifest-judo root (or pass `--workspace`).

## Slash / natural-language mapping

| User says | Command |
|-----------|---------|
| `/default-xml-check-refs` | `default.xml` in workspace, full checks |
| `check manifest pins` | same |
| `check default.xml refs` | same |
| `remote only skipped` | add `--skip-remote` (local object check only) |

## CLI flags

| Flag | Meaning |
|------|---------|
| `-m` / `--manifest` | Manifest path (default: `<workspace>/default.xml`) |
| `-w` / `--workspace` | Repo workspace root (default: auto-detect) |
| `--manifest-branch` | Branch for alignment (default: `git branch` in workspace) |
| `--skip-remote` | Local only; skips origin and branch alignment |
| `--no-skip-remote` | Default: verify origin |
| `--skip-tip` | Pin may be behind `origin/{manifest-branch}` tip |
| `--no-skip-tip` | Default: pin must equal branch tip when branch exists |
| `-q` / `--quiet` | Print failures and summary only |

Exit **0** when every SHA pin passes; **1** when any check fails.

## What is checked

**SHA pins only** (`revision="[40 hex]"`):

1. **Local** — If `workspace/<path>` is a git checkout:
   - `git cat-file -t <sha>` only. Do not fetch into that repo.
   - `not_checked_out` if absent (not a failure).
   - `missing` if checked out but the object is absent (a failure).
     The checker does not fetch the object into the checkout.
2. **Origin** — `git fetch --depth=1 <url> <sha>` in a temporary repo.
   Never in the project checkout (`--depth` writes `.git/shallow`).
3. **Branch / tip** — For SHA pins only (unless `--skip-remote` or manifest
   branch unknown):
   - Manifest branch from `git branch --show-current` (or
     `--manifest-branch`).
   - If `refs/heads/<branch>` exists on the project `origin`, the pin must
     **equal** that branch tip (`git ls-remote`). An older commit on the
     branch fails with `branch=behind_tip`.
   - With `--skip-tip`, the pin need only be an ancestor of the tip
     (inclusive); `branch=ok` when on branch but not at tip.
   - If that branch is missing on the project (typical upstream OE on a
     feature manifest), `branch=n/a` (not a failure).
   - If the manifest branch is `main` and `origin/main` is missing on a
     SHA-pinned project, fail.

Non-hash revisions are not listed in the report.

Manifest URL rule: `{fetch}/{name}.git`.

## Terminal

```bash
cd /path/to/judo
python3 .agents/skills/default-xml-check-refs/scripts/default_xml_check_refs.py
```

## Agent behavior

1. **Read** this skill.
2. **Run** the script; show stdout/stderr.
3. **Summarize** SHA pin failures only (including `behind_tip`).
4. Do not commit generated output.

## Related

- `update-src-rev` — pins SHAs into the manifest (run this check after).
- `copy-manifest-revisions` — copies pins from a lock file.
- `bamboo-download-build-logs` — CI triage when sync fails on bad SHAs.
