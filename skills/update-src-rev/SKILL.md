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

## Meta-layer branch

Before writing SRCREV, step 1 uses the **current branch name** of the
source repo:

1. If the meta-layer repo already has that branch locally, check it out.
2. Else if `origin/<branch>` exists, check it out as a local branch.
3. Else create a new branch with that name from **`origin/main`** (or
   local `main` if origin is missing).

To create the new recipe-repo branch from the **current checkout**
instead of `main`, pass `--base-existing`:

```bash
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  mqtt-api --base-existing
```

Example: if `oe/meta-judo-proprietary` is on `feature/old` and the
source branch is `feature/SUMO-588_func_test_flicker` with no matching
meta branch yet, default is
`git checkout -b feature/SUMO-588_func_test_flicker origin/main`.
With `--base-existing` it is
`git checkout -b feature/SUMO-588_func_test_flicker feature/old`.

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
2. Feature branch checked out in the **source** repo. Manifest repo
   should already be on the intended feature branch.
3. Issue id in a branch name or `--issue`.

## Script location

`.agents/skills/update-src-rev/scripts/update_src_rev.py` (stdlib only).

Helpers in the same directory (do not invoke as separate skills):

- `update_src_rev_bb.py`
- `update_src_rev_xml.py`

## CLI

| Flag | Meaning |
|------|---------|
| `repo` | **Required.** Name or path (`mqtt-api`, `src/mqtt-api`). |
| `--workspace` | Workspace root (passed to helpers). |
| `--recipe` | Recipe `.bb`/`.inc` override. |
| `--manifest` | Manifest path override. |
| `--srcrev` | SHA for recipe and source pin (default: source `HEAD`). |
| `--issue` | Issue id for commit messages. |
| `--no-commit` | Update files only; no commits. |
| `--base-existing` | New recipe-repo branch from current checkout, not `main`. |
| `-n` / `--dry-run` | Dry-run only; do not write or commit. |

Without `-n`, the orchestrator **always dry-runs all steps first**, then
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

Section headers separate each step. Final line:

```text
RESULT: dry-run complete for all requested steps
```

or

```text
RESULT: apply complete (recipe SRCREV and manifest source project and
manifest recipe project)
```

Helpers print `INFO:` and `RESULT:` lines. Read those for recipe path,
meta-layer branch, SHAs, and per-step outcomes.

After `RESULT:`, the orchestrator prints push hints (workspace-relative
directories). Dry-run uses `PUSH (after apply):`. Example:

```text
PUSH:
src/mqtt-api: git push origin feature/SUMO-588_func_test_flicker
oe/meta-judo-proprietary: git push origin feature/SUMO-588_func_test_flicker
.: git push origin feature/SUMO-588_func_test_flicker
```

`.` is the manifest git repo (workspace root).

**Never push.** Scripts never run `git push`. The agent never runs
`git push`. Only list the `PUSH:` commands.

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
3. Run `update_src_rev.py` with `-n` first; show combined output.
4. On success, run without `-n` unless the user asked for dry-run only.
5. **Report** recipe path, meta-layer branch, both manifest pins, and
   the `PUSH:` lines (relative directory + `git push origin <branch>`).
6. **Never push.** Do not run `git push` in any repo. Listing the
   commands is the whole push-related output.

## Partial failure

Commits land in **different** git repositories. If the recipe step
applies but a manifest step fails, the meta-layer commit remains. The
orchestrator prints `WARNING: partial apply` and exits non-zero. Do not
retry blindly; inspect git state in both repos before re-running.

## Errors to expect

| Situation | Action |
|-----------|--------|
| Missing repo argument | Pass repo name (e.g. `mqtt-api`). |
| Detached HEAD in source | Check out a named branch first. |
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
