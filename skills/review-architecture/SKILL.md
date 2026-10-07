---
name: review-architecture
description: >-
  Review code for architectural red flags, tight coupling, poor separation of
  concerns, and unused (dead), unreachable, or outdated code. Use when the user
  explicitly invokes review-architecture for an architectural code review.
disable-model-invocation: true
---

# Review Architecture

Review the requested scope for architectural red flags, tight coupling, poor
separation of concerns, and code that should be removed or updated. Suggest
how to better structure components within a scalable system.

## When to use

Apply when the user names this skill or asks for an architectural review.
Scope is a **snippet**, **file**, or **directory** the user provides. This
skill is **global**; project conventions live in the repo under review.

## Scope

1. Resolve the target path (absolute or relative to workspace root).
2. If a **snippet**: use it as the primary focus; search the repo for callers,
   duplicates, and dead branches tied to symbols in the snippet when paths are
   known.
3. If a **file** or **directory**: read application code; skip generated dirs
   (`node_modules/`, `.git/`, `venv/`, `.venv/`, `build/`, `dist/`,
   `__pycache__/`, unless the user says otherwise).
4. If the path is missing, say so and stop.

## Review approach

Copy and track:

```
Review progress:
- [ ] Scope resolved (path, languages)
- [ ] Responsibilities and dependencies mapped
- [ ] Dead / unreachable / outdated code sweep completed
- [ ] Architectural concerns ranked
- [ ] Recommendations written
```

1. Identify the component's responsibilities and dependencies.
2. Run the **dead, unreachable, and outdated code sweep** (below).
3. Flag concrete architectural concerns, ranked by impact.
4. Explain the maintenance, testing, or scaling consequence of each concern.
5. Recommend the smallest practical boundary, interface, or dependency change.
6. Distinguish must-fix design risks from optional refinements.

## Dead, unreachable, and outdated code sweep

Search the scoped code and its immediate module boundaries. Every finding
needs a **location** and **evidence** (no callers, unreachable block, stale
comment, deprecated API).

### Categories

- **Dead (unused):** Symbols with no references (helpers, exports, types,
  modules, files). Orphan config, routes, or feature entry points.
- **Unreachable:** Code after `return` / `throw` / `break` / `continue`;
  constant branches; disabled blocks; handlers that cannot run.
- **Outdated:** `@deprecated`, removal TODOs, superseded APIs, duplicate
  implementations kept "just in case", stale flags, docs for removed behavior.

### Search workflow

Run searches appropriate to the language and repo. Prefer **evidence over
guesswork**: grep or reference search, then read call sites.

1. **Entry points** — List public APIs, routes, CLI commands, handlers, and
   exported symbols in scope. For each, search the repo for imports and
   references (symbol name and re-exports).
2. **Inbound-only symbols** — Functions, classes, or modules defined in scope
   but never referenced outside their file (and not entry points) are
   **dead** candidates unless framework registration applies (plugins,
   decorators, `__all__`, reflection).
3. **Outbound dead imports** — Imports or dependencies in scope that are never
   used in that file (language-aware: linters, IDE hints, or read the file).
4. **Unreachable blocks** — Scan for early returns, exhaustive switches, and
   constant conditions; note unreachable lines.
5. **Outdated markers** — Search scoped paths for:
   - `deprecated`, `DEPRECATED`, `@Deprecated`, `# noqa: deprecated`
   - `TODO.*remove`, `FIXME.*delete`, `legacy`, `obsolete`, `old_`, `_v1`
   - Comments saying "no longer used", "replaced by", "can delete"
6. **Parallel implementations** — Two modules or classes solving the same
   problem; identify which call sites use which and whether one path is dead.

### Language and tooling

- **Python (repo or path is Python):** Follow the **python-dead-code** skill
  (Vulture) for unused functions, methods, classes, imports, and unreachable
  code. Merge Vulture results with manual grep for outdated markers and
  duplicate modules. Respect project `pyproject.toml` `[tool.vulture]` and
  `vulture_whitelist.py`.
- **TypeScript / JavaScript:** Search imports and re-exports; note
  `export`/`export default` with no importers. Check for unreachable code
  after returns. Search for `@deprecated` JSDoc and stale route files.
- **Other languages:** Use project linters or `unused` / `dead_code` checks if
  documented in the repo; otherwise reference search plus unreachable-block
  reading.

### False positives

State caveats briefly: dynamic imports, `getattr`, plugin entry points,
framework callbacks, test-only helpers, and generated code may look unused.
Do not recommend deletion without confirming no external or runtime
registration.

## Response format

Use this structure:

```markdown
## Summary
[Overall architectural assessment, including dead/outdated code themes.]

## Findings
- [Severity] [Specific concern, evidence from the snippet, and consequence.]

## Dead, unreachable, and outdated code
- [Severity] [Category: Dead | Unreachable | Outdated] [Location, evidence,
  and recommended action: delete, merge, or update callers.]

## Recommended structure
[Suggested component boundaries, interfaces, and dependency direction.]

## Example refactoring
[A concise example only when it clarifies the recommendation.]

## Out of scope / assumptions
[e.g., skipped tests; no Vulture run; snippet-only without repo search]
```

If a section has no findings, include the heading with "No issues found."

Do not invent surrounding system requirements. State assumptions and ask for
the relevant context when the snippet alone cannot support a conclusion.

## Do not

- Recommend large rewrites when deleting dead code or removing a duplicate path
  fixes the problem.
- Flag symbols as dead without a reference search (or Vulture) when the repo
  is available.
- Treat every TODO as outdated; only report when the code or comment shows
  removal intent or clear supersession.
