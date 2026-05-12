"""
ophix_task_crontab.core
~~~~~~~~~~~~~~~~~~~~~~~
Crontab translation layer for ophix-tasks.

Fetches the active task list from the task server via task_client and
writes a managed block to a cron.d file using sentinel comments. The
entire block is reconstructed on every sync — no line-by-line diffing.

Sentinel format:
    # --- BEGIN OPHIX-TASKS (managed by ophix-task-crontab, do not edit) ---
    # Description of task
    0 2 * * * root /opt/backup.sh >> /var/log/backup.log 2>&1  # nightly-backup
    # [disabled] 30 9 * * * root /opt/cleanup.sh  # disabled-task
    # --- END OPHIX-TASKS ---

One-off tasks (run_at set):
    Derive a cron expression from the datetime: MM HH DD month *
    The server stops returning the task after ends_at closes, so the
    entry is removed on the next sync before it can fire a second year.

Recurring tasks (interval set):
    Use the interval directly as a cron expression.

Disabled tasks:
    Tasks with enabled=False are written as commented-out lines so the
    operator can see what is managed and that a task has been suspended,
    rather than it silently disappearing from the file.
"""

import os
import re
import subprocess
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SENTINEL_BEGIN = "# --- BEGIN OPHIX-TASKS (managed by ophix-task-crontab, do not edit) ---"
SENTINEL_END = "# --- END OPHIX-TASKS ---"

DEFAULT_CRONTAB_FILE = "/etc/cron.d/ophix-tasks"
DEFAULT_CRONTAB_USER = "root"

FORMAT_CROND = "crond"  # cron.d style: includes username field between schedule and command
FORMAT_USER = "user"    # user crontab style: no username field

# task-client lives in the same venv bin directory as this process.
# Using the full path ensures cron (which runs with a minimal PATH) can find it.
_TASK_CLIENT = os.path.join(os.path.dirname(sys.executable), "task-client")


# ---------------------------------------------------------------------------
# Cron line generation
# ---------------------------------------------------------------------------

