---
name: update-src-rev
description: >-
  Pins commits into default.xml (and SRCREV when applicable). For src/<name>:
  updates SRCREV, aligns the meta-layer branch, and pins source plus recipe
  SHAs. For oe/meta-judo*: pins the layer HEAD in default.xml only. Supports
  one repo or "for each of" multiple repos. Use when preparing a PR branch,
  pinning a source or meta layer, or when the user mentions update-src-rev.
disable-model-invocation: true
---

# update-src-rev

Pin a commit into `default.xml` (and the Yocto recipe when a **source
repo** is named).

## Repo argument: `src/` vs `oe/`

The script classifies each repo argument automatically:

| Argument style | Example | Mode |
|----------------|---------|------|
| Source repo | `mqtt-api`, `src/mqtt-api` | Full skill (three steps) |
| Meta layer | `meta-judo`, `oe/meta-judo-proprietary` | Manifest-only pin |

**Do not** treat `oe/meta-judo*` as an error or ask how to proceed.
Pass `meta-judo` (or `oe/meta-judo`) directly.

### Source repo (`src/<name>`) — four steps

| Step | Git repo | Artifact |
|------|----------|----------|
| 1 | `oe/meta-judo*` | Matching branch + `SRCREV` commit |
| 2 | Manifest (workspace root) | Source `<project revision>` |
| 3 | Manifest (workspace root) | Recipe-layer `<project revision>` |
| 4 | Manifest (workspace root) | `manifest-judo` self `<project revision>` |

Step 1 reads the source SHA from the source repo `HEAD` (or `--srcrev`).
Step 3 uses the meta-layer `HEAD` **after** the recipe commit (or after
checking out the matching branch if SRCREV already matched).

Step 4 pins the `manifest-judo` project (path `.`) to the workspace
branch name so `repo manifest -r` locks manifest scripts (e.g.
`scripts/build-fntest-container.sh`) from the feature branch, not
`main`. On `main`, revision stays `main`.

### Meta layer (`oe/meta-judo*`) — manifest-only

| Step | Git repo | Artifact |
|------|----------|----------|
| Pre-flight | Meta layer + workspace | Align workspace to meta-layer branch |
| 1–2 | — | Skipped (no source repo / SRCREV) |
| 3 | Manifest (workspace root) | Meta-layer `<project revision>` → layer `HEAD` |
| 4 | Manifest (workspace root) | `manifest-judo` self revision → branch name |

Uses the meta-layer's **current branch** and **committed HEAD**. No
carrier source repo is required. Amends the manifest commit when HEAD
only changed `revision` attributes.

The old `update-src-rev-bb` and `update-src-rev-xml` skills are retired;
this skill covers both plus the meta-layer branch and recipe SHA pin.

## Three roles (do not conflate)

| Role | Location | Example |
|------|----------|---------|
| **Source repo** | `src/<name>` (HEAD -> SRCREV) | `src/mqtt-api` |
| **Meta layer** | `oe/meta-judo*` | `oe/meta-judo-proprietary` |
| **Manifest** | Workspace root (`default.xml`) | `.` (manifest-judo) |

Recipe files always live under `oe/meta-judo*`, never under `src/`.

## Pre-flight — branch alignment and main freshness

Before steps 1–3, the script checks the `main` branch in the source,
meta-layer, and workspace repositories against `origin/main`. It also
verifies that the source branch name contains no underscores.

If a main branch is **behind** `origin/main` or **missing** locally,
`--fix-preflight` fetches `origin/main` and fast-forwards or creates
local `main`. If local `main` has **diverged** from `origin/main`,
`--fix-preflight` is rejected (dry-run and apply); the user must fix
`main` manually, then re-run the skill.

**Diverged `main` recovery** (typical, per affected git repo):

```text
git checkout main
git pull origin main
git checkout <your-feature-branch>
git rebase main
```

After rebasing a meta layer, re-run update-src-rev so step 3 pins the
new meta-layer `HEAD` in `default.xml`.

If the source branch contains underscores, fixing renames the current
local source, meta-layer, and workspace branches when possible. The
remote branch is not renamed or pushed.

