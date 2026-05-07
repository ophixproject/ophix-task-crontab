# ophix-task-crontab

Crontab Tier 2 client for [Ophix](https://ophixproject.com) task scheduling.

Fetches the active task list from an Ophix task server (via `ophix-task-client`) and writes a managed block to a `cron.d` file. The managed block is fully reconstructed on every sync — no line-by-line diffing.

---

## Installation

```
pip install ophix-task-crontab
```

`ophix-task-client` is a dependency and will be installed automatically. Configure `ophix-task-client` first (run `task-client quickstart`) before using `task-crontab`.

Requires Python 3.7+. Writing to `/etc/cron.d/` requires root.

---

## Quick start

```
task-client quickstart https://tasks.internal myhost-tasks
task-crontab sync
```

---

## How it works

On each `sync`, `task-crontab`:

1. Fetches the active task list from the task server via `task-client`
2. Translates each task to a cron entry (see Translation below)
3. Replaces the managed block in the crontab file between sentinel comments
4. Leaves all content outside the sentinels untouched

### Sentinel format

```
# --- BEGIN OPHIX-TASKS (managed by ophix-task-crontab, do not edit) ---
0 2 * * * root /opt/myapp/backup.sh  # nightly-backup
30 9 1 6 * root /opt/myapp/cleanup.sh  # one-time-cleanup
# --- END OPHIX-TASKS ---
```

Do not manually edit content between the sentinels — it will be overwritten on the next sync.

### Task translation

| Server field | Cron output |
|---|---|
| `interval` set | Used directly as the cron schedule expression |
| `run_at` set | Schedule derived from the datetime: `MM HH DD month *` |
| Neither set | Skipped with a comment line in the output |

**One-off tasks (`run_at`):** The cron expression pins the minute, hour, day, and month but leaves the year as `*`. Without a year field, the entry would fire again the following year — however, `ends_at` (set automatically by the server, or explicitly by the operator) causes the task to disappear from the API response after its window closes. The next sync removes the crontab entry before it can fire again.

**Time bounds (`starts_at` / `ends_at`):** Enforced server-side. Tasks outside their active window are not returned by the API and therefore not written to the crontab. No client-side date checking is required.

---

## CLI reference

### `task-crontab sync`

Fetch tasks and apply to the crontab file. Run this regularly (e.g. every 5 minutes) to keep the schedule current.

```
task-crontab sync
task-crontab sync --file /etc/cron.d/myapp-tasks
task-crontab sync --user www-data
```

Options:

| Option | Default | Description |
|---|---|---|
| `--file` | `/etc/cron.d/ophix-tasks` | Crontab file to write |
| `--user` | `root` | Unix user to run tasks as |

Requires write access to the crontab file (typically root).

### `task-crontab show`

Print the cron block that would be written, without writing it. Useful for inspection and debugging.

```
task-crontab show
task-crontab show --user www-data
```

### `task-crontab clear`

Remove the ophix-managed block from the crontab file. Leaves all other content intact.

```
task-crontab clear
task-crontab clear --file /etc/cron.d/myapp-tasks
```

---

## Recommended cron setup

Add a `task-crontab sync` entry to run the sync regularly. Place this **outside** the ophix-managed block so it is not overwritten:

```
# Ophix task sync — not managed by ophix-task-crontab
*/5 * * * * root /path/to/venv/bin/task-crontab sync >> /var/log/ophix-task-sync.log 2>&1
```

The sync interval determines how quickly schedule changes on the server propagate to the host. Five minutes is a reasonable default for most workloads; reduce it if you need tighter timing for one-off tasks.

---

## Multiple crontab files

You can run multiple sync jobs writing to different files with different users:

```
*/5 * * * * root /path/to/venv/bin/task-crontab sync --file /etc/cron.d/ophix-root --user root
*/5 * * * * root /path/to/venv/bin/task-crontab sync --file /etc/cron.d/ophix-app --user appuser
```

All syncs pull from the same task server using the same client credentials. Filtering by user is done by creating separate Schedules on the server and linking the appropriate one to this client — the Tier 2 then applies a `--user` flag to run those tasks as the correct OS user.
