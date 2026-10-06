---
name: review-pikes-rules
description: >-
  Reviews a file or directory for alignment with Rob Pike's 5 Rules of
  Programming (measure first, simple algorithms, data dominates). Produces
  prioritized refactor recommendations with evidence. Use when the user asks
  for a Pike's rules review, Pike review, review-pikes-rules, simplicity
  audit, or premature-optimization check on code or a directory.
disable-model-invocation: true
---

# Pike's Rules Code Review

Source: [Rob Pike's 5 Rules of Programming](https://www.cs.unc.edu/~stotts/COMP590-059-f24/robsrules.html)

## When to use

Apply when the user names this skill or asks to review code against Pike's
rules. Scope is **one file** or **one directory** (including recursive review
when the user passes a directory).

This skill is **global**; project conventions live in the repo under review.

## Scope

1. Resolve the target path (absolute or relative to workspace root).
2. If a **file**: read it and imports/types it depends on for context.
3. If a **directory**: enumerate source files (skip `node_modules/`, `.git/`,
   `venv/`, `.venv/`, `build/`, `dist/`, `__pycache__/`, and other generated
   dirs unless the user says otherwise). Prioritize application code over
   tests and config unless the user includes them.
4. If the path is missing or not code, say so and stop.

Read enough surrounding code to judge data flow and complexity; do not skim.

## Pike's Rules (evaluation criteria)

Use these rules **verbatim** when judging code and writing recommendations.

1. **Rule 1.** You can't tell where a program is going to spend its time.
   Bottlenecks occur in surprising places, so don't try to second guess and
   put in a speed hack until you've proven that's where the bottleneck is.

2. **Rule 2.** Measure. Don't tune for speed until you've measured, and even
   then don't unless one part of the code overwhelms the rest.

3. **Rule 3.** Fancy algorithms are slow when n is small, and n is usually
   small. Fancy algorithms have big constants. Until you know that n is
   frequently going to be big, don't get fancy. (Even if n does get big, use
   Rule 2 first.)

4. **Rule 4.** Fancy algorithms are buggier than simple ones, and they're
   much harder to implement. Use simple algorithms as well as simple data
   structures.

5. **Rule 5.** Data dominates. If you've chosen the right data structures and
   organized things well, the algorithms will almost always be self-evident.
   Data structures, not algorithms, are central to programming.

### Context (for interpretation, not extra criteria)

- Rules 1 and 2 restate Tony Hoare's maxim: "Premature optimization is the
  root of all evil."
- Ken Thompson rephrased Rules 3 and 4 as: "When in doubt, use brute force."
- Rule 5 was stated earlier by Fred Brooks; often shortened to "write stupid
  code that uses smart objects."

## Review workflow

Copy and track:

```
Review progress:
- [ ] Scope resolved (path, file count, languages)
- [ ] Rule 5: data structures and organization assessed
- [ ] Rule 4: algorithm simplicity assessed
- [ ] Rule 4: thin-wrapper sweep completed per application file
- [ ] Rule 3: fancy algorithms vs small n assessed
- [ ] Rule 1: unproven speed hacks assessed
- [ ] Rule 2: tuning without measurement assessed
- [ ] Recommendations prioritized and written
```

Evaluate **Rule 5 first**, then **Rules 4 and 3** (simplicity), then
**Rules 1 and 2** (measurement and tuning). Report findings under the
**single most specific rule** violated.

### Step 1 — Rule 5: Data dominates

For each module or cohesive unit:

- What are the core data structures, types, schemas, and state containers?
- If structures are right, are algorithms self-evident?
- Is domain state scattered (dicts, tuples, positional args) where a named
  type would make behavior obvious?
- Do algorithms manipulate opaque blobs instead of well-modeled objects?

Flag: poor data choice or organization that forces non-obvious algorithms;
primitive obsession; stringly-typed APIs; logic duplicated because data is
poorly factored.

### Step 2 — Rule 4: Simple algorithms and data structures

- Fancy or clever algorithms where a straightforward loop or stdlib call works?
- Implementations hard to follow or easy to get wrong (off-by-one, invariants)?
- Unnecessary abstraction layers (factories, strategies) for one path?
- Complex control flow where simple data + simple steps would suffice?
- Unused variables, including chains of assignments whose final result is unused?
- Thin delegators (see [reference.md](reference.md) thin-wrapper decision
  test); call-site count does not exempt them. Duplicate direct calls to the
  same callee in one module (split entry point) may be Rule 5.
- Wrappers that only encode a constant argument (for example,
  `do_myfun_on_true(...)` delegating to `_do_myfun(True, ...)`)?