When **only** behind/missing `main` is reported, the agent must use
`AskQuestion` and offer:

- `yes`: pass `--fix-preflight` and let the skill make the fixes.
- `abort`: stop the skill without changing anything.
- `continue`: pass `--continue-preflight` and continue unchanged.

When **diverged** `main` is reported, offer **abort** or **continue**
only (`--continue-preflight`). Do **not** offer `--fix-preflight`.

The agent must also accept `y` for `yes`, `a`, `no`, or `n` for
`abort`, and `c` for `continue`.

The default is to stop with `PREFLIGHT: action required`; never choose
`continue` without the user's explicit choice.

If the **source repo branch name** differs from the **workspace**
branch (for example source on `main`, manifest on `feature/...`), the
skill stops unless `--continue-preflight`. Checkout the source repo on
the intended feature branch before pinning.

**Untracked-only** dirt in the source or meta layer is a warning; the
pin uses committed `HEAD`. **Tracked** uncommitted changes still require
`--allow-dirty-source` or commit/stash.

Recipe discovery prefers the canonical recipe when several `.bb` files
reference the same `src/<name>` (for example
`recipes-.../<name>/<name>_git.bb`). Pass `--recipe` when ambiguity
remains.

When the primary recipe is already pinned to source `HEAD`, the script
also scans other recipes that reference the same `src/<name>`. Any that
use a definitive assignment (`SRCREV =`, not `SRCREV ?=`) must match
source `HEAD` as well. If they lag (for example
`python3-functional-test_git.bb` while the canonical
`judo-radio-utils_git.bb` was updated), the run **errors** and lists
each stale recipe. Update them with `--recipe <path>` in separate runs,
or pass `--allow-split-src-pins` when intentional lag is expected
(recipes that only use `SRCREV ?=` are not checked).

After these checks, the script aligns the **meta-layer** and
**workspace** (manifest) repos to the **source repo branch name**:

1. If the repo already has that branch locally, check it out — but only
   when its history is compatible with the current checkout (one is an
   ancestor of the other). If histories diverge, stop with
   `PREFLIGHT: action required` unless `--recreate-branch` or
   `--continue-preflight` is passed.
2. Else if `origin/<branch>` exists, check it out as a local branch
   (same ancestry check as step 1).
3. Else create a new branch from **`origin/main`** (or local `main`).
   When the repo is not on `main`, the script stops with
   `PREFLIGHT: action required` so the agent can ask whether the new
   branch should be based on `main` or the current checkout.

To base new branches on the **current checkout** instead of `main`,
pass `--base-existing` (applies to both meta-layer and workspace):

```bash
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api --base-existing
```

When an **existing** target branch has the right name but the wrong
parent (for example workspace on `feature/SUMO-588-func-test-flicker`
and a stale local `feature/CSNMR-6399-fntest-loop` based on `main`),
pass `--recreate-branch` to run `git checkout -B <target>` from the
current checkout instead of checking out the stale branch:

```bash
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api --recreate-branch
```

After `rebase-redo`, when the manifest is still on `branch_b` and
sources are on `branch_a`, prefer `--recreate-branch` (or align branches
manually) before multi-repo `update-src-rev`.

Example: workspace on `feature/old`, source on
`feature/SUMO-588_func_test_flicker`, no matching branch yet — default
is `git checkout -b feature/SUMO-588_func_test_flicker origin/main`.
With `--base-existing` it is
`git checkout -b feature/SUMO-588_func_test_flicker feature/old`.

Only **local** branches are considered; server sync is the user's
responsibility. Push hints may include warnings when `origin/<branch>`
is missing or differs from local.

Then stage and commit the recipe (unless SRCREV already matches, or
`--no-commit` / `-n`).

Before changing SRCREV, the recipe helper checks that the **existing**
SHA in the `.bb`/`.inc` file is a commit in the source repo (`git
rev-parse <sha>^{commit}`). If it is not, the skill stops. Fetch the
source repo or confirm the recipe pin if that happens.

