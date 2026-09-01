---
name: update-src-rev
description: >-
  Updates SRCREV in a Yocto recipe (.bb or .inc) from git rev-parse HEAD in a
  src/* repo. Auto-discovers the recipe under oe/meta-judo*; supports --recipe
  override. Stages and commits in the meta layer. Use when preparing a PR branch,
  pinning a src repo in bitbake, or when the user mentions update-src-rev.
disable-model-invocation: true
---

# update-src-rev

Pin a `src/<repo>` commit into the matching Yocto recipe before opening a PR.

## Goal

1. Run `git rev-parse HEAD` in the **src repo** with your feature changes.
2. Write that SHA into the matching **`SRCREV`** in `oe/meta-judo*`.
3. **Stage and commit** in the meta-layer repo with:
   `{issue}:{recipe_name} Update SRCREV`

## Preconditions

1. Google Repo workspace (`.repo/` or `default.xml` + `oe/`).
2. Feature branch checked out in **both** the src repo and the meta-layer repo.
3. Branch name contains an issue id (e.g. `CSNMR-6260`, `SUMO-588`), or pass
   `--issue`.

## Script location

`.agents/skills/update-src-rev/scripts/update_src_rev.py` (relative to
workspace root). Stdlib only.

## Discovery (default)

From `src/<repo>` (or with `--src-repo`):

1. Search `oe/meta-judo`, `oe/meta-judo-bsp`, `oe/meta-judo-proprietary`, and
   other `oe/meta-judo*` layers.
2. Match `.bb` and `.inc` files that reference `src/<repo>` in `SRC_URI`,
   `EXTERNALSRC`, or `GIT_URI`.
3. **Single match** → use it. **Multiple matches** → stop; pass `--recipe`.
4. **Multi-SRCREV** recipes: update the `SRCREV_<name>` whose git URI matches
   `src/<repo>`. Stop if ambiguous.

## CLI

| Flag | Meaning |
|------|---------|
| `--workspace` | Workspace root (default: auto-detect). |
| `--src-repo` | Path to `src/<repo>` (default: infer from cwd under `src/`). |
| `--recipe` | Override auto-discovered `.bb`/`.inc` path. |
| `--srcrev` | SHA to write (default: `git rev-parse HEAD` in src repo). |
| `--issue` | Issue id for commit message (default: parse from branch). |
| `--no-commit` | Update file only; do not stage or commit. |
| `-n` / `--dry-run` | Show planned change without writing. |

## Terminal

**From workspace root:**

```bash
cd /path/to/judo
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  --src-repo src/mqtt-api -n
python3 .agents/skills/update-src-rev/scripts/update_src_rev.py \
  --src-repo src/mqtt-api
```

**From the src repo** (cwd on your feature branch):

```bash
cd /path/to/judo/src/mqtt-api
python3 ../../.agents/skills/update-src-rev/scripts/update_src_rev.py -n
python3 ../../.agents/skills/update-src-rev/scripts/update_src_rev.py
```

**Explicit recipe override:**

```bash
cd /path/to/judo/src/mqtt-api
python3 ../../.agents/skills/update-src-rev/scripts/update_src_rev.py \
  --recipe oe/meta-judo-proprietary/recipes-python/python3-mqtt-api/python3-mqtt-api_git.bb
```

**Dry run first** when unsure; remove `-n` to apply and commit.

## Commit message

Format (exact):

```text
{issue}:{recipe_name} Update SRCREV
```

Examples:

- `CSNMR-6260:python3-mqtt-api Update SRCREV`
- `SUMO-588:judo-radio-utils Update SRCREV`

`recipe_name` is the recipe filename without `_git.bb` / `.inc` suffix.

## Agent behavior

When the user wants this operation:

1. **Read** this skill.
2. Confirm cwd is under `src/<repo>` or resolve `--src-repo`.
3. Run `scripts/update_src_rev.py` from this skill directory (use an absolute
   path or `.agents/skills/update-src-rev/scripts/update_src_rev.py` from the
   workspace root).
4. Run with `-n` first; show old → new SRCREV and recipe path.
5. On success, run without `-n` to write and commit (unless user asked for
   dry-run only).
6. Do **not** push unless asked.

## Errors to expect

| Situation | Action |
|-----------|--------|
| Multiple recipes match | List paths; ask user which `--recipe` to use. |
| Ambiguous multi-SRCREV | Ask user; may need manual edit. |
| No issue in branch name | Ask for issue id or pass `--issue`. |
| SRCREV already matches HEAD | Script exits 0 with no commit. |