def run_at_to_cron(run_at_str):
    # type: (str) -> str
    """Convert an ISO datetime string to a cron expression pinned to that minute/hour/day/month."""
    if run_at_str.endswith("Z"):
        run_at_str = run_at_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(run_at_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone(dt_timezone.utc)
    return "{} {} {} {} *".format(dt.minute, dt.hour, dt.day, dt.month)


def _stdout_suffix(stdout, log_file):
    # type: (str, str) -> str
    if stdout == "null":
        return " > /dev/null"
    if stdout == "file" and log_file:
        return " >> {}".format(log_file)
    return ""


def _stderr_suffix(stderr, log_file):
    # type: (str, str) -> str
    if stderr == "null":
        return " 2>/dev/null"
    if stderr == "merge":
        return " 2>&1"
    if stderr == "file" and log_file:
        return " 2>> {}".format(log_file)
    return ""


def _build_command(task):
    # type: (Dict) -> str
    """
    Build the full shell command string for a task, including output redirects.

    stdout/stderr handling combinations:
      inherit/inherit               → bare command
      report/inherit                → command | task-client report <id>
      report/report or report/merge → command 2>&1 | task-client report <id>
      report/<other>                → command <stderr redirect> | task-client report <id>
      inherit/report                → command 2>&1 1>/dev/null | task-client report <id>
      null/report                   → command 2>&1 1>/dev/null | task-client report <id>
      <stdout>/null                 → command <stdout redirect> 2>/dev/null
      <stdout>/merge                → command <stdout redirect> 2>&1
      file/merge                    → command >> <log_file> 2>&1
      etc.
    """
    command = task.get("command", "")
    task_id = task.get("id")
    stdout = task.get("stdout_handling", "inherit")
    stderr = task.get("stderr_handling", "inherit")
    log_file = (task.get("log_file") or "").strip()

    # If no task ID, reporting is impossible — treat as inherit
    if task_id is None:
        if stdout == "report":
            stdout = "inherit"
        if stderr == "report":
            stderr = "inherit"

    # Both stdout and stderr go to the reporter
    if stdout == "report" and stderr in ("report", "merge"):
        reporter = "{} report {} --stream both".format(_TASK_CLIENT, task_id) if task_id is not None else None
        return "{} 2>&1 | {}".format(command, reporter)

    # Only stdout goes to the reporter; stderr has its own redirect
    if stdout == "report":
        reporter = "{} report {} --stream stdout".format(_TASK_CLIENT, task_id) if task_id is not None else None
        return "{}{} | {}".format(command, _stderr_suffix(stderr, log_file), reporter)

    # Only stderr goes to the reporter; stdout has its own redirect (or is discarded)
    if stderr == "report":
        reporter = "{} report {} --stream stderr".format(_TASK_CLIENT, task_id) if task_id is not None else None
        return "{}{} 2>&1 1>/dev/null | {}".format(command, _stdout_suffix(stdout, log_file), reporter)

    # No reporting — just redirects
    return "{}{}{}".format(command, _stdout_suffix(stdout, log_file), _stderr_suffix(stderr, log_file))


def task_to_cron_line(task, user, fmt=FORMAT_CROND):
    # type: (Dict, str, str) -> str
    """
    Convert a task dict to one or more cron lines (as a single string).

    If the task has a description, a comment line is prepended.
    Paused tasks (paused=True) are written as commented-out lines with [paused].
    The task name suffix (#name) is only appended to active (non-paused) lines.
    Tasks missing both run_at and interval produce a skip comment.

    Disabled tasks (enabled=False) are never returned by the server and are
    therefore never passed to this function.
    """
    name = task.get("name", "unnamed")
    run_at = task.get("run_at")
    interval = task.get("interval", "").strip()
    description = (task.get("description") or "").strip()
    paused = task.get("paused", False)

    if run_at:
        schedule = run_at_to_cron(run_at)
    elif interval:
        schedule = interval
    else:
        return "# SKIPPED (no run_at or interval): {}".format(name)

    command = _build_command(task)

    if fmt == FORMAT_USER:
        cron_line_base = "{schedule} {command}".format(schedule=schedule, command=command)
    else:
        cron_line_base = "{schedule} {user} {command}".format(
            schedule=schedule, user=user, command=command,
        )

    parts = []
    if description:
        for line in description.splitlines():
            parts.append("# {}".format(line))

    if paused:
        parts.append("# [paused] {}".format(cron_line_base))
    else:
        parts.append(cron_line_base)

    return "\n".join(parts)


def build_managed_block(tasks, user, fmt=FORMAT_CROND):
    # type: (List[Dict], str, str) -> str
    """Build the full managed cron block including sentinels."""
    lines = [SENTINEL_BEGIN]
    for task in tasks:
        lines.append("")
        lines.append(task_to_cron_line(task, user, fmt=fmt))
    lines.append("")
    lines.append(SENTINEL_END)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Crontab file management
# ---------------------------------------------------------------------------

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


def sync_crontab(tasks, crontab_file=DEFAULT_CRONTAB_FILE, user=DEFAULT_CRONTAB_USER, fmt=FORMAT_CROND):
    # type: (List[Dict], str, str, str) -> None
    """
    Write the task list to the crontab file.

    Replaces the managed block if present, appends it if not.
    The file is created if it does not exist.
    """
    path = Path(crontab_file)
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    stripped, _ = _strip_managed_block(existing)
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"

    new_content = stripped + build_managed_block(tasks, user, fmt=fmt)
    path.write_text(new_content, encoding="utf-8")


def sync_user_crontab(tasks):
    # type: (List[Dict]) -> None
    """Write the managed block to the current user's crontab via crontab -l / crontab -."""
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "no crontab for" in stderr.lower():
            existing = ""
        else:
            raise RuntimeError("crontab -l failed: {}".format(stderr))
    else:
        existing = result.stdout

    stripped, _ = _strip_managed_block(existing)
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"

    new_content = stripped + build_managed_block(tasks, user="", fmt=FORMAT_USER)

    proc = subprocess.run(["crontab", "-"], input=new_content, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("crontab - failed: {}".format(proc.stderr.strip()))


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


def show_crontab(tasks, user=DEFAULT_CRONTAB_USER, fmt=FORMAT_CROND):
    # type: (List[Dict], str, str) -> str
    """Return the cron block that would be written, without writing it."""
    return build_managed_block(tasks, user, fmt=fmt)


# ---------------------------------------------------------------------------
# Crontab import parsing
# ---------------------------------------------------------------------------

_USERNAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_-]*$')
_SPECIAL_SCHEDULES = frozenset(
    ["@reboot", "@yearly", "@annually", "@monthly", "@weekly", "@daily", "@midnight", "@hourly"]
)


# Commands that look like usernames but are never used as cron.d usernames.
_KNOWN_COMMANDS = frozenset([
    "sudo", "env", "nice", "nohup", "ionice", "timeout", "runuser",
])


def _looks_like_username(token, next_token):
    # type: (str, str) -> bool
    """Return True only when token plausibly is a cron.d username.

    A username must match the username regex, must not be a known command,
    and must be followed by something that looks like a command — an absolute
    path or a known interpreter. This prevents bare commands like 'date' or
    'curl' from being mistaken for usernames when reading user crontabs.
    """
    if not _USERNAME_RE.match(token) or "/" in token:
        return False
    if token in _KNOWN_COMMANDS:
        return False
    return next_token.startswith("/") or next_token in _INTERPRETER_NAMES


_INTERPRETER_NAMES = frozenset([
    "python", "python3", "python2",
    "bash", "sh", "zsh", "dash",
    "perl", "ruby", "node", "nodejs",
    "php", "lua", "tclsh",
])


def _command_basename(command):
    # type: (str) -> str
    """Derive a short task name from the command.

    When the first token is a known interpreter (python, bash, etc.),
    use the basename of the next token (the script) instead, so that
    'python get_prices.py arg' yields 'get_prices' not 'python'.
    """
    tokens = command.split()
    if not tokens:
        return "imported-task"
    first = os.path.basename(tokens[0])
    first_stem = os.path.splitext(first)[0]
    if first_stem in _INTERPRETER_NAMES and len(tokens) > 1:
        next_token = tokens[1]
        if not next_token.startswith("-"):
            base = os.path.basename(next_token)
            name = os.path.splitext(base)[0]
            return name or first_stem
    return first_stem or "imported-task"


def _parse_redirections(command):
    # type: (str) -> tuple
    """
    Strip shell output redirections from a command string and map them to
    ophix task handling fields.

    Returns (cleaned_command, stdout_handling, stderr_handling, log_file).

    Handles both combined (>/dev/null) and spaced (> /dev/null) forms.
    Scans right-to-left; stops at the first token that is neither a
    redirection operator nor a redirection target.
    """
    tokens = command.split()
    stdout_handling = "inherit"
    stderr_handling = "inherit"
    log_file = ""
    consumed = set()  # type: set

    i = len(tokens) - 1
    while i >= 0:
        tok = tokens[i]

        # 2>&1
        if tok == "2>&1":
            stderr_handling = "merge"
            consumed.add(i)
            i -= 1
            continue

        # Combined stderr: 2>/dev/null  2>>/dev/null  2>/path
        if tok.startswith("2>>") or tok.startswith("2>"):
            sep = 3 if tok.startswith("2>>") else 2
            target = tok[sep:]
            if target:
                stderr_handling = "null" if target == "/dev/null" else "file"
                if stderr_handling == "file" and not log_file:
                    log_file = target
                consumed.add(i)
                i -= 1
                continue

        # Combined stdout: >/dev/null  >>/dev/null  >/path
        if tok.startswith(">>") or (tok.startswith(">") and not tok.startswith("2>")):
            sep = 2 if tok.startswith(">>") else 1
            target = tok[sep:]
            if target:
                stdout_handling = "null" if target == "/dev/null" else "file"
                if stdout_handling == "file" and not log_file:
                    log_file = target
                consumed.add(i)
                i -= 1
                continue

        # Spaced form: current token is the target, previous token is the operator.
        # e.g.  "... > /dev/null"  "... >> /var/log/foo.log"  "... 2> /dev/null"
        if i > 0 and tokens[i - 1] in (">", ">>", "2>", "2>>"):
            target = tok
            op = tokens[i - 1]
            if op in (">", ">>"):
                stdout_handling = "null" if target == "/dev/null" else "file"
                if stdout_handling == "file" and not log_file:
                    log_file = target
            else:
                stderr_handling = "null" if target == "/dev/null" else "file"
                if stderr_handling == "file" and not log_file:
                    log_file = target
            consumed.add(i)
            consumed.add(i - 1)
            i -= 2
            continue

        # Not a redirection token or target — stop scanning
        break

    cleaned = " ".join(t for j, t in enumerate(tokens) if j not in consumed)
    return cleaned, stdout_handling, stderr_handling, log_file


def _parse_cron_line(line, comments):
    # type: (str, List[str]) -> Optional[Dict]
    """
    Parse a single cron entry line. Returns a dict or None if unparseable.

    Handles:
      @special [user] command
      min hour dom month dow [user] command
    Auto-detects cron.d (with username) vs user-crontab (without) format.
    """
    tokens = line.split()
    if not tokens:
        return None

    schedule = ""
    rest = []

    if tokens[0] in _SPECIAL_SCHEDULES:
        schedule = tokens[0]
        rest = tokens[1:]
    elif len(tokens) >= 6:
        schedule = " ".join(tokens[:5])
        rest = tokens[5:]
    else:
        return None

    if not rest:
        return None

    # Detect cron.d format: first token of rest looks like a username
    if len(rest) >= 2 and _looks_like_username(rest[0], rest[1]):
        command = " ".join(rest[1:])
    else:
        command = " ".join(rest)

    if not command:
        return None

    command, stdout_handling, stderr_handling, log_file = _parse_redirections(command)

    return {
        "schedule": schedule,
        "command": command,
        "name": _command_basename(command),
        "description": "\n".join(comments),
        "stdout_handling": stdout_handling,
        "stderr_handling": stderr_handling,
        "log_file": log_file,
    }


def parse_crontab(content):
    # type: (str) -> List[Dict]
    """
    Parse crontab content and return a list of task dicts.

    Skips the ophix-managed sentinel block, environment variable assignments,
    and blank lines. Comment lines immediately preceding a cron entry are
    captured as the task description.
    """
    lines = content.splitlines()
    entries = []
    pending_comments = []  # type: List[str]
    in_sentinel = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            pending_comments = []
            continue

        if stripped == SENTINEL_BEGIN:
            in_sentinel = True
            pending_comments = []
            continue
        if stripped == SENTINEL_END:
            in_sentinel = False
            pending_comments = []
            continue
        if in_sentinel:
            continue

        if stripped.startswith("#"):
            comment = stripped.lstrip("#").strip()
            if comment:
                pending_comments.append(comment)
            continue

        # Environment variable assignment (e.g. MAILTO="", SHELL=/bin/bash)
        if "=" in stripped and not stripped[0].isdigit() and stripped[0] != "*" and stripped[0] != "@":
            pending_comments = []
            continue

        entry = _parse_cron_line(stripped, pending_comments)
        if entry:
            entries.append(entry)

        pending_comments = []

    return entries


def read_crontab_source(file_path=None):
    # type: (Optional[str]) -> str
    """
    Read crontab content from a file or from `crontab -l`.

    Raises RuntimeError if crontab -l fails (e.g. no crontab for user).
    """
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")

    result = subprocess.run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "no crontab for" in stderr.lower():
            return ""
        raise RuntimeError("crontab -l failed: {}".format(stderr))
    return result.stdout