The previous recipe-only helper committed SRCREV but did **not** create
or switch this matching branch.

## Preconditions

1. Google Repo workspace (`.repo/` or `default.xml` + `oe/`).
2. **Source-repo mode:** feature branch checked out in the source repo
   (not detached HEAD). Meta-layer and workspace align to that branch.
   **Meta-layer mode:** feature branch checked out in the meta layer;
   workspace aligns to that branch.
3. Issue id in a branch name or `--issue`.
4. When a branch switch is required, repos being switched must be
   **clean** (commit or stash first). A dirty pin target (source repo in
   source mode, meta layer in meta-layer mode) stops pre-flight unless
   the user confirms via `--allow-dirty-source`.

## Script location

`.agents/skills/update-src-rev/scripts/update_src_rev.py` (stdlib only).

Git commit/amend helpers live in `scripts/skill_git.py` (imported, not a CLI).

## Multiple repositories

`/update-src-rev for each of <repo_a> <repo_b> <repo_c>` or
`/update-src-rev in order: <repo_a>, <repo_b>, <repo_c>` runs the full
skill once per named repo, in order. The script strips the `for each of`
and `in order:` prefixes and ignores commas in the repo list.
**Pre-flight (batch):** every named repo must be on the **same branch
name** (source repos use their current branch; meta layers use the layer
branch). If they differ, the script stops with
`PREFLIGHT: action required` unless `--continue-preflight` is passed.

Each per-repo run is otherwise independent: its own pre-flight, recipe
SRCREV (when applicable), and manifest pins.

The agent should pass every repo name to the script in one invocation
(equivalent to running the skill on each repo separately):

```bash
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api judo-rest-api cfg-mgr -n
```

Or run the script once per repo with the same flags. Do not merge repos
into a single partial run.

When more than one repo is requested, show the script output for each
repo (including `Repository N of M` banners) without collapsing them
into one summary.

## CLI

| Flag | Meaning |
|------|---------|
| `repo` … | **Required.** One or more names or paths. `src/<name>` or bare source name → three steps. `oe/meta-judo*` or bare meta name → manifest-only pin. Multiple repos run once each, in order. |
| `--workspace` | Workspace root (default: auto-detect). |
| `--recipe` | Recipe `.bb`/`.inc` override. |
| `--manifest` | Manifest path override. |
| `--srcrev` | SHA for recipe and source pin (default: source `HEAD`). |
| `--issue` | Issue id for commit messages. |
| `--no-commit` | Update files only; no commits. |
| `--base-existing` | New meta-layer/workspace branch from current checkout, not `main`. |
| `--recreate-branch` | Existing target branch diverged from current checkout; recreate target from current (`checkout -B`). |
| `--allow-dirty-source` | Pin source `HEAD` despite uncommitted source changes. |
| `--fix-preflight` | Fast-forward local `main` when behind (not diverged); rename underscores. |
| `--continue-preflight` | Continue with pre-flight issues unchanged. |
| `--allow-split-src-pins` | Do not error when other `SRCREV =` recipes lag source `HEAD`. |
| `-n` / `--dry-run` | Dry-run only; do not write, commit, or switch branches. |

Without `-n`, the script **always dry-runs all steps first**, then
applies only if every dry-run succeeds.

## Terminal

**Dry run (recommended first):**

```bash
cd /path/to/judo
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api -n
```

**Apply (dry-runs internally, then commits):**

```bash
cd /path/to/judo
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api
```

**Meta layer only (manifest pin):**

```bash
cd /path/to/judo
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  meta-judo -n
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  meta-judo
```

**Multiple repos (dry run, then apply):**

```bash
cd /path/to/judo
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api judo-rest-api cfg-mgr -n
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api judo-rest-api cfg-mgr
```

**From the source repo:**

```bash
cd /path/to/judo/src/mqtt-api
python3 ../../.agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api -n
```

## Output

The script prints **pre-flight**, **three steps**, a **final result**, then
**push hints** (with optional push warnings). The agent should show this
output as-is (or paste it), not rewrite it into a different outline.

