# Cursor Config

This is a repo for some global cursor config.

**Usage**:
CLAUDE.md, AGENTS.md, and `.cursor/rules/` can be copied or symbolically
linked into another project.

## User Rules (global, always apply)

If using Cursor Settings instead of project symlinks:

- Open Cursor settings (Cmd + Shift + J or Ctrl + Shift + J),
- go to General > Rules for AI,
- and paste the contents of your CLAUDE.md there.

This applies workflow and planning directives to every Agent session regardless
of the folder. Paste only the slimmed CLAUDE.md content; language-specific
style guides live in `.cursor/rules/` and should not be pasted here.

## Project symlinks

Symlink both CLAUDE.md and `.cursor/rules/` so always-apply workflows and
glob-scoped language rules are active in the project.

```bash
# Always-apply workflows and planning directives
ln -s <cursor-config repo location>/CLAUDE.md <project dir>/CLAUDE.md

# Language-specific rules (glob-scoped)
mkdir -p <project dir>/.cursor
ln -s <cursor-config repo location>/.cursor/rules <project dir>/.cursor/rules
```

Symlinking only CLAUDE.md does not activate the language rules. Both paths are
needed per project.

AGENTS.md can be linked the same way as CLAUDE.md:

```bash
ln -s <cursor-config repo location>/AGENTS.md <project dir>/AGENTS.md
```
