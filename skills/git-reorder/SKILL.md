---
name: git-reorder
description: >-
  Reorders an existing contiguous git commit range to a user-supplied SHA
  list on a wip branch, resolves conflicts, verifies the final tree
  matches the original branch, then waits for approval to rename.
  Use only when the user names or attaches git-reorder, or asks to
  reorder commits with an explicit SHA order.
disable-model-invocation: true
---

# git-reorder

Must be provided a the desired order of git commits. Use git to reorder
the commits in the desired order, and resolve any merge conflicts along
the way. When complete, verify that the code for the final commit and
the original branch match exactly.

## Preconditions

Stop and ask if any of these fail:

- The user did not give a desired commit order as **SHAs** or as a list
  of short **SHAs** with commit title (matches the format of
  `git log --oneline`)
- The working tree is not clean.
- The listed SHAs are not a permutation of one contiguous sequence
  ending at current `HEAD` (same set, same count, same merge-base
  parent). Do not drop, add, squash, or split commits.
- The user asked to push (including force-push). Do not push.

SHA list order is **newest first** (like `git log`): the first SHA is
the desired new `HEAD`. Apply commits **oldest first** (reverse of
that list).

Do **not** use `git rebase -i`, `git add -i`, or any other `-i` git
command. Rewrite history with non-interactive `git cherry-pick`.

## WIP branch

Do all rewrite work on a new branch. Leave `$branch` unchanged until
approval.

```bash
skill="git-reorder"
branch="$(git rev-parse --abbrev-ref HEAD)"
wip="${branch}-${skill}-wip"
```

If already on a caller wip (git-squash), do **not** create another
wip and do **not** run approval here. Cherry-pick on the current
branch and verify against the caller's original `$branch`.

If `$wip` already exists, ask whether to delete it, pick a different
name, or abort.

```bash
git checkout -b "$wip"
```

## Reorder

Let `parent` be the parent of the **oldest** commit in the original
range (`git rev-parse "${oldest}^"`).

1. Record `$branch` (original tip). Stay on `$wip`.
2. `git reset --hard "$parent"`
3. Cherry-pick the listed SHAs from oldest to newest (reverse of the
   user list), one commit at a time, preserving original messages
   (`git cherry-pick <sha>`).
4. On conflict: resolve so each commit still applies **that commit's
   intent** in the new order, then `git add` and
   `git cherry-pick --continue`. Prefer resolutions that keep the
   **net tree identical** to `$branch` when all picks finish.
5. If a pick cannot be resolved without losing a commit's intent or
   the final-tree invariant, abort the cherry-pick, `git checkout
   "$branch"`, leave `$wip` in place, and report what blocked.

## Verify

After the last cherry-pick (on `$wip`):

```bash
git diff --stat "$branch" HEAD
git diff --exit-code "$branch" HEAD
```

Success only if the diff is empty (trees match exactly). Also confirm
the wip range `$parent..HEAD` is the requested SHA order, newest
first at `HEAD`.

If the trees differ: do not leave a "close enough" history.
`git checkout "$branch"` unless the user wants to keep the wip.

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

- Original `$branch` SHA and `$wip` name
- New `HEAD` SHA and newest-first order
- Conflicts resolved (files / commits), or none
- Confirmation that `git diff "$branch" HEAD` was empty before
  rename (compare using the original ref before `-M`)
- Approval token used, and backup ref if created
- Do not push
