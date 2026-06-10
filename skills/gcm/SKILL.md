---
name: gcm
description: >-
  Drafts Conventional Commit messages from staged git changes and runs git
  commit in the terminal. Prefers lightweight model like Gemini Flash, then
  cloud fallback. Use when the user says gcm, commit staged, or explicitly asks
  for this quick-commit workflow (not the full land-the-plane checklist).
disable-model-invocation: true
model: composer-2.5
---

# Git quick commit (gcm)

## When to use

Apply when the user wants a **staged** commit with a **Conventional Commit**
message: keywords include `gcm`, `commit staged`, or a direct request to run
this workflow.

Do **not** treat every "land the plane" mention as gcm alone; landing the plane
may include broader steps (see project CLAUDE.md).

## Steps

1. **Model requirement (priority)**
   - 1st: `Composer 2.5` 
   - 2nd: `GPT-5 mini`
   - 3rd: `Auto`

2. **Validation**

   Run `git diff --cached`. If there is no staged diff, stop and tell the user
   nothing is staged.

3. **Drafting**

   Generate a Conventional Commit message (e.g. `feat:`, `fix:`, `refactor:`).
   The message must satisfy **Git commit message requirements** below.

4. **Git commit message requirements (strict)**

   - Format: `<type>: <summary>` (Conventional Commits).
   - Subject: max 50 characters, imperative mood, no trailing period.
   - Body: max 72 characters per line (when a body is used).
   - ASCII only; do not put markdown backticks inside the commit message text.

5. **Action**

   Commit via the terminal using the drafted message. Do not narrate the shell
   steps unless the user asks.
