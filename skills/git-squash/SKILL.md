---
name: git-squash
description: >-
  Squashes current-branch commits whose subjects start with SQUASH,
  optionally reordering via git-reorder when a target hash is named.
  Work happens on a wip branch; stops at another local branch or tag.
  Use only when the user names or attaches git-squash.
disable-model-invocation: true
---

# git-squash

- squashes commits on the current branch, that have titles starting
  with "SQUASH"
- if titles start with "SQUASH <hash>" or "SQUASH into <hash>", then
  provide a reorder list to the git-reorder skill first.
- Otherwise (starts with SQUASH, but no hash), assume that the commit
  should be squashed into the parent commit.
- Stop when another local branch or tag is reached. If unsure where to
  stop, provide a `git log --oneline` style output of the commits in
  the range of manipulation.

Read and follow `~/.cursor/skills/git-reorder/SKILL.md` whenever a
reorder list is required. Nested git-reorder must use this skill's
wip (no second wip, no mid-run approval). Do not use `git rebase -i`
or other `-i` git commands. Do not push.

## Range

Walk from `HEAD` toward the root. **Exclude** the first commit that
is pointed to by another **local** branch (`refs/heads`, not
`refs/remotes`) or a **tag**. Include every commit **after** that
commit (newer), inclusive of the child sitting on it.

Remote-tracking decorations (e.g. `origin/...`) do **not** end the
range.

Example: `main` (and/or another local branch) on `6383de1` means the
range ends at `3aafac1` inclusive and does not rewrite `6383de1`.

If the stop commit is unclear, print `git log --oneline` for the
candidate range and ask before rewriting.

## Classify subjects

Match the **first line** of each commit in the range:

- `SQUASH into <hash>` or `SQUASH <hash>`: targeted squash. `<hash>`
  may be abbreviated. Resolve with `git rev-parse --verify`.
- `SQUASH` with no hash: squash into the current parent.
- Anything else: leave as its own commit.

Keep the **target/parent** message after squash. Drop the SQUASH
subject.

## Out-of-range target

If a targeted `<hash>` is not in the rewrite range:

1. Do not rewrite yet.
2. Print `git log --oneline` for the range.
3. Tell the user the hash is out of range.
4. Prompt whether it is OK to continue.

If they continue, leave that SQUASH commit unsquashed and do not
move it toward the missing hash. If they decline, abort.

## WIP branch

Do all rewrite work on a new branch. Leave `$branch` unchanged until
approval.

```bash
skill="git-squash"
branch="$(git rev-parse --abbrev-ref HEAD)"
wip="${branch}-${skill}-wip"
```

Working tree must be clean. If `$wip` already exists, ask whether to
delete it, pick a different name, or abort.

```bash
git checkout -b "$wip"
```

On failure: `git checkout "$branch"`, leave `$wip`, do not `-M`.

## Reorder (targeted SQUASH only)

If any in-range commit is a targeted squash, build a **newest-first**
SHA list (same set as the range):

- Remove each targeted SQUASH commit from its current place.
- Insert it **immediately above** its target (newer than the target,
  older than whatever was already above the target).
- Preserve relative order among several SQUASH commits that share
  the same target.
- Leave untagged SQUASH (no hash) and normal commits in their
  relative order aside from those insertions.

Then apply git-reorder with that list on **this** `$wip`. Verify
`git diff --exit-code "$branch" HEAD` is empty.

After reorder, each targeted SQUASH commit must be a **direct
child** of its target. If not, `git checkout "$branch"` and stop.

## Squash

After any reorder, fold SQUASH commits without changing the tree.
Rebuild the range from `$parent` (parent of the oldest in-range
commit) with cherry-pick on `$wip`:

- Normal commit: `git cherry-pick <sha>`
- SQUASH (no hash, or targeted and now child of target):
  `git cherry-pick --no-commit <sha>` then
  `git commit --amend --no-edit` onto the current `HEAD` (the
  parent/target). Do not change the target message.

If `HEAD` would be a SQUASH with nothing to fold into, stop and
show `git log --oneline` for the range.

Success requires `git diff --exit-code "$branch" HEAD` empty.

## Show log and approve

Print both logs, then wait. Do not rename until the user answers.

```bash
git log --oneline "$parent".."$branch"
git log --oneline "$parent"..HEAD
```

Treat the **entire trimmed reply** as the token:

- `YES` or `Y`: replace `$branch` with `$wip` (no backup).

  ```bash
  git branch -M "$branch"
  ```

- `yes` or `Yes` or `y`: backup original `$branch`, then replace.

  ```bash
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  git branch "${branch}-${skill}-${ts}" "$branch"
  git branch -M "$branch"
  ```

Any other reply: reject. `git checkout "$branch"` then
`git branch -D "$wip"`. Report that `$wip` was deleted.

`git branch -M` must run while `HEAD` is `$wip`.

## Report

- Range used (oldest..newest) and why it stopped
- Reorder list passed to git-reorder, or none
- Which SHAs were folded into which targets
- Both `git log --oneline` listings shown for approval
- Approval token used, and backup ref if created