Flag: custom wheels, framework-style patterns on small code, clever one-liners,
recursive solutions for flat data, dead data-flow chains, and delegating
wrappers that add no behavior or domain meaning.

#### Thin-wrapper sweep (required for each application file)

Before finishing Rule 4, list every function or method whose body is only
delegation: a single return call (optional pass-through of `self` or
`cls`), no branches, no validation.

For each delegator, apply the thin-wrapper decision test in
[reference.md](reference.md). Any function that fails the test is at least
**Low** Rule 4. If the same callee is also invoked directly elsewhere in
the module, file **Rule 5** (duplicate entry point) when that is the more
specific violation.

### Step 3 — Rule 3: Fancy algorithms when n is small

- Is `n` treated as huge without evidence (streaming, pagination, batching for
  tiny collections)?
- O(n log n) or worse structures when n is clearly small and linear is fine?
- Big-constant "fancy" structures (trees, heaps, trie) where dict/list/set
  suffices at expected n?
- Generic or optimized paths before anyone has shown large n?

Default assumption: **n is usually small** unless the repo or user says
otherwise.

### Step 4 — Rule 1: Don't second-guess bottlenecks

- Speed hacks (caches, pools, manual indexing, concurrency) without evidence
  that **this** code is the bottleneck?
- Infrastructure for hypothetical slowness ("might be slow someday")?
- Distributed or parallel patterns on local, tiny workloads?

Flag: optimization placed before understanding where time is spent.

### Step 5 — Rule 2: Measure before tuning

- Tuning knobs (batch sizes, buffer sizes, thread counts) without benchmarks
  or profiling?
- Micro-optimizations in code that is not the measured hot path?
- Optimizing many parts equally instead of the one part that overwhelms the
  rest?

Flag: performance work without measurement; scattered tuning instead of
targeting proven dominance.

### Step 6 — Write recommendations

Each finding must include:

1. **Rule** — exactly one of: Rule 1, Rule 2, Rule 3, Rule 4, or Rule 5
2. **Location** — file and symbol or line range
3. **Issue** — one sentence: what violates the rule
4. **Recommendation** — concrete refactor (new type, replace algorithm,
   delete layer, remove cache, add benchmark gate, etc.)
5. **Priority** — High / Medium / Low (see below)

Prefer **delete or simplify** over **add abstraction**. Recommend the smallest
change that fixes the violation.

For detailed detection patterns, see [reference.md](reference.md).

## Priority rubric

| Priority | Meaning |
| -------- | ------- |
| **High** | Violation makes code error-prone or blocks clarity; fix soon |
| **Medium** | Clear simplification or better data modeling; fix when touching area |
| **Low** | Style-aligned improvement; optional unless refactoring anyway |

Do not mark something High solely for micro-performance; Pike favors clarity
and measurement unless a bottleneck is proven.

Pure rename delegators with no split entry points are **Low** Rule 4. Split
entry points (thin delegator plus direct callee calls in the same module)
are **Low** Rule 4 or **Medium** Rule 5 when they confuse which API to use.

## Report format

Use this structure:

```markdown
# Pike's Rules Review: [path]

## Scope
- Target: ...
- Files reviewed: N
- Languages: ...

## Summary
[2-4 sentences: overall alignment, top themes, count by priority]

## Strengths
- [What already follows Pike's rules, with brief evidence]

## Findings by rule

### Rule 5 — Data dominates
#### [Short title] (High|Medium|Low)
- **Location:** `path:line` or `path` (`symbol`)
- **Issue:** ...
- **Recommendation:** ...

### Rule 4 — Simple algorithms and data structures
...

### Rule 3 — Fancy algorithms when n is small
...

### Rule 1 — Don't second-guess bottlenecks
...

### Rule 2 — Measure before tuning
...

## Suggested refactor order
1. [Usually Rule 5 data fixes first]
2. [Then Rule 4/3 simplifications]
3. [Remove Rule 1/2 premature tuning last unless blocking]

## Out of scope / assumptions
- [e.g., assumed small n; ignored test files; no runtime profiling]
```

If a rule has no findings, include the heading with "No issues found."

If the user asked to **implement** fixes, offer to apply recommendations in
priority order after the report. Do not refactor unless asked.

## Do not

- Recommend optimizations that violate Rules 1 or 2 while fixing Rule 5.
- Flag standard library use or idiomatic types as "too complex" under Rule 4.
- Invent large `n` or performance requirements; default to Rule 3's "n is usually
  small."
- Produce a generic essay; every finding needs a specific location.
- Review unrelated files outside the requested path.
- Bundle multiple rules into one finding; pick the most specific rule.
