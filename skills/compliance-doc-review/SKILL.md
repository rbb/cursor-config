---
name: compliance-doc-review
description: >-
  Downloads the latest Judo compliance and functional test procedure Word doc
  from Google Drive via rclone, compares it to the current judo codebase, and
  writes a findings report under /tmp. Use when the user asks for compliance
  doc review, compliance testing document accuracy, or names this skill or
  /compliance-doc-review.
disable-model-invocation: true
---

# Compliance doc review

Compare **Judo Compliance and Functional Test Setup and Procedure** (Google
Drive) against the **current workspace** (manifest-judo / judo repo). Output a
markdown report only; do not edit the Word doc unless the user asks.

## Prerequisites

- `rclone` with remote **`gdrive`** (see [setup-rclone.md](setup-rclone.md))
- `pandoc` for docx extraction
- Run from the **judo repo root** (paths below are relative to it)

### Step 0 — rclone preflight (before download)

```bash
bash .agents/skills/compliance-doc-review/scripts/check_rclone_gdrive.sh
```

If this exits non-zero, still create the report (Step 4) with a **Blocked**
summary: paste the script stderr/stdout, then add a **Rclone setup hints**
section summarizing [setup-rclone.md](setup-rclone.md) (config path
`~/.config/rclone/rclone.conf`, remote name `gdrive`, `rclone config` /
`rclone config reconnect gdrive:`). **Never** copy `client_secret`, `token`,
or other secret fields from `rclone config show` into the report.

## Workflow

Copy this checklist and track progress:

```text
Task progress:
- [ ] Step 0: rclone preflight (gdrive remote)
- [ ] Step 1: Download latest doc into archive/
- [ ] Step 2: Extract text from the .docx
- [ ] Step 3: Review claims vs codebase
- [ ] Step 4: Write /tmp/compliance_testing_doc_review_<timestamp>.md
- [ ] Step 5: Tell the user the report path
```

### Step 1 — Download

From repo root:

```bash
rclone copy gdrive:Compliance\ testing/Judo\ Compliance\ and\ Functional\ Test\ Setup\ and\ Procedure.docx archive/
```

If rclone fails, report the error in the output file (still create the report),
run Step 0 diagnostics if not already done, include **Rclone setup hints** from
[setup-rclone.md](setup-rclone.md), and stop Steps 2–3 until Drive access works.

Locate the downloaded file:

```bash
find archive -maxdepth 3 -type f -name '*.docx' -printf '%T@ %p\n' | sort -n | tail -1
```

Use the newest `.docx` if several exist.

### Step 2 — Extract text

```bash
DOCX="<absolute path to .docx>"
TS="$(date +%Y%m%d_%H%M%S)"
EXTRACT="/tmp/compliance_doc_extract_${TS}.md"
bash .agents/skills/compliance-doc-review/scripts/extract_docx.sh "$DOCX" "$EXTRACT"
```

Read `$EXTRACT` (and re-open sections of the docx via pandoc if needed).
Do not rely on memory; base findings on extracted text.

### Step 3 — Review vs codebase

1. Skim the doc structure (setup, lab, DUT, Pi, MQTT, compliance builds, etc.).
2. For each **testable claim** (commands, paths, filenames, services, topics,
   versions), verify against the repo:
   - `Grep` / `Glob` / `Read` on judo sources
   - Use [reference.md](reference.md) for where implementations usually live
3. Classify each finding:

| Status | Meaning |
|--------|---------|
| **Accurate** | Matches current repo (cite path or grep evidence) |
| **Inaccurate** | Doc contradicts repo; explain correct current behavior |
| **Stale / partial** | Partly right but missing new steps or renamed artifacts |
| **Unverified** | Could not confirm in repo (external lab, Artifactory, Bamboo only) |

Prioritize **Inaccurate** and **Stale** items that would mislead compliance or
functional test runs.

Do not copy passwords or private keys from the doc into the report; refer to
them as "document mentions credentials" only.

### Step 4 — Report file

Path (required):

```text
/tmp/compliance_testing_doc_review_<timestamp>.md
```

Use the same `TS` as extraction: `date +%Y%m%d_%H%M%S` (local time).

Write the report with this structure:

```markdown
# Compliance testing document review

- **Reviewed at:** <ISO-8601 local time>
- **Document:** <docx filename and mtime from stat>
- **Workspace:** <absolute judo repo path>
- **Git branch / HEAD:** <output of git rev-parse --abbrev-ref HEAD and short SHA>
- **Extract:** <path to EXTRACT md>

## Summary

<2–5 sentences: overall doc health, count of issues by severity>

## Findings

### Critical (would cause failed or invalid compliance test)

- ...

### Major (misleading steps or wrong artifacts)

- ...

### Minor (typos, outdated names, optional clarifications)

- ...

## Accurate sections (spot-check)

<Bullet list of major sections that matched the codebase well>

## Suggested doc updates

<Numbered, actionable edits for the Word doc owner — no file edits by agent>

## Method

<Brief note: rclone source, files searched, limits (e.g. off-repo infra)>

## Rclone setup hints

<Only when download blocked: concise steps from setup-rclone.md; no secrets>
```

### Step 5 — Handoff

Reply with the **absolute report path** and a short summary of Critical/Major
counts. Offer to drill into any finding if the user names a section.

## Agent behavior

When the user invokes this skill:

1. **Read** this file, [reference.md](reference.md), and [setup-rclone.md](setup-rclone.md).
2. **Run** Step 0, then Steps 1–2 in the terminal (network required for rclone).
3. **Investigate** the codebase; do not skip Step 3 for a generic summary.
4. **Write** the report file even if there are zero inaccuracies (say so in
   Summary).
5. Do **not** commit `archive/` or report files unless the user asks.

## Examples

**User:** `/compliance-doc-review`

Run the full workflow from the open judo workspace root.

**User:** "Check if the compliance Word doc still matches our fntest scripts"

Same workflow; emphasize `functional_test/`, recipe `files/`, and
`scp_fntest_packages.sh` in Findings.
