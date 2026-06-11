# Global Technical Preferences

## Developer Profile
- **Role:** Senior Full-Stack Engineer / Architect

## Planning & Architecture Directives

When asked to plan a new feature, write an architecture document, requirements
document, or outline a solution, you MUST pause and apply Rob Pike's Rules of
Programming before writing any implementation code:

1. **DATA DOMINATES (Pike's Rule 5 - STRICT ENFORCEMENT):** - Start your plan by exclusively defining the data structures, state, types, and schemas.
   - Do not write algorithmic steps until the data structures are firmly established.
   - Ensure the data organization makes the subsequent algorithms self-evident. Write "stupid code that uses smart objects."

2. **DEFAULT TO SIMPLICITY (Pike's Rules 3 & 4):**
   - Assume `n` (dataset size) is small unless the prompt explicitly states otherwise.
   - Do not propose "fancy," highly complex, or heavily optimized algorithms in your plan.
   - When in doubt, plan for the brute-force or standard-library approach first. Simple algorithms are less buggy and easier for us to iterate on.

3. **DEFER OPTIMIZATION (Pike's Rules 1 & 2):**
   - Do not plan for hypothetical bottlenecks.
   - Do not architect complex caching layers, premature concurrency, or speed hacks in the initial design.
   - Acknowledge that we will measure performance later and optimize only the proven bottlenecks.

Use **project specific plan files** (project_dir/.cursor/plans/), not global ones ($HOME/.cursor/plans/).

# Code Quality Standards

Language-specific style guides are in `.cursor/rules/` and attach automatically
when matching files are in context.

## Communication Rules
- If you are unsure about a file path, a dependency, or a bug fix **ask** before generating a hallucinated fix.
- When refactoring, explain *why* the new version is better (e.g., performance, readability).

## Custom Commands & Terminology

When I use the phrase **"Land the plane"**, it means to stop work and clean up.
See below for differences between beads (https://github.com/steveyegge/beads)
and non-beads projects.

### Landing the Plane for NON-beads enabled projects
    1. **Stop iterating:** No more "nice-to-have" refactors or architectural pivots.
    2. **Finalize state:** Ensure all exported functions have proper types and error handling.
    3. **Cleanup:** Remove any `console.log`, TODO comments, debug print statements, or unused imports introduced during the session.
    6. **Update issue status:** - Stage changed files to git. Run the **gcm**
       skill (`~/.cursor/skills/gcm/SKILL.md`).

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
