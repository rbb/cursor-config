---
name: git-archive
description: >-
  Creates a git archive zip named
  <UTC ISO datetime>_<branch>_<short hash>.zip from HEAD. Use when the user
  says git-archive, git archive, or asks for a zip snapshot of the repo.
disable-model-invocation: true
---

# git-archive

Create a zip of the current `HEAD` tree with `git archive`.

## Naming

```text
YYYY-MM-DDTHHMMSSZ_<branch>_<short-hash>.zip
```

Example: `2026-08-03T183923Z_main_2de0e14.zip`

- Timestamp: UTC via `date -u +%Y-%m-%dT%H%M%SZ`
- Branch: `git rev-parse --abbrev-ref HEAD`
- Hash: `git rev-parse --short HEAD`

## Steps

1. Confirm the cwd is a git repository (`git rev-parse --is-inside-work-tree`).
2. Build the filename and archive `HEAD` into the repo root:

```bash
NAME="$(date -u +%Y-%m-%dT%H%M%SZ)_$(git rev-parse --abbrev-ref HEAD)_$(git rev-parse --short HEAD).zip"
git archive --format=zip -o "$NAME" HEAD
ls -lh "$NAME"
```

3. Report the created path and size. Do not commit or push the zip unless asked.

## Notes

- Archives tracked files at `HEAD` only (untracked/ignored files are omitted).
- Default ref is `HEAD`. If the user names another ref/commit, substitute it for `HEAD` and still use that ref's short hash in the filename (`git rev-parse --short <ref>`), keeping the current branch name unless they ask otherwise.
