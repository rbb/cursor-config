---
name: update-src-rev
description: >-
  Pins a source-repo commit into the Yocto recipe and default.xml: updates
  SRCREV, checks out or creates a matching branch in the recipe's meta-layer
  repo, commits the recipe, then pins both the source SHA and the updated
  recipe-repo SHA in default.xml. Use when preparing a PR branch, pinning a
  source repo, or when the user mentions update-src-rev.
disable-model-invocation: true
---

# update-src-rev

Pin a source-repo commit into the Yocto recipe **and** `default.xml`.

## What runs

| Step | Git repo | Artifact |
|------|----------|----------|
| 1 | `oe/meta-judo*` | Matching branch + `SRCREV` commit |
| 2 | Manifest (workspace root) | Source `<project revision>` |
| 3 | Manifest (workspace root) | Recipe-layer `<project revision>` |

Step 1 reads the source SHA from the source repo `HEAD` (or `--srcrev`).
Step 3 uses the meta-layer `HEAD` **after** the recipe commit (or after
checking out the matching branch if SRCREV already matched).

The old `update-src-rev-bb` and `update-src-rev-xml` skills are retired;
this skill covers both plus the meta-layer branch and recipe SHA pin.

## Three roles (do not conflate)

| Role | Location | Example |
|------|----------|---------|
| **Source repo** | `src/<name>` (HEAD -> SRCREV) | `src/mqtt-api` |
| **Meta layer** | `oe/meta-judo*` | `oe/meta-judo-proprietary` |
| **Manifest** | Workspace root (`default.xml`) | `.` (manifest-judo) |

Recipe files always live under `oe/meta-judo*`, never under `src/`.

## Pre-flight — branch alignment

Before steps 1–3, the script aligns the **meta-layer** and **workspace**
(manifest) repos to the **source repo branch name**:

1. If the repo already has that branch locally, check it out.
2. Else if `origin/<branch>` exists, check it out as a local branch.
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
2. Feature branch checked out in the **source** repo (not detached
   HEAD). Meta-layer and workspace (manifest) repos are aligned to that
   same branch name during pre-flight (checkout, or create from `main`
   / current checkout per user choice).
3. Issue id in a branch name or `--issue`.
4. When a branch switch is required, meta-layer and workspace repos
   must be **clean** (commit or stash first). A dirty **source** repo
   stops pre-flight unless the user confirms via `--allow-dirty-source`.

## Script location

`.agents/skills/update-src-rev/scripts/update_src_rev.py` (stdlib only).

Git commit/amend helpers live in `scripts/skill_git.py` (imported, not a CLI).

## CLI

| Flag | Meaning |
|------|---------|
| `repo` | **Required.** Name or path (`mqtt-api`, `src/mqtt-api`). |
| `--workspace` | Workspace root (default: auto-detect). |
| `--recipe` | Recipe `.bb`/`.inc` override. |
| `--manifest` | Manifest path override. |
| `--srcrev` | SHA for recipe and source pin (default: source `HEAD`). |
| `--issue` | Issue id for commit messages. |
| `--no-commit` | Update files only; no commits. |
| `--base-existing` | New meta-layer/workspace branch from current checkout, not `main`. |
| `--allow-dirty-source` | Pin source `HEAD` despite uncommitted source changes. |
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
SRCREV when known):

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
2. Confirm the **source repo** name. Ask if unclear.
3. Run `update_src_rev.py` with `-n` first; show the script output
   (pre-flight + three steps + final result + push hints) without
   rewriting the layout.
4. If the script exits with **`PREFLIGHT: action required`** (exit
   code 2), use **AskQuestion** to resolve (dirty source, dirty
   meta/workspace before switch, or `main` vs current checkout for a
   new branch), then re-run with the appropriate flags.
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
| Missing repo argument | Pass repo name (e.g. `mqtt-api`). |
| `PREFLIGHT: action required` | AskQuestion; re-run with flags or after stash. |
| Dirty source repo | Ask user; `--allow-dirty-source` or clean source. |
| Dirty meta/workspace before switch | Commit or stash; re-run. |
| New branch, not on `main` | Ask `main` vs current; `--base-existing` for current. |
| Detached HEAD | Check out a named branch first. |
| Multiple recipes match | List paths; ask which `--recipe`. |
| No issue in branch name | Ask for issue id or pass `--issue`. |
| SRCREV already matches | Skip recipe commit; still do branch + XML. |
| Existing SRCREV not in source | Fetch or verify the recipe pin; do not apply. |
| Re-run after skill commit | Amends HEAD if it is SRCREV- or revision-only. |

## Related skills

| Skill | When to use |
|-------|-------------|
| **update-src-rev** | Recipe, matching meta branch, both XML pins |
| **copy-manifest-revisions** | Bulk lock-manifest sync |
