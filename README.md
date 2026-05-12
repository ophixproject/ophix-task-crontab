# ophix-task-crontab

Crontab Tier 2 client for [Ophix Project](https://ophixproject.com) task scheduling.

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

# Nightly backup script
0 2 * * * root /opt/backup.sh | task-client report 1  # nightly-backup

# [paused] 30 9 * * * root /opt/report.sh

# [disabled] 0 3 * * * root /opt/cleanup.sh
# --- END OPHIX-TASKS ---
```

- Content outside the sentinels is preserved
- `[disabled]` tasks (`enabled=False`) — commented out, entry is not active
- `[paused]` tasks (`paused=True`) — commented out temporarily; distinct from disabled
- The task name suffix (`# name`) is only written on active lines
- Descriptions appear as comment lines above active and paused entries
- One-off tasks (`run_at`) are converted to a pinned cron expression

### Output Format

| Format | When used | Line structure |
| --- | --- | --- |
| `crond` | Default when run as root | `schedule username command  # name` |
| `user` | Default when run as non-root | `schedule command  # name` |

Override with `--format user` or `--format crond`.

Output handling (`stdout_handling` / `stderr_handling`) on each task controls shell redirects:

```text
report → command | task-client report <id>
null   → command > /dev/null
file   → command >> /path/to/log
merge  → stderr merged with stdout (2>&1)
```

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

## Multi-Schedule and Multi-User Setup

A single host can manage multiple cron.d files, each populated from a different Schedule:

```bash
# System maintenance jobs (run as root)
task-crontab sync --schedule server-maintenance --file /etc/cron.d/ophix-root --user root

# Web server jobs (run as www-data)
task-crontab sync --schedule www-data-tasks --file /etc/cron.d/ophix-www --user www-data
```

A single client may hold access to multiple Schedules simultaneously. There is no server-enforced limit.

---

## Automating the Sync

Add the sync call as a root cron entry outside the managed block:

```text
# /etc/cron.d/ophix-tasks-sync
*/15 * * * * root /opt/venv/bin/task-crontab sync --schedule server-maintenance
```

Or define it as a task in a separate Schedule and bootstrap that Schedule's cron.d entry manually.
