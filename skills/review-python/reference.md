# Python scoping reference (review-python)

## Import aliases (functional test)

`testcpu/functional_test/` splits helpers by domain. Reviewers should expect
call sites to name the **module** (via alias), not a compatibility layer.

### Alias table

| Alias | Full module | Typical contents |
|-------|-------------|------------------|
| `fnt_art` | `fntest_artifacts` | Run layout, paths, index CSV, artifact discovery |
| `fnt_debug` | `fntest_debug_report` | HTML helpers, log/syslog parsing for reports |
| `fnt_exp` | `fntest_expand` | OS snapshot expansion |
| `fnt_runtime` | `fntest_runtime` | Live loop logging, MQTT, container image, DUT teardown |

### Call style

- Pattern: `fnt_<abbrev>.<object>` where `<object>` is a function, class, or
  constant defined in that module.
- Multiple domains in one file → multiple `import fntest_* as fnt_*` lines
  (stdlib, third-party, then local imports per PEP 8).
- Type hints and docstrings: use the real module in Sphinx roles when helpful
  (`:class:`fntest_runtime.FtestDutTeardown``), not a removed facade module.

### Anti-patterns to flag

```python
# Facade / barrel — do not add or extend
import fntest_loop_utils as fntlu
from fntest_loop_utils import DATA_DIR, MONITOR_LOG_GLOB

# Wrong owner — LOGS_DIR is artifacts, not runtime
import fntest_runtime as fnt_runtime
path = fnt_runtime.LOGS_DIR  # should be fnt_art.LOGS_DIR
```

### Rough symbol ownership (not exhaustive)

Use when verifying a qualified call:

- **fnt_art:** `LOGS_DIR`, `ensure_iter_dir`, `iter_dir_name`,
  `datetime_to_filename_timestamp`, `IndexEntry`, `discover_iterations`,
  `MONITOR_LOG_GLOB`, `monitor_gnss_position_data_basename`, …
- **fnt_debug:** `esc`, `fmt_ts`, `load_syslog_entries`, `MON_LINE_TS_RE`, …
- **fnt_exp:** `expand_failed_snapshots`, `expand_iteration_snapshots`, …
- **fnt_runtime:** `DATA_DIR`, `LoopedDevice`, `FtestContainerImageCheck`,
  `FtestDutTeardown`, `setup_logging`, `parse_loglevel`, …

Packaging: `pyproject.toml` `py-modules` lists each domain module; there is
no `fntest_loop_utils` entry.

## Compile-time locals (LEGB)

For each function, the compiler collects `co_varnames`. Any name assigned
anywhere in the function body is local unless declared `global` or `nonlocal`.
Loads before the local is initialized raise `UnboundLocalError`, not a fallback
to module scope.

Operations that bind the name (non-exhaustive):

- `name = ...`
- `name += ...` and other augmented assignments
- `del name`
- `for name in ...`, `with ... as name`, `except E as name`
- `(name := ...)` walrus in that function's scope

Operations that do **not** bind the name:

- `name.append(...)`, `name[0] = ...`, `name.attr = ...` (they load `name`)
- Method calls on the object referenced by `name`

## `global` and `nonlocal`

- `global x` in a function: loads and stores of `x` refer to the module global.
- `nonlocal x` in a nested function: refer to the enclosing function's local
  `x` (must exist in an enclosing scope).

Declaring `global` after first use is a syntax error in Python 3.

## Nested functions

```python
def outer():
    count = 0

    def inc():
        count += 1  # UnboundLocalError: count is local due to +=
```

Fix: `nonlocal count` or mutate a mutable holder (`state["n"] += 1` without
rebinding `state`).

## Classes

Class statement body runs in a temporary scope. Method bodies are separate
functions; they do not treat class attributes as implicit locals:

```python
class C:
    LIMIT = 10

    def ok(self):
        return self.LIMIT

    def bad(self):
        return LIMIT  # usually NameError: global/module LIMIT, not C.LIMIT
```

## Comprehensions (Python 3)

In Python 3, `{... for x in ...}`, list/dict/set comprehensions, and generator
expressions have their own scope; the loop variable does not leak in the same
way as Python 2. Generators inside a function still close over enclosing
locals by reference (late-binding gotchas when rebinding in a loop).

## False positives to downgrade

- Name is a parameter (always bound on entry).
- Name only stored, never loaded (unused local — linter territory).
- Load and store in disjoint nested functions (outer vs inner) — the checker
  skips nested `def` bodies when analyzing an outer function.
- Intentional shadowing with immediate bind before load (rare; verify by hand).
