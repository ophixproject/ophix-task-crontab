"""
ophix_task_crontab.cli
~~~~~~~~~~~~~~~~~~~~~~
Command-line interface for the ophix-task-crontab Tier 2 client.

Entry point: task-crontab (registered in pyproject.toml).

Commands:
    sync   — fetch tasks from the server and apply to the crontab file
    show   — print the cron block that would be written, without writing
    clear  — remove the ophix-managed block from the crontab file
"""

import argparse
import sys

from ophix_task_crontab._version import __version__
from ophix_task_crontab.core import (
    DEFAULT_CRONTAB_FILE,
    DEFAULT_CRONTAB_USER,
    clear_crontab,
    show_crontab,
    sync_crontab,
)

from task_client.core import get_tasks


def cmd_sync(args):
    try:
        tasks = get_tasks()
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
        tasks = get_tasks()
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


def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(
        prog="task-crontab",
        description="Apply ophix-tasks schedules to a cron.d file.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="task-crontab {}".format(__version__),
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # sync
    p = sub.add_parser("sync", help="Fetch tasks and apply to crontab file.")
    p.add_argument(
        "--file",
        default=DEFAULT_CRONTAB_FILE,
        help="Crontab file to write (default: {})".format(DEFAULT_CRONTAB_FILE),
    )
    p.add_argument(
        "--user",
        default=DEFAULT_CRONTAB_USER,
        help="Unix user to run tasks as (default: {})".format(DEFAULT_CRONTAB_USER),
    )

    # show
    p = sub.add_parser("show", help="Print the cron block that would be written.")
    p.add_argument(
        "--user",
        default=DEFAULT_CRONTAB_USER,
        help="Unix user to run tasks as (default: {})".format(DEFAULT_CRONTAB_USER),
    )

    # clear
    p = sub.add_parser("clear", help="Remove the ophix-managed block from the crontab file.")
    p.add_argument(
        "--file",
        default=DEFAULT_CRONTAB_FILE,
        help="Crontab file to modify (default: {})".format(DEFAULT_CRONTAB_FILE),
    )

    return parser


COMMANDS = {
    "sync": cmd_sync,
    "show": cmd_show,
    "clear": cmd_clear,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    handler = COMMANDS.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
