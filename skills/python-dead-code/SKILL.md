---
name: python-dead-code
description: >-
  Runs Vulture to find dead Python code (unused functions, methods, classes,
  variables, imports, attributes, unreachable code). Emphasizes functions and
  methods in the report. Respects per-project pyproject.toml and optional
  vulture_whitelist.py. Use when the user asks for Python dead code, Vulture,
  dead code, unused functions, or static unused-code analysis on Python.
disable-model-invocation: true
---

# Python dead code (Vulture)

## When to use

Apply when the user wants a **Vulture** pass over Python: dead code, unused
functions, dead imports, or "what can I delete." This skill is **global**;
whitelist files and `pyproject.toml` stay **per project**.

## Prerequisites

- Vulture must be available: `python3 -m vulture --version` or `vulture
  --version`.
- If missing, suggest: `pip install vulture` (or add to the project's dev
  dependencies).

## Configuration precedence

1. **`pyproject.toml`** at the config path (default: `./pyproject.toml` resolved
   from the working directory): section **`[tool.vulture]`** defines `paths`,
   `exclude`, `ignore_decorators`, `ignore_names`, `min_confidence`, etc.
2. **CLI arguments override** TOML when both are present.

If **`[tool.vulture]`** exists with valid `paths`, prefer running Vulture from
the directory that contains that `pyproject.toml`, or pass **`--config`** with
the absolute path to that file. Do not duplicate TOML settings on the CLI unless
the user asks for a one-off override.

### Default CLI when there is no usable `[tool.vulture]`

Use explicit paths (repository Python roots such as `src/`, `lib/`, or the
paths the user names). Combine layers:

| Layer | Purpose |
| ----- | ------- |
| **`--min-confidence 60`** | Unused functions/methods/classes report at **60%** confidence; threshold **80** hides those findings—avoid high thresholds unless the user only wants high-confidence items (imports, unreachable code). |
| **`--exclude`** | Comma-separated patterns (see below). Repeat noisy dirs first. |
| Project **`vulture_whitelist.py`** | If present at project root (or path the user gives), append it as the **last** positional argument so known dynamic/false positives are suppressed. |

**Suggested default `--exclude` patterns** (merge with project needs):

`venv,.venv,env,.env,__pycache__,build,dist,.git,.tox,.nox,*egg-info`

Also exclude **`tests/`**, **`test/`**, or `**/tests/**` when the goal is
production dead code only (pytest discovers tests dynamically; Vulture often
flags fixtures and helpers).

### Per-project whitelist (`vulture_whitelist.py`)

- **Scope:** One whitelist per codebase; commit it if the team wants shared
  documentation of intentional "looks dead" symbols; otherwise `.gitignore`
  is acceptable.
- **Usage:** `vulture <paths...> vulture_whitelist.py` — whitelist last.
- **Bootstrap:** From project root, after a normal run:

  `python3 -m vulture --make-whitelist <paths> > vulture_whitelist.py`

  Then **edit** the file: remove entries that are truly dead; keep stubs for
  false positives (dynamic imports, plugin entry points, framework callbacks).

### Example `[tool.vulture]`

```toml
[tool.vulture]
min_confidence = 60
paths = ["src"]
exclude = ["tests/", "build/", ".venv/"]
```

Keys match CLI flags with underscores; lists use TOML array syntax. **`paths`**
is required in TOML.

## Execution

1. Resolve the project root (workspace root or `git rev-parse --show-toplevel`
   when appropriate).
2. Check for **`pyproject.toml`** with **`[tool.vulture]`**. If present and
   valid, run Vulture with that config (from the correct cwd or `--config`).
3. Else build the CLI: paths + **`--min-confidence 60`** + default excludes +
   optional whitelist file if it exists.
4. Run **`python3 -m vulture`** if bare `vulture` is not on `PATH`.

## Reporting format (emphasize functions)

Present Vulture output grouped for readability:

1. **Unused functions and methods** — list first (file:line, name).
2. **Other unused code** — classes, variables, attributes, imports, unreachable
   code.
3. **Caveats** — one short paragraph: static analysis; names used only via
   `getattr`, string imports, or framework reflection may be false positives;
   whitelist or `ignore_names` / `ignore_decorators` can refine results.

If output is large, summarize counts per category, then full detail for
functions/methods only, with a note that the rest remains in the raw log.

## Optional flags

- **`--sort-by-size`**: sort unused functions and classes by line count (helps
  prioritize large dead blocks).
- **`--verbose`**: more detail when debugging configuration.

## Do not

- Recommend **`--min-confidence 80`** as the default when the user cares about
  unused functions (those are reported at **60%**).
- Put project-specific whitelist content inside this skill; keep whitelists in
  the repository being analyzed.
