---
name: review-python
description: >-
  Reviews Python for name-binding and scoping bugs: assignment makes a name
  local for the whole function, while in-place mutation of mutable objects
  does not. Also checks import style in fntest/functional_test code:
  domain modules imported as short aliases (fnt_art, fnt_debug, fnt_exp,
  fnt_runtime) with qualified fnt_<name>.<object> calls—no compatibility
  facade modules. Use when the user runs /review-python, asks for a Python
  scoping review, UnboundLocalError risks, global/nonlocal issues, mutable vs
  rebinding mistakes, or fntest import conventions.
---

# Review Python Scoping

Python decides which names are **local to a function at compile time**.
Any **binding** to a name inside the function (`=`, `+=`, `*=`, `del`, `for`,
`except ... as`, walrus targeting that name, etc.) makes that name **local
for the entire function**, including lines above the binding.

Reads of that name then use the **local** cell, not the module or enclosing
scope, unless the name is listed in a `global` or `nonlocal` statement.

## When to use

- User invokes `/review-python` or names this skill.
- Reviewing Python diffs for subtle runtime failures (`UnboundLocalError`).
- Auditing module-level singletons, caches, flags, or shared mutable state
  used from functions.
- Reviewing `testcpu/functional_test/` (or similar) for module boundaries and
  import/call style.

## Module imports and calls (fntest functional_test)

Domain logic lives in dedicated modules. Callers import those modules with
**short aliases** and always qualify symbols as **`alias.name`**.

| Alias | Module |
|-------|--------|
| `fnt_art` | `fntest_artifacts` |
| `fnt_debug` | `fntest_debug_report` |
| `fnt_exp` | `fntest_expand` |
| `fnt_runtime` | `fntest_runtime` |

**Do:**

```python
import fntest_artifacts as fnt_art
import fntest_runtime as fnt_runtime

run_dir = fnt_runtime.DATA_DIR / stamp
fnt_art.ensure_iter_dir(run_dir, iteration)
```

**Do not:**

- Compatibility facades that re-export other modules (`fntest_loop_utils`,
  `from foo import *` barrels).
- Umbrella aliases that hide which domain owns a symbol
  (`import fntest_loop_utils as fntlu` then `fntlu.LOGS_DIR` and
  `fntlu.FtestDutTeardown` from different underlying modules).
- Bare `from fntest_loop_utils import DATA_DIR, MONITOR_LOG_GLOB` (or from any
  facade); import the owning module as `fnt_art` / `fnt_runtime` instead.

When reviewing diffs, map each symbol to its home module and flag wrong
imports, missing aliases, or unqualified names that relied on a removed
facade. Prefer **Info** for style-only drift; **Warning** when a facade or
star-import makes ownership unclear or blocks deleting shim modules.

More examples: [reference.md](reference.md#import-aliases-functional-test).

## Core rules (check mentally and with the script)

| Operation on name `N` | Effect on scope |
|----------------------|-----------------|
| Read only (`print(N)`, `N.method()`, `N[k]`, `N.attr = ...`) | Uses enclosing/global binding |
| Bind/rebind (`N = ...`, `N += ...`, `del N`, `for N in ...`) | `N` is local unless `global`/`nonlocal` |
| In-place mutate without rebinding (`N.append(x)`, `N.update(...)`) | Still a **read** of `N`; no new local unless another bind exists |

**Critical pattern:** load + bind in the same function without `global`/`nonlocal`
→ **`UnboundLocalError`** on the load if it runs before the bind assigns a value.

### Safe vs broken (module-level `FOO`)

**OK — read only:**

```python
FOO = True

def myfun():
    print(FOO)
```

**Broken — bind makes `FOO` local for all of `myfun`:**

```python
FOO = True

def myfun():
    print(FOO)  # UnboundLocalError: local 'FOO' referenced before assignment
    FOO = False
```

Same failure if the bind appears only on one branch (the name is still local
everywhere in the function):

```python
FLAG = False

def set_flag(value):
    if value:
        FLAG = True
    print(FLAG)
```

### Mutable vs immutable (rebinding)

**OK — mutate in place, no assignment to the name:**

```python
ITEMS = []

def add_item(x):
    ITEMS.append(x)
```

**Broken — assignment shadows the global:**

```python
ITEMS = []

def reset_and_add(x):
    print(len(ITEMS))  # UnboundLocalError
    ITEMS = []
    ITEMS.append(x)
```

**Note:** augmented assignment (`+=`, `*=`, ...) is binding. For immutables it
rebinds; for mutables it may call `__iadd__` but still counts as a **store**
on the name → same local-binding rules.

## Review workflow

1. **Scope the diff**
   - If the user named a path or PR, limit review to that Python tree or diff.
   - Otherwise review changed `*.py` files (staged + unstaged + branch commits
     vs merge-base with default branch), same spirit as other review skills.

2. **Run the checker** on each file or the repo root:

   ```bash
   python ~/.cursor/skills/review-python/scripts/check_scoping.py path/to/file.py
   python ~/.cursor/skills/review-python/scripts/check_scoping.py src/
   ```

   Exit code `1` when findings exist; stdout lists `file:line: rule: message`.

3. **Manual pass** (the script does not catch everything):
   - **Imports (functional_test):** aliases `fnt_art`, `fnt_debug`, `fnt_exp`,
     `fnt_runtime`; qualified calls; no `fntest_loop_utils` or equivalent
     facades (see section above).
   - Nested functions: missing `nonlocal` when outer mutable is rebound in
     inner function.
   - Class bodies: methods do **not** see class-level names as locals;
     bare `attr` is not `self.attr` (often `NameError`, not UnboundLocal).
   - `global`/`nonlocal` declarations after use (syntax error) or wrong name
     list.
   - Thread/async: module globals mutated without locks where it matters
     (separate concurrency review).

4. **Report** findings in a table:

   | Severity | Location | Finding |
   |----------|----------|---------|
   | Critical | `file:line` | One sentence + suggested fix |

   Severity guide:
   - **Critical:** definite or high-confidence `UnboundLocalError` / wrong
     binding on common paths.
   - **Warning:** load+bind pattern only on rare branches; needs human judgment.
   - **Info:** style fix (`global` declaration, rename, pass mutable as arg).

5. **Suggested fixes** (prefer in order):
   - Rename the local (e.g. `local_foo = ...`) when shadowing was accidental.
   - Pass state as an argument or attribute instead of module globals.
   - Use `global N` / `nonlocal N` only when shared mutable state is intentional.
   - Restructure so mutation uses methods on the outer object without
     rebinding the name.

Do not change code unless the user asks to fix findings.

## Script limits

`check_scoping.py` flags functions where a name is both **loaded** and
**stored** (including augmented assignment and `for`/`except as` targets),
excluding parameters and names declared `global`/`nonlocal`. It does not
prove execution order; treat every match as at least a **Warning** and escalate
to **Critical** when the load is clearly reachable before any assignment on
all paths (e.g. load at the start of the function body).

For rule details and edge cases, see [reference.md](reference.md).