**Dry run** (`-n`), already in sync:

```text
Pre-flight — branch alignment

  • Source: src/mqtt-api on feature/SUMO-588_func_test_flicker (clean)
  • Meta layer: oe/meta-judo-proprietary on feature/SUMO-588_func_test_flicker (already on matching branch)
  • Workspace: . on feature/SUMO-588_func_test_flicker (already on matching branch)

Step 1 — Recipe SRCREV

  • Source: src/mqtt-api on feature/SUMO-588_func_test_flicker at 677be58940df4087e254c4bb4cf0a95768f6eaa2
  • Recipe: oe/meta-judo-proprietary/recipes-python/python3-mqtt-api/python3-mqtt-api_git.bb
  • Meta layer: oe/meta-judo-proprietary (already on matching branch)
  • Outcome: SRCREV already matches source HEAD — no recipe commit would be made

Step 2 — Manifest source project

  • Project: mqtt-api → src/mqtt-api
  • Outcome: default.xml revision already matches source HEAD — no change

Step 3 — Manifest recipe project

  • Project: meta-judo-proprietary → oe/meta-judo-proprietary at dd17e9581e34a608830123ded24e366763e724cb
  • Outcome: default.xml revision already matches meta-layer HEAD — no change

Step 4 — Manifest self project (manifest-judo)

  • Project: manifest-judo → . revision feature/SUMO-588_func_test_flicker
  • Outcome: default.xml manifest-judo revision already matches workspace branch — no change


Final result

  RESULT: dry-run complete for all requested steps

  Everything is already in sync, so an apply run would make no commits or file changes.


Push hints (informational only — not executed)

  • src/mqtt-api:
    git push origin feature/SUMO-588_func_test_flicker
  • oe/meta-judo-proprietary: remote already in sync
  • .: remote already in sync

Push warnings (local vs origin; informational only)

  • src/mqtt-api: origin/feature/SUMO-588_func_test_flicker does not exist yet (first push for this repo)
```

`.` is the manifest git repo (workspace root).

**Never push.** The script never runs `git push`. The agent never runs
`git push`. Only list the push hints from the script.

## Commit messages

Each run keeps **one** commit in the recipe repo and **one** commit in
the manifest repo (both `default.xml` pins share that commit). If HEAD
already only changed `SRCREV` lines (recipe) or `revision` attributes
(`default.xml`), the skill amends that commit instead of adding another.

Recipe (meta-layer repo):

```text
{issue}:{recipe_name} Update SRCREV
```

Manifest (one commit). Title formula:

```text
{issue}:{branch} Update SRCREV
```

`{branch}` is the source-repo branch name (example:
`feature/SUMO-588_func_test_flicker`). The body lists source project
and recipe project name, path, and revision (plus recipe path and
SRCREV when known). When a manifest commit is amended for another
repo, prior project sections are kept and new ones are appended; an
existing section's `path:` value is extended with the new path instead
of replacing the whole body:

```text
SUMO-588:feature/SUMO-588_func_test_flicker Update SRCREV

Source project:
  name: mqtt-api
  path: src/mqtt-api
  revision: abc123... -> def456...

Recipe project:
  name: meta-judo-proprietary
  path: oe/meta-judo-proprietary
  revision: 111... -> 222...
  recipe: oe/meta-judo-proprietary/recipes-python/.../python3-mqtt-api_git.bb
  SRCREV: 111... -> 222...
```

## Agent behavior

When the user wants this operation:

1. **Read** this skill.
2. Confirm the repo name or names. Ask if unclear.
   - Source repo: `mqtt-api`, `src/mqtt-api` → full three-step skill.
   - Meta layer: `meta-judo`, `oe/meta-judo-proprietary` → manifest-only
     pin (default; do not ask the user to pick a carrier source repo).
   - Multiple repos: `/update-src-rev for each of mqtt-api meta-judo`
     — pass every name to one script invocation (or one per repo with
     the same flags). Each arg is classified independently.
3. Run `update_src_rev.py` with `-n` first; show the script output
   (pre-flight + three steps + final result + push hints) without
   rewriting the layout.
