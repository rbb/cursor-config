# Cursor Config

This repo holds Cursor project config. Treat the repo root as the contents of a
project's `.cursor/` directory: `rules/`, `hooks/`, and `hooks.json` live here
(not under a nested `.cursor/`).

CLAUDE.md and AGENTS.md sit alongside that tree and are linked at the project
root.

**Usage**: copy or symlink into another project (see below).

## User Rules (global, always apply)

If using Cursor Settings instead of project symlinks:

- Open Cursor settings (Cmd + Shift + J or Ctrl + Shift + J),
- go to General > Rules for AI,
- and paste the contents of your CLAUDE.md there.

This applies workflow and planning directives to every Agent session regardless
of the folder. Paste only the slimmed CLAUDE.md content; language-specific
style guides live in `.cursor/rules/` and should not be pasted here.

## Project symlinks

Symlink CLAUDE.md at the project root and this repo's contents into
`<project>/.cursor/`.

**Option A — entire `.cursor` tree** (rules + hooks in one step):

```bash
ln -s <cursor-config repo location> <project dir>/.cursor
```

**Option B — piecemeal:**

```bash
# Always-apply workflows and planning directives
ln -s <cursor-config repo location>/CLAUDE.md <project dir>/CLAUDE.md

# Language-specific rules (glob-scoped)
mkdir -p <project dir>/.cursor
ln -s <cursor-config repo location>/rules <project dir>/.cursor/rules
```

Symlinking only CLAUDE.md does not activate the language rules. Link both
CLAUDE.md and `.cursor/rules` (or use option A).

AGENTS.md can be linked the same way as CLAUDE.md:

```bash
ln -s <cursor-config repo location>/AGENTS.md <project dir>/AGENTS.md
```

## Style hooks

Hooks symlinks activate post-edit style enforcement (rule injection, and
automatic formatting where tooling is available).

```bash
mkdir -p <project dir>/.cursor
ln -s <cursor-config repo location>/hooks.json <project dir>/.cursor/hooks.json
ln -s <cursor-config repo location>/hooks <project dir>/.cursor/hooks
```

(Included automatically if you used option A above.)

Symlink both `hooks.json` and the `hooks/` directory. Hooks are optional per
project but recommended when using the language style guides.

### Required tools (style hooks)

Hooks always need **Python 3** on PATH (hook scripts are `python3`; stdlib only).

Formatter/linter binaries are **optional** — hooks fail open when missing. Install
only what you use:

| Tool | Languages | Used for | Required? |
|------|-----------|----------|-----------|
| `ruff` | Python | `ruff format`, `ruff check` | Optional (hard mode) |
| `rustfmt` | Rust | post-edit formatting | Optional (hard mode) |
| `clang-format` | C/C++ | post-edit formatting | Optional (hard mode) |

**Soft mode** (rule injection only, no subprocess): TypeScript/JS, Markdown — no
extra tools.

Example installs (pick what you need):

```bash
# Python (ruff)
pip install ruff
# or: curl -LsSf https://astral.sh/ruff/install.sh | sh

# Rust (rustfmt — usually via rustup)
rustup component add rustfmt

# C/C++ (clang-format — package name varies by distro)
sudo apt install clang-format   # Debian/Ubuntu
```

At Agent session start, the `sessionStart` hook checks PATH for hard-mode tools
and logs missing binaries to the **Hooks** output channel (View → Output →
Hooks). Style enforcement still works without them; you lose automatic
post-edit formatting and Python lint feedback.
