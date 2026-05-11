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

task-crontab writes a sentinel-delimited block to a cron.d file:

```text
# --- BEGIN OPHIX-TASKS (managed by ophix-task-crontab, do not edit) ---
# Nightly backup script
0 2 * * * root /opt/backup.sh | task-client report 1  # nightly-backup
# [disabled] 30 9 * * * root /opt/cleanup.sh  # disabled-cleanup
# --- END OPHIX-TASKS ---
```

- Content outside the sentinels is preserved
- Disabled tasks are written as commented-out lines (visible but not active)
- Descriptions appear as comment lines above the cron entry
- One-off tasks (`run_at`) are converted to a pinned cron expression

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

Fetch tasks and apply to the crontab file.

```bash
task-crontab sync
task-crontab sync --schedule server-maintenance
task-crontab sync --user www-data --file /etc/cron.d/ophix-www
```

| Argument | Default | Description |
| --- | --- | --- |
| `--schedule` | (all) | Only fetch tasks from this named Schedule |
| `--file` | `/etc/cron.d/ophix-tasks` | Crontab file to write |
| `--user` | `root` | Unix user to run tasks as |

Requires write permission to the target file. Run as root or via sudo.

### `show`

Print the cron block that would be written, without writing it.

```bash
task-crontab show
task-crontab show --schedule server-maintenance --user www-data
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
