---
name: proc-issue
description: >-
n  Process the next open beads issue: pick the highest-priority open issue,
  mark it in-progress, spawn a sub-agent to implement the fix, commit with a
  Conventional Commit message, and close the issue. Use when the user says
  "proc-issue", "process next issue", "work on the next beads issue", or
  asks to run the issue-processing loop.
disable-model-invocation: true
---

# proc-issue

Process one open beads issue end-to-end.

## Steps

### 1. Find the next issue

```bash
bd list --state open
```

Pick the first issue (highest priority / lowest ID). If there are no open
issues, stop and tell the user the queue is empty.

### 2. Gather context

```bash
bd show <issue-id>
```

Also fetch any linked predecessor issues mentioned in the description:

```bash
bd show <linked-id>
```

### 3. Mark in-progress

```bash
bd set-state <issue-id> state=in_progress
```

### 4. Survey the relevant code

Before writing the sub-agent prompt, read or grep the key source files so
the prompt contains precise file paths, line numbers, and existing patterns.
The main GUI source is usually:

```
apps/gnss_diff_gui.cpp
```

Use Grep/Read to find the relevant functions before composing the prompt.

### 5. Spawn a sub-agent

Launch a `generalPurpose` sub-agent with a prompt that includes:

- **Issue ID and title** (exact text from `bd show`)
- **Root cause hypothesis** from the description
- **Exact file path(s)** to modify, with line numbers when known
- **Existing pattern to follow** (quote the nearby code that the fix should
  mirror - e.g., pre-snapshot bool before ImGui toggle, style-stack guard
  pattern, etc.)
- **Build command**: `cmake --build /home/russ/Documents/projects/Olympus/montera/build 2>&1`
- **Commit instructions** (see Commit rules below)
- **Close instruction**: `bd close <issue-id> --reason "<one-line summary>"`
- **Return value**: ask the agent to return a summary of what changed and
  whether the build succeeded.

#### Commit rules for the sub-agent prompt

```
Commit with git commit -m "<message>" where:
- Format: <type>: <summary>  (Conventional Commits)
- Subject: max 50 characters, imperative mood, no trailing period
- Body: max 72 characters per line (when used)
- ASCII only; no markdown backticks inside the commit message text
```

### 6. Verify

After the sub-agent returns, confirm:

```bash
bd list --state open       # issue is gone from open list
git log --oneline -1       # commit exists
```

If the issue is still open (sub-agent forgot to close it), close it manually:

```bash
bd close <issue-id> --reason "<summary from sub-agent>"
```

### 7. Report

Tell the user:
- What was fixed
- The commit hash and message

## C++ code style reminders for sub-agent prompts

Include these when the issue touches C++ code:

- `snake_case` free functions, `PascalCase` classes, `m_` prefix for members
- Pre-snapshot booleans before `ImGui::Button()` to keep style-stack balanced
- `static_cast` over C casts; `nullptr` over `NULL`
- Block comment on non-obvious logic