4. If the script exits with **`PREFLIGHT: action required`** (exit
   code 2), use **AskQuestion**. For main **behind/missing**, offer
   `yes` (`--fix-preflight`), `abort`, or `continue`
   (`--continue-preflight`). For **diverged** `main`, offer only
   `abort` or `continue` (include the recovery playbook from the
   script output). For source vs workspace branch mismatch, offer
   `abort` or `continue`. For underscore
   problems, offer `yes` (`--fix-preflight`), `abort`, or `continue`
   (`--continue-preflight`). For diverged existing target branches,
   offer `recreate` (`--recreate-branch`), `continue`
   (`--continue-preflight`, checkout stale target as-is), or `abort`.
   For new-branch base questions, offer `main` (default),
   `current` (`--base-existing`), or `abort`. For dirty-repo
   questions, resolve as before. Accept `y` for yes, `a`, `no`, or `n`
   for abort, and `c` for continue.
5. On success, run without `-n` unless the user asked for dry-run only.
6. **Report** that same layout from the script. Include push hints and
   any push warnings.
7. **Never push.** Do not run `git push` in any repo. Listing the
   hints is the whole push-related output.

## Partial failure

Commits land in **different** git repositories. If the recipe step
applies but a manifest step fails, the meta-layer commit remains. The
script prints `WARNING: partial apply` and exits non-zero. Do not
retry blindly; inspect git state in both repos before re-running.

## Errors to expect

| Situation | Action |
|-----------|--------|
| Missing repo argument | Pass one or more repo names (e.g. `mqtt-api`). |
| `meta-judo` / `oe/meta-judo*` | Manifest-only pin; not an error. Do not ask for a carrier source. |
| Multiple repos in one request | Pass all names to the script, or run once per repo. |
| Multi-repo branch mismatch | Align every named repo to the same branch, or `--continue-preflight`. |
| Failure on repo N of M | Earlier repos may already be applied; inspect git state before retry. |
| `PREFLIGHT: action required` | AskQuestion; re-run with flags or after stash. |
| Main behind or missing | Offer `--fix-preflight`, abort, or `--continue-preflight`. |
| Main diverged | Manual recovery playbook; abort or `--continue-preflight` only. |
| `--fix-preflight` with diverged main | Exit 1; never succeeds until main is fixed manually. |
| Source branch ≠ workspace branch | Checkout source feature branch; or `--continue-preflight`. |
| Branch contains `_` | Ask whether to rename, abort, or continue. |
| Dirty source (tracked) | Ask user; `--allow-dirty-source` or clean source. |
| Untracked files only | Warning only; pin uses `HEAD`. |
| Dirty meta/workspace before switch | Commit or stash; re-run. |
| New branch, not on `main` | Ask `main` vs current; `--base-existing` for current. |
| Existing target diverges from current | Ask recreate (`--recreate-branch`), continue (`--continue-preflight`), or abort. |
| `in order:` / comma-separated repo list | Parsed automatically; commas and `in order:` are stripped. |
| After `rebase-redo` | Manifest may be on `branch_b`; use `--recreate-branch` when aligning to `branch_a`. |
| Detached HEAD | Check out a named branch first. |
| Multiple recipes match | Auto-picks canonical `*_git.bb` when unique; else list paths and `--recipe`. |
| Other `SRCREV =` recipes lag | Error with paths; update via `--recipe` or `--allow-split-src-pins`. |
| After meta-layer rebase | Re-run skill to refresh step 3 manifest pin. |
| No issue in branch name | Ask for issue id or pass `--issue`. |
| SRCREV already matches | Skip recipe commit; still do branch + XML. |
| Existing SRCREV not in source | Fetch or verify the recipe pin; do not apply. |
| Re-run after skill commit | Amends HEAD if it is SRCREV- or revision-only. |

## Related skills

| Skill | When to use |
|-------|-------------|
| **update-src-rev** | Recipe, matching meta branch, both XML pins |
| **copy-manifest-revisions** | Bulk lock-manifest sync |
