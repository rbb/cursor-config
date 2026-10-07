---
name: default-xml-check-refs
description: >-
  Verifies 40-character SHA1 revision pins in default.xml exist locally and on
  origin; for those pins only, checks alignment with the manifest git branch
  when that branch exists on the project remote (pin must equal branch tip).
  For src/* SHA pins, compares manifest revision to URI-associated BitBake
  SRCREV values in oe/meta-judo* recipes. Ignores non-hash revisions (main,
  master, tags, etc.) for manifest ref checks. Use after update-src-rev,
  before pushing manifest changes, or for /default-xml-check-refs.
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
| `--skip-recipe` | Skip manifest vs BitBake `SRCREV` checks |
| `--lenient-optional-src-pins` | Report stale `SRCREV ?=` pins without failing |
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

**Recipe alignment** (unless `--skip-recipe`):

- Layers: checked-out manifest projects under `oe/meta-judo*`.
- Projects: `src/*` with a 40-character manifest `revision`.
- Recipes: `*.bb` / `*.inc` with an in-tree `protocol=file` URI for
  `src/<name>`. An unnamed URI maps to `SRCREV`; `;name=foo` maps to
  `SRCREV_foo`.
- Check both `SRCREV = "…"` and `SRCREV ?= "…"`. A stale optional pin fails
  as `optional_srcrev_stale` unless `--lenient-optional-src-pins` is used.
- A source URI whose pin is assigned only through a colon override reports
  `override_srcrev_unresolved`; the checker does not guess BitBake override
  precedence.
- Fail when manifest `revision` differs from the URI-associated `SRCREV`, or
  when they match but the commit is absent from a checked-out `src/<name>`
  tree (BitBake `do_fetch` / `repo sync` failure).

Manifest URL rule: `{fetch}/{name}.git`.

## Terminal

```bash
cd /path/to/judo
python3 .agents/skills/default-xml-check-refs/scripts/default_xml_check_refs.py
```

## Agent behavior

1. **Read** this skill.
2. **Run** the script; show stdout/stderr.
3. **Summarize** manifest pin and recipe SRCREV failures (including
   `behind_tip` and `mismatch`).
4. Do not commit generated output.

## Related

- `update-src-rev` — pins SHAs into the manifest (run this check after).
- `copy-manifest-revisions` — copies pins from a lock file.
- `bamboo-download-build-logs` — CI triage when sync fails on bad SHAs.
