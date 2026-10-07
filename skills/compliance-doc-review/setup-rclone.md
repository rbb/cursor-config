# rclone `gdrive` setup (this machine)

There is no separate rclone how-to in `$HOME`; the working setup lives in:

```text
~/.config/rclone/rclone.conf
```

On a configured host, `rclone listremotes` includes **`gdrive:`** and
`rclone config show gdrive` shows **`type = drive`** and **`scope = drive`**
(OAuth token present; do not print token values in reports).

## Quick check

```bash
command -v rclone
rclone listremotes
rclone config show gdrive 2>&1 | grep -E '^(type|scope) ='
rclone lsd 'gdrive:' --max-depth 1
```

Expected remote name for the compliance skill: exactly **`gdrive`** (matches
`gdrive:Compliance testing/...` in the download command).

## First-time setup (interactive)

Run:

```bash
rclone config
```

Suggested answers (align with existing `rclone.conf` on this machine):

| Prompt | Value |
|--------|--------|
| New remote | `n` |
| name | `gdrive` |
| Storage | `drive` (Google Drive) |
| client_id | Enter (blank) unless your org requires a custom OAuth app |
| client_secret | Enter (blank) unless required |
| scope | `drive` (full access) |
| root_folder_id | Enter (blank) |
| service_account_file | Enter (blank) |
| Advanced config | `n` |
| Auto config | `y` (opens browser to sign in to Google) |
| Shared drive | `n` unless the doc lives only on a Shared drive |

Config is written to `~/.config/rclone/rclone.conf`.

Verify:

```bash
rclone lsd 'gdrive:' --max-depth 1
```

## Token / auth errors

If copy fails with auth or token errors:

```bash
rclone config reconnect gdrive:
```

Or re-run `rclone config`, choose **`e`** (edit) on `gdrive`, and refresh OAuth.

## Path note for the compliance doc

Download uses a Drive path with spaces (escaped for the shell):

```bash
rclone copy 'gdrive:Compliance testing/Judo Compliance and Functional Test Setup and Procedure.docx' archive/
```

If `lsd` works but copy fails with "directory not found", list the folder:

```bash
rclone lsf 'gdrive:Compliance testing/' --dirs-only
```

Adjust only after confirming the name in Drive; do not guess renames in the
skill text.

## Install rclone

If `command -v rclone` fails, install from your distro or
https://rclone.org/install/ (this machine has `/usr/bin/rclone`).
