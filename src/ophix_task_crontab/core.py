"""
ophix_task_crontab.core
~~~~~~~~~~~~~~~~~~~~~~~
Crontab translation layer for ophix-tasks.

Fetches the active task list from the task server via task_client and
writes a managed block to a cron.d file using sentinel comments. The
entire block is reconstructed on every sync — no line-by-line diffing.

Sentinel format:
    # --- BEGIN OPHIX-TASKS (managed by ophix-task-crontab, do not edit) ---
    <entries>
    # --- END OPHIX-TASKS ---

One-off tasks (run_at set):
    Derive a cron expression from the datetime: MM HH DD month *
    The server stops returning the task after ends_at (or 24h after run_at
    if ends_at is not set), so the entry is removed on the next sync.

Recurring tasks (interval set):
    Use the interval directly as a cron expression.
"""

import os
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SENTINEL_BEGIN = "# --- BEGIN OPHIX-TASKS (managed by ophix-task-crontab, do not edit) ---"
SENTINEL_END = "# --- END OPHIX-TASKS ---"

DEFAULT_CRONTAB_FILE = "/etc/cron.d/ophix-tasks"
DEFAULT_CRONTAB_USER = "root"


def run_at_to_cron(run_at_str):
    # type: (str) -> str
    """Convert an ISO datetime string to a cron expression pinned to that minute/hour/day/month."""
    if run_at_str.endswith("Z"):
        run_at_str = run_at_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(run_at_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone(dt_timezone.utc)
    return "{} {} {} {} *".format(dt.minute, dt.hour, dt.day, dt.month)


def _build_command(task):
    # type: (Dict) -> str
    """
    Build the full shell command string for a task, including any reporting pipes.

    Reporting logic (server-controlled via report_output / report_error):
      - Neither: bare command
      - output only:  command | task-client report <id>
      - error only:   command 2>&1 1>/dev/null | task-client report <id>
      - both:         command 2>&1 | task-client report <id>
    """
    command = task.get("command", "")
    task_id = task.get("id")
    report_output = task.get("report_output", False)
    report_error = task.get("report_error", False)

    if not (report_output or report_error) or task_id is None:
        return command

    reporter = "task-client report {}".format(task_id)

    if report_output and report_error:
        return "{} 2>&1 | {}".format(command, reporter)
    elif report_output:
        return "{} | {}".format(command, reporter)
    else:
        # stderr only — redirect stderr to stdout, discard stdout
        return "{} 2>&1 1>/dev/null | {}".format(command, reporter)


def task_to_cron_line(task, user):
    # type: (Dict, str) -> Optional[str]
    """
    Convert a task dict to a cron line, or None if the task cannot be expressed.

    Returns a comment line for tasks missing both run_at and interval so
    the admin is aware something was skipped rather than silently dropped.
    """
    name = task.get("name", "unnamed")
    run_at = task.get("run_at")
    interval = task.get("interval", "").strip()

    if run_at:
        schedule = run_at_to_cron(run_at)
    elif interval:
        schedule = interval
    else:
        return "# SKIPPED (no run_at or interval): {}".format(name)

    command = _build_command(task)

    return "{schedule} {user} {command}  # {name}".format(
        schedule=schedule,
        user=user,
        command=command,
        name=name,
    )


def build_managed_block(tasks, user):
    # type: (List[Dict], str) -> str
    """Build the full managed cron block including sentinels."""
    lines = [SENTINEL_BEGIN]
    for task in tasks:
        line = task_to_cron_line(task, user)
        if line is not None:
            lines.append(line)
    lines.append(SENTINEL_END)
    return "\n".join(lines) + "\n"


def _strip_managed_block(content):
    # type: (str) -> Tuple[str, bool]
    """
    Remove the ophix-managed block from existing crontab content.

    Returns (stripped_content, found) where found indicates whether
    a managed block was present.
    """
    lines = content.splitlines(keepends=True)
    result = []
    inside = False
    found = False
    for line in lines:
        stripped = line.rstrip("\n").rstrip("\r")
        if stripped == SENTINEL_BEGIN:
            inside = True
            found = True
            continue
        if stripped == SENTINEL_END:
            inside = False
            continue
        if not inside:
            result.append(line)
    return "".join(result), found


def sync_crontab(tasks, crontab_file=DEFAULT_CRONTAB_FILE, user=DEFAULT_CRONTAB_USER):
    # type: (List[Dict], str, str) -> None
    """
    Write the active task list to the crontab file.

    Replaces the managed block if present, appends it if not.
    The file is created if it does not exist.
    Raises PermissionError if the file is not writable.
    """
    path = Path(crontab_file)

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    stripped, had_block = _strip_managed_block(existing)

    # Ensure the file ends with a newline before appending
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"

    new_block = build_managed_block(tasks, user)
    new_content = stripped + new_block

    path.write_text(new_content, encoding="utf-8")


def clear_crontab(crontab_file=DEFAULT_CRONTAB_FILE):
    # type: (str) -> bool
    """Remove the ophix-managed block from the crontab file. Returns True if a block was found."""
    path = Path(crontab_file)
    if not path.exists():
        return False
    existing = path.read_text(encoding="utf-8")
    stripped, found = _strip_managed_block(existing)
    if found:
        path.write_text(stripped, encoding="utf-8")
    return found


def show_crontab(tasks, user=DEFAULT_CRONTAB_USER):
    # type: (List[Dict], str) -> str
    """Return the cron block that would be written, without writing it."""
    return build_managed_block(tasks, user)
