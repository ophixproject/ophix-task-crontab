# ophix-task-crontab

Crontab Tier 2 client for [Ophix Project](https://ophix.io) task scheduling.

Fetches the task list from an Ophix task server via `ophix-task-client` and writes a managed block to a `/etc/cron.d/` file. The entire block is reconstructed on every sync.

---

## Installation

```bash
pip install ophix-task-crontab
```

`ophix-task-client` is a required dependency and is installed automatically. Bootstrap with `task-client quickstart` before using task-crontab.

---

## How It Works

task-crontab writes a sentinel-delimited block to a cron file:

```text
# --- BEGIN OPHIX-TASKS (managed by ophix-task-crontab, do not edit) ---

# --- Schedule: maintenance ---

# Nightly backup script
0 2 * * * root /opt/backup.sh | task-client report 1

# --- Schedule: reporting ---

# [paused] 30 9 * * * root /opt/report.sh
# --- END OPHIX-TASKS ---
```

- Content outside the sentinels is preserved
- Tasks are grouped by schedule, sorted alphabetically by schedule name; task order within each group mirrors the server's order
- Disabled tasks (`enabled=False`) are not returned by the server and do not appear in the block
- `[paused]` tasks (`paused=True`) are commented out so the entry is visible but inactive
- Descriptions appear as comment lines immediately above the cron entry; no name suffix is added
- One-off tasks (`run_at`) are converted to a pinned cron expression

### Output Format

| Format | When used | Line structure |
| --- | --- | --- |
| `crond` | Default when run as root | `schedule username command` |
| `user` | Default when run as non-root | `schedule command` |

Override with `--format user` or `--format crond`.

Output handling (`stdout_handling` / `stderr_handling`) on each task controls shell redirects:

| stdout | stderr | Result |
| --- | --- | --- |
| `report` | `inherit` | `command \| task-client report <id> --stream stdout` |
| `report` | `report` or `merge` | `command 2>&1 \| task-client report <id> --stream both` |
| `report` | `null` | `command 2>/dev/null \| task-client report <id> --stream stdout` |
| `report` | `file` | `command 2>>/path/to/log \| task-client report <id> --stream stdout` |
| any | `report` | `command 2>&1 >/dev/null \| task-client report <id> --stream stderr` |
| `null` | `inherit` | `command > /dev/null` |
| `file` | `merge` | `command >> /path/to/log 2>&1` |

`task-client report` receives output via a pipe (single stream). If stdin is empty, no log entry is created — pass `--force` to record an entry anyway. When both stdout and stderr go to the reporter they must be merged first — `stderr=report` and `stderr=merge` produce the same shell construct. When they go to different destinations they get independent redirects.

> **Note:** When `stderr=report`, stdout is always discarded regardless of the `stdout` setting (including `stdout=file`). The pipe requires `2>&1 >/dev/null` — the `2>&1` captures stderr into the pipe before stdout is sent to `/dev/null`, and there is no clean way to simultaneously redirect stdout elsewhere in the same construct. If you need both stdout logged to a file and stderr reported, use `stderr=file` and pipe to `task-client report` manually, or set both to `report`/`merge` and accept them interleaved.

`task-client report` is a general-purpose command and can be called from any context, not just generated cron lines:

```bash
echo "Manual note: deployed v2.3 at 14:30" | task-client report 42
some-script.sh 2>&1 | task-client report 42 --stream both
```

For non-standard handling, set both fields to `inherit` and write redirections directly in the command field — the command is written verbatim to the crontab.

---

## Commands

### `sync`

Fetch tasks and apply to the crontab.

```bash
# Non-root: writes to user crontab automatically (no --file needed)
task-crontab sync --schedule my-schedule

# Root: writes to /etc/cron.d/ophix-tasks
task-crontab sync --schedule server-maintenance

# Explicit file and user (crond format)
task-crontab sync --user www-data --file /etc/cron.d/ophix-www
```

| Argument | Default | Description |
| --- | --- | --- |
| `--schedule` | (all) | Only fetch tasks from this named Schedule |
| `--file` | auto | File to write; omit when non-root to update user crontab via `crontab -` |
| `--user` | `root` | Unix user to run tasks as (crond format only) |
| `--format` | auto | `user` or `crond`. Auto-detected from effective UID. |

When run as root without `--file`, writes to `/etc/cron.d/ophix-tasks`. When run as non-root without `--file`, reads and writes the user crontab via `crontab -l` / `crontab -`.

### `show`

Print the cron block that would be written, without writing it.

```bash
task-crontab show
task-crontab show --schedule server-maintenance --user www-data
task-crontab show --format user
```

### `install`

Add a bootstrapping sync line to the crontab, remove any duplicate entries that match tasks in the schedule, then run an immediate sync.

```bash
# Non-root: installs into user crontab
task-crontab install --schedule my-schedule

# Root: installs into /etc/cron.d/ophix-tasks
task-crontab install --schedule server-maintenance

# Custom sync interval and file
task-crontab install --schedule my-schedule --interval "*/30 * * * *" --file /etc/cron.d/ophix-www --user www-data
```

| Argument | Default | Description |
| --- | --- | --- |
| `--schedule` | (required) | Schedule name to fetch and install |
| `--interval` | `*/15 * * * *` | Cron expression for the bootstrapping sync line |
| `--file` | auto | File to write; omit when non-root to use user crontab |
| `--user` | `root` | Unix user to run tasks as (crond format only). The bootstrap sync line always runs as root regardless of this setting. |
| `--format` | auto | `user` or `crond`. Auto-detected from effective UID. |

The bootstrapping line keeps the managed block current by running `task-crontab sync` on a schedule. It is idempotent — re-running `install` will not add a second bootstrapping line. Any cron entries outside the managed block whose commands match tasks in the nominated schedule are removed to avoid duplicates.

In crond format the bootstrap sync line always runs as root (it must write to `/etc/cron.d/`). The `--user` value applies only to the task lines — tasks run as that user even if their shell is set to `/sbin/nologin`, because cron uses `/bin/sh` directly, not the configured login shell.

After `import` + `install`, the workflow is complete: tasks are on the server, the managed block is written, and the crontab self-updates going forward.

---

### `clear`

Remove the ophix-managed block from the crontab file.

```bash
task-crontab clear
task-crontab clear --file /etc/cron.d/ophix-www
```

### `import`

Parse an existing crontab and create tasks on the server. Bootstraps existing cron jobs into Ophix.

```bash
# Import current user's crontab (crontab -l)
task-crontab import --schedule server-maintenance

# Import from a specific file
task-crontab import --schedule server-maintenance --file /etc/cron.d/myapp
```

| Argument | Required | Description |
| --- | --- | --- |
| `--schedule` | Yes | Schedule name to import into |
| `--file` | No | File to read (default: `crontab -l`) |

The client must have `can_update` access to the Schedule. Tasks with a duplicate command and interval are skipped. After import, run `task-crontab sync` to apply from the server.

> **Use full paths for commands.** Cron runs with a minimal `PATH`, so bare command names like `date` or `curl` may fail at runtime. Full paths (`/usr/bin/date`) also avoid an import parsing ambiguity: the importer detects cron.d format by checking whether the first word after the schedule looks like a username, and a bare command name with no `/` can be misidentified. If you see a `command may not be blank` error during import, replace the bare command with its full path.

---

## Running Tasks as a Non-Root User

Cron jobs in `/etc/cron.d/` include a username field that controls which user the command runs as. `task-crontab` is always run by root (to write to `/etc/cron.d/`), but the tasks themselves can run as any user via the `--user` flag.

### Reporting and `.task.env` access

`task-client` reads `.task.env` to authenticate with the task server. When a task reports its output, `task-client` must be able to read this file. Keeping `.task.env` at `600` (root-readable only) is correct and recommended — service accounts should not have access to the API token.

When reporting is enabled on a task (`stdout_handling=report` or `stderr_handling=report`) and `--user` is set to a non-root account, task-crontab **automatically** generates the cron line so that:

- The task command runs as the service user via `su -s /bin/sh`
- The surrounding pipeline — including `task-client report` — runs as root

Example generated line for `--user pypiserver` with reporting enabled:

```text
*/5 * * * * root su -s /bin/sh pypiserver -c '/opt/pypiserver/venv/bin/venv-cmds check_updates' 2>&1 | /etc/tasks/.task-env/bin/task-client report 107 --stream both
```

When reporting is **not** enabled, the task runs directly as the service user with no su wrapper:

```text
*/5 * * * * pypiserver /opt/pypiserver/venv/bin/venv-cmds check_updates
```

No extra configuration is required — the correct form is selected automatically based on the task's output handling settings.

> **Note:** Users with no login shell (e.g. `pypiserver` with `/usr/sbin/nologin`) work fine. Cron and `su -s /bin/sh` both invoke commands via `/bin/sh` directly, bypassing the configured login shell. The no-shell restriction only applies to interactive logins.

### Organising tasks across users

There are two ways to separate tasks for different service accounts. Both use the same `su -s` mechanism when reporting is enabled — `.task.env` is always root-owned regardless of which approach you choose.

#### Option A — One venv, one Schedule per user

Use a single venv and client registration. Create one Schedule per user on the task server, then run `install` once per user with matching `--schedule`, `--user`, and `--file` flags:

```bash
task-crontab install --schedule pypiserver-tasks --user pypiserver --file /etc/cron.d/ophix-pypiserver
task-crontab install --schedule www-data-tasks   --user www-data   --file /etc/cron.d/ophix-www-data
```

Each file is self-contained and self-updating. Good for many users managed from a single venv, where all tasks come from the same task server.

#### Option B — Separate venv per user

Install a dedicated venv for each service account with its own client registration on the task server. Run `install` from each venv:

```bash
/opt/venvs/pypiserver/bin/task-crontab install --schedule pypiserver-tasks --user pypiserver --file /etc/cron.d/ophix-pypiserver
/opt/venvs/www-data/bin/task-crontab install    --schedule www-data-tasks   --user www-data   --file /etc/cron.d/ophix-www-data
```

Good for a small number of users, or when different service accounts need to pull tasks from different task servers — each venv has its own `.task.env` pointing to a different server URL and token.

A single client may hold access to multiple Schedules simultaneously. There is no server-enforced limit.

---

## Automating the Sync

The `install` command adds the bootstrapping sync line automatically. The generated line includes all flags needed for a faithful re-sync — `--user`, `--file`, and `--format` — so no manual configuration is required after `install`.

To add the bootstrap line manually instead:

```text
# /etc/cron.d/ophix-pypiserver
*/15 * * * * root /opt/venv/bin/task-crontab sync --schedule pypiserver-tasks --user pypiserver --file /etc/cron.d/ophix-pypiserver --format crond
```

Or define the sync call itself as a task in a separate Schedule and run `install` for that Schedule.
