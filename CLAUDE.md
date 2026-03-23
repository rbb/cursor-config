# Global Technical Preferences

## Developer Profile
- **Role:** Senior Full-Stack Engineer / Architect

# Code Quality Standards

## Typscript or JS Projects
- **Style:** Clean, modular, and DRY.
- **Naming:** Descriptive variable names > short ones. Use `camelCase` for JS/TS and `snake_case` for Python.
- **Type Safety:** Always use TypeScript for JS projects. Avoid `any` like the plague.
- **Error Handling:** Don't just `console.error`; suggest robust recovery or user-facing feedback patterns.

## Communication Rules
- If you are unsure about a file path, a dependency, or a bug fix **ask** before generating a hallucinated fix.
- When refactoring, explain *why* the new version is better (e.g., performance, readability).

## Python Style Guide (PEP 8)
- Indentation: Use 4 spaces per indentation level. No tabs.
- Line Length: Maximum 79 characters. Wrap long lines.
- Blank Lines: Two lines between top-level functions/classes; one line between methods.
- Imports: Always at the top. Group in this order: standard library, third-party, local imports.
- Naming Conventions:
   - snake_case for variables, functions, and methods.
   - CamelCase (PascalCase) for classes.
   - UPPER_SNAKE_CASE for constants.
- Whitespace:
   - Avoid trailing whitespace.
   - Surround operators with one space (x = 1 + 2).
   - No spaces inside parentheses or brackets.
- Comments: Use # (hash + space). Keep lines under 72 characters
- Use PEP 484 (Type Hinting)
- All files and functions should have docstrings. Use tripe double quotes (""").

## Git Commit Message Requirements
- The Subject Line:
   - The first line should be a concise summary of the change.
   - Target: 50 Characters or less
   - Hard Limit: 72 characters or less
- The Body:
   - Hard Limit: 72 characters or less

## Markdown Style Guide

- Keep lines under 79 characters.
- Prefer '-' for bullet points.
- Perfer ASCII only characters (character values less than 0x80).

## C++ style Guide

- **Naming**:
   - `snake_case` for free functions
   - `PascalCase` for classes
   - `m_` prefix for class members
- **C/C++ mix**:
   - Fixed-width integers (`uint8_t`, `int32_t`, …) where they match external APIs.
   - `memset` zero-init for large C structs before C library calls is acceptable.
   - Prefer `nullptr` over `NULL` in new code.
- **Includes**: Prefer C++-style headers (`<cstring>`, `<cstdlib>`, `<cerrno>`) in new code; legacy files may use C headers (`<string.h>`, …).
- **Unused parameters**: When signatures are fixed by an API, mark unused parameters with `UNUSED(x)` (or equivalent) instead of leaving them silently unused.
- **Casts**: Prefer `static_cast` / `reinterpret_cast` over C casts when touching pointers or numeric conversions in new code.
- **Errors**: Distinguish library return codes from process exit codes. Fatal setup in low-level helpers may `exit(1)` after logging; higher-level code can use `try` / `catch (const std::exception &)` plus a final catch-all when appropriate.
- **Comments**: 
   - Use block comments for integration notes or non-obvious behavior.
   - TODOs that describe temporary behavior should reference a ticket ID when one exists.
- **Formatting**: Pick one brace style (e.g. K&R vs Allman) and enforce it with `clang-format`

## Rust Style Guide

- **Formatting**:
  - When initializing a project, create rustfmt.toml with:
      - comment_width = 80
      - wrap_comments = true
      - short_array_element_width_threshold = 40,
      - unstable_features = true.
  - Keep line comments roughly within the configured comment width.
- **Naming**:
  - Wire/protocol constants: SCREAMING_SNAKE_CASE
  - Types: PascalCase.
  - Functions and locals: snake_case.
  - Enums tied to on-the-wire values: #[repr(...)], FromPrimitive / num_enum where used, and a short comment when variant order matters
- **Comments and section breaks**:
  - Use /// on public items that need a stable contract (example: GIT_VERSION / RELEASE_VERSION).
  - Inside large modules, long runs of / characters separate major sections
  - Prefer comments that explain protocol, hardware, or receiver-specific behavior, not a line-by-line repeat of the code.
- **CLI Arguments**:
  - Define commands with xflags! and document flags and subcommands with /// so --help stays accurate.
- **Clippy**:
  - When a lint is intentionally ignored, use a narrow #[allow(...)] next to the match or statement and add a short comment if the
    reason is not obvious (handler.rs and from_str_radix).
- **Consistency for new code**:
  - Prefer propagating errors over bare unwrap() / expect() unless the invariant is obvious or matches surrounding legacy style.
  - Double-check spelling in public function parameters and type names so APIs stay clear over time.


## Custom Commands & Terminology

When I use the phrase **"Land the plane"**, it means to stop work and clean up.
See below for differences between beads (https://github.com/steveyegge/beads)
and non-beads projects.

### Landing the Plane for NON-beads enabled projects
    1. **Stop iterating:** No more "nice-to-have" refactors or architectural pivots.
    2. **Finalize state:** Ensure all exported functions have proper types and error handling.
    3. **Cleanup:** Remove any `console.log`, TODO comments, debug print statements, or unused imports introduced during the session.
    6. **Update issue status:** - Stage changed files to git. Print a potential commit message.

### Landing the Plane for beads enabled projects
**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds.

## Session Completion (Landing the Plane)

**When ending a work session**, you MUST complete ALL steps identified for **"Land the plane"**.

