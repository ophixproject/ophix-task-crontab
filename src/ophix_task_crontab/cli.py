"""
ophix_task_crontab.cli
~~~~~~~~~~~~~~~~~~~~~~
Command-line interface for the ophix-task-crontab Tier 2 client.

Entry point: task-crontab (registered in pyproject.toml).
"""

import sys
import types

from client_core.parser import make_main
from ophix_task_crontab._version import __version__
from ophix_task_crontab.core import (
    DEFAULT_CRONTAB_FILE,
    DEFAULT_CRONTAB_USER,
    clear_crontab,
    parse_crontab,
    read_crontab_source,
    show_crontab,
    sync_crontab,
)
from task_client.core import create_task, get_tasks


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_sync(args):
    try:
        tasks = get_tasks(schedule=args.schedule or None, scheduler="cron")
    except Exception as e:
        print("Failed to fetch tasks: {}".format(e))
        sys.exit(1)

    try:
        sync_crontab(tasks, crontab_file=args.file, user=args.user)
        print("Synced {} task(s) to {}.".format(len(tasks), args.file))
    except PermissionError:
        print("Permission denied writing to {}. Run as root or use sudo.".format(args.file))
        sys.exit(1)
    except Exception as e:
        print("Failed to write crontab: {}".format(e))
        sys.exit(1)


def cmd_show(args):
    try:
        tasks = get_tasks(schedule=args.schedule or None, scheduler="cron")
    except Exception as e:
        print("Failed to fetch tasks: {}".format(e))
        sys.exit(1)

    print(show_crontab(tasks, user=args.user), end="")


def cmd_clear(args):
    try:
        found = clear_crontab(crontab_file=args.file)
        if found:
            print("Ophix-managed block removed from {}.".format(args.file))
        else:
            print("No ophix-managed block found in {}.".format(args.file))
    except PermissionError:
        print("Permission denied writing to {}. Run as root or use sudo.".format(args.file))
        sys.exit(1)
    except Exception as e:
        print("Failed to clear crontab: {}".format(e))
        sys.exit(1)


def cmd_import(args):
    try:
        content = read_crontab_source(args.file)
    except Exception as e:
        print("Failed to read crontab: {}".format(e))
        sys.exit(1)

    entries = parse_crontab(content)

    if not entries:
        print("No cron entries found to import.")
        return

    print("Found {} entries. Importing into schedule '{}'...\n".format(len(entries), args.schedule))

    created = 0
    skipped = 0
    errors = 0

    for entry in entries:
        try:
            result = create_task(
                schedule=args.schedule,
                name=entry["name"],
                command=entry["command"],
                description=entry["description"],
                interval=entry["schedule"] if not entry["schedule"].startswith("@") or True else "",
            )
            task_status = result.get("status")
            task_id = result.get("id")
            if task_status == "created":
                created += 1
                print("  created  #{}: {} ({})".format(task_id, entry["name"], entry["command"][:60]))
            elif task_status == "skipped":
                skipped += 1
                print("  skipped  #{} (command already exists): {}".format(task_id, entry["command"][:60]))
        except Exception as e:
            errors += 1
            print("  error       {}: {}".format(entry["command"][:60], e))

    print("\nImport complete: {} created, {} skipped, {} errors.".format(created, skipped, errors))


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

COMMANDS = {
    "sync": {
        "help": "Fetch tasks from the server and apply to the crontab file.",
        "arguments": [
            {"name": "--schedule", "default": "",
             "help": "Only fetch tasks from this named schedule (default: all)"},
            {"name": "--file", "default": DEFAULT_CRONTAB_FILE,
             "help": "Crontab file to write (default: {})".format(DEFAULT_CRONTAB_FILE)},
            {"name": "--user", "default": DEFAULT_CRONTAB_USER,
             "help": "Unix user to run tasks as (default: {})".format(DEFAULT_CRONTAB_USER)},
        ],
        "handler": cmd_sync,
    },

    "show": {
        "help": "Print the cron block that would be written, without writing it.",
        "arguments": [
            {"name": "--schedule", "default": "",
             "help": "Only fetch tasks from this named schedule (default: all)"},
            {"name": "--user", "default": DEFAULT_CRONTAB_USER,
             "help": "Unix user to run tasks as (default: {})".format(DEFAULT_CRONTAB_USER)},
        ],
        "handler": cmd_show,
    },

    "clear": {
        "help": "Remove the ophix-managed block from the crontab file.",
        "arguments": [
            {"name": "--file", "default": DEFAULT_CRONTAB_FILE,
             "help": "Crontab file to modify (default: {})".format(DEFAULT_CRONTAB_FILE)},
        ],
        "handler": cmd_clear,
    },

    "import": {
        "help": "Parse an existing crontab and create tasks on the server.",
        "arguments": [
            {"name": "--schedule", "required": True,
             "help": "Schedule name to import tasks into"},
            {"name": "--file", "default": None,
             "help": "Crontab file to read (default: reads from 'crontab -l')"},
        ],
        "handler": cmd_import,
    },
}

_CONFIG = types.SimpleNamespace(
    prog="task-crontab",
    description="Apply ophix-tasks schedules to a cron.d file.",
    version=__version__,
)

main = make_main(_CONFIG, COMMANDS)


if __name__ == "__main__":
    main()
