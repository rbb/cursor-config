# Pike's Rules — Detection Reference

Source: [Rob Pike's 5 Rules of Programming](https://www.cs.unc.edu/~stotts/COMP590-059-f24/robsrules.html)

Use this file when classifying findings. Not every pattern is a violation;
weigh intent, domain size, and existing project conventions.

## Rule 5 — Data dominates

If you've chosen the right data structures and organized things well, the
algorithms will almost always be self-evident.

### Positive signals (call out in Strengths)

- Named structs/classes/dataclasses/enums for domain concepts
- Schemas (JSON Schema, OpenAPI, SQL migrations) defined before handlers
- Pure functions that take typed inputs and return typed outputs
- State machines where states are explicit types or enums
- "Stupid" orchestration: load object, call methods, persist object
- Algorithm reads as obvious steps over well-chosen structures

### Violation signals

| Pattern | Why it violates | Typical recommendation |
| ------- | --------------- | ---------------------- |
| Wrong structure for the problem | Forces convoluted algorithms | Pick structure that makes steps obvious |
| `dict[str, Any]` or `object` for domain records | Hidden shape, runtime errors | Introduce dataclass/TypedDict/interface |
| Tuple returns `(a, b, c)` for named fields | Callers index by position | Named record or small result type |
| String keys for enums (`status == "active"`) | Typos, no exhaustiveness | Enum or sealed union |
| God object mutating many concerns | Algorithms entangled with state | Split by aggregate/root entity |
| Parallel arrays / index alignment | Easy to desync | Zip into records or one collection |
| Callback soup without event types | Unclear contracts | Typed event/command objects |

### Refactor patterns (prefer in order)

1. Choose or extract the **right data structure** for the domain
2. Move validation onto the type (constructor, factory, method)
3. Replace algorithm branches with **data-driven** tables/maps keyed by enum
4. Shrink functions to **orchestration** over smart objects

## Rule 4 — Simple algorithms and data structures

Fancy algorithms are buggier than simple ones, and they're much harder to
implement. Use simple algorithms as well as simple data structures.

### Positive signals

- Straightforward loops over explicit data structures
- Stdlib algorithms (`sort`, `sorted`, `find`, `filter`, maps/sets)
- One obvious implementation path a junior could maintain
- Simple data structures (list, dict, set) matching the problem

### Violation signals

| Pattern | Why it violates | Typical recommendation |
| ------- | --------------- | ---------------------- |
| Custom sort when `sort`/`sorted` suffices | Harder to implement correctly | Use stdlib; add key if needed |
| Hand-rolled linked tree for flat input | Bug-prone invariant maintenance | List + dict parent map, or nested dict |
| Generic `<T>` with single instantiation | Complexity tax | Concrete type until second use exists |
| Plugin/registry for one backend | Indirection without benefit | Direct call or simple if/branch |
| DFS/BFS on data that fits one pass | Algorithm overkill | Single loop or groupby |
| Builder/factory chains for 2 fields | Ceremony | Constructor or dataclass |
| Clever one-liners / dense recursion | Hard to verify | Explicit loop or named steps |
| Unused variable or chain of unused variables | Dead data flow obscures the real computation | Remove the unused assignments and dependent dead chain |
| Thin delegator (zero-logic rename) | Extra indirection; name alone is not domain logic | Inline callee or one entry point everywhere |
| Wrapper that only fixes an argument value | Duplicates the base API without adding behavior | Call the base function with the value directly |
| Split entry point (same module) | Two ways to do the same operation | Pick one name; use it at all call sites |

### Simple-code checks

- Trace unused assignments through their consumers. If an unused variable is
  derived from other variables or feeds assignments whose results are also
  unused, flag the full dead-data chain and recommend removing it together.

### Thin-wrapper decision test

A function is a **thin delegator** when its body is essentially:

- `return callee(...)` (or an equivalent one-liner), and
- every argument is omitted (callee defaults), passed through unchanged,
  or is a literal constant.

**Flag (Rule 4, usually Low)** unless at least one **keep** condition holds.

**Keep** (do not flag as thin wrapper):

1. **Different defaults or arguments** — wrapper fixes parameters the
   caller should not repeat (including `True`, enum values, paths).
2. **Policy / validation** — documents or enforces pre/post conditions,
   logging, metrics, or error translation.
3. **Stable boundary** — documented public API (package export, CLI
   surface, semver) where the callee is internal (`_foo`).
4. **Real implementation elsewhere** — wrapper is not a pure rename;
   siblings in a naming family each contain non-trivial logic (for
   example `local_iso_timestamp()` formats time; it is not a delegator).

**Do not treat as "domain meaning" by itself:**

- A shorter or more specific *name* when the callee already documents the
  same operation and accepts the same defaults (for example
  `local_filename_timestamp()` calling `datetime_to_filename_timestamp()`).
- **Multiple call sites** — reuse alone does not justify a zero-logic layer.

**Also flag (Rule 5, Low or Medium):** the same operation is reachable via
a thin delegator in some places and a direct callee call in others within
one module (split front door).

Convenience wrappers that encode a constant argument without other behavior
follow the same test; prefer a direct `_do_myfun(True, ...)` call unless
the wrapper satisfies a **keep** condition above.

### When complexity may be OK (usually Low or omit)

- Published library API with multiple backends
- Correctness requires a known algorithm (crypto, geometry) with tests
- Regulatory requirement with documented rationale

## Rule 3 — Fancy algorithms when n is small

Fancy algorithms are slow when n is small, and n is usually small. Fancy
algorithms have big constants. Until you know that n is frequently going to be
big, don't get fancy.

### Positive signals

- Linear scans over small collections
- Simple structures chosen for expected n
- "Brute force" that is fast enough at real n

### Violation signals

| Pattern | Why it violates | Typical recommendation |
| ------- | --------------- | ---------------------- |
| Streaming/chunk API over in-memory list | Assumes large n without proof | Read all, process simply; note n |
| BST/heap for dozens of items | Big constants beat benefit | `list` + linear search or `dict` |
| Premature indexing (secondary maps, trie) | Maintenance cost at small n | Single pass or one dict |
| Batch/tuning APIs for tiny workloads | Fancy path unused | Direct processing |
| Micro-optimized hot path at tiny n | Rule 2 not satisfied either | Simple code; measure if n grows |

### When complexity may be OK

- User or code comment documents large `n` or SLA
- Benchmarks in repo show n is frequently big (then still apply Rule 2)

## Rule 1 — Don't second-guess bottlenecks

You can't tell where a program is going to spend its time. Bottlenecks occur
in surprising places, so don't try to second guess and put in a speed hack
until you've proven that's where the bottleneck is.

### Positive signals

- Simple code path with no speculative performance infrastructure
- Optimizations isolated and tied to a identified hot spot

### Violation signals

| Pattern | Why it violates | Typical recommendation |
| ------- | --------------- | ---------------------- |
| `@lru_cache` / global cache on cheap pure fn | Assumed hot spot | Remove cache; profile if needed |
| Thread pool for handful of tasks | Assumed parallel bottleneck | Sequential loop |
| Manual cache dict + TTL without metrics | Guessed bottleneck | Delete; add when profiling shows need |
| `sync.Pool`, object pools in app code | Assumed allocation hotspot | Allocate normally |
| Parallel map over tiny collections | Wrong bottleneck guess | Simple for-loop |
| Redis/distributed cache for local data | Surprising-place fallacy | In-process struct; measure first |

### Safe wording for recommendations

- "Remove X until profiling shows this path is the bottleneck ..."
- "Replace pool with sequential Y; revisit only if proven hot ..."

## Rule 2 — Measure before tuning

Measure. Don't tune for speed until you've measured, and even then don't
unless one part of the code overwhelms the rest.

### Positive signals

- Benchmark or profiler citation before optimization
- One dominant hot path optimized; rest left simple
- Performance tests or metrics guarding tuned code

### Violation signals

| Pattern | Why it violates | Typical recommendation |
| ------- | --------------- | ---------------------- |
| Batch size / buffer tuning constants | Tuned without baseline | Fixed simple batch or no batching |
| Many `@lru_cache` / memo sites | Scatter tuning | Profile; optimize one overwhelming part |
| SIMD intrinsics / bit-twiddling | No measurement cited | Simple code; bench if needed |
| Config knobs for throughput/latency | Knobs without data | Remove knobs; measure then tune |
| Optimizing cold paths "while we're here" | Non-dominant code tuned | Revert; focus on measured hotspot |
| React `useMemo`/`memo` everywhere | Tuning without proof | Plain components until profiled |

### Safe wording for recommendations

- "Add benchmark before keeping this optimization ..."
- "Tune only X after measurement shows it overwhelms Y ..."

## Cross-cutting examples

### Rule 5 — Before / after

**Before:** function parses CSV rows into list of dicts, 200 lines of `row["x"]`.

**After:** `Row` dataclass + parser returns `list[Row]`; business logic uses
attributes; algorithm is obvious.

### Rule 4 — Before / after

**Before:** custom merge sort for 20-item list (~40 lines).

**After:** `sorted(items, key=...)`.

### Rule 3 — Before / after

**Before:** binary search tree for in-memory tag lookup (~80 lines).

**After:** `dict[str, Tag]` — O(1) at expected n with less code.

### Rule 1 — Before / after

**Before:** Redis cache wrapper around config loaded once at startup.

**After:** load config into module-level immutable struct; no cache layer.

### Rule 2 — Before / after

**Before:** three different batch sizes tuned by guesswork across pipeline.

**After:** single simple batch; one benchmark script; tune only step that
profile shows dominates.

## Language-specific quick scans

| Language | Rule 5 | Rule 4 / 3 | Rule 1 / 2 |
| -------- | ------ | ---------- | ---------- |
| Python | dataclasses, TypedDict vs dict; split entry points for same helper | thin delegators (`return foo(...)` only); itertools vs manual; trees for tiny n | lru_cache; ThreadPoolExecutor without profile |
| TypeScript | interfaces vs `any`; Zod schemas | custom utils vs array methods | memo/useMemo without profiling |
| Go | structs vs `map[string]interface{}` | goroutines for small work | sync.Pool; premature channels |
| Rust | newtypes, enums vs raw primitives | Arc/Mutex everywhere at small scale | custom allocators without bench |
| C/C++ | structs before void* APIs | manual memory pools | SIMD intrinsics without proof |

Adjust for project norms but default to Rule 3's "n is usually small" unless
the repo states otherwise.

**Python scan hints (Rule 4 thin delegators):** read functions whose body is
only `return callee(...)`; in the same file, search the callee name for both
wrapper and direct call sites (split entry point).
