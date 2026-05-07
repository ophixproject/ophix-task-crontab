"""
ophix_task_crontab.cli
~~~~~~~~~~~~~~~~~~~~~~
Command-line interface for the ophix-task-crontab Tier 2 client.

Entry point: task-crontab (registered in pyproject.toml).

Commands:
    sync   — fetch tasks from the server and apply to the crontab file
    show   — print the cron block that would be written, without writing
    clear  — remove the ophix-managed block from the crontab file
    import — parse an existing crontab and create tasks on the server
"""

import argparse
import sys

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
                print("  created  #{}: {} ({})".format(
                    task_id, entry["name"], entry["command"][:60]
                ))
            elif task_status == "skipped":
                skipped += 1
                print("  skipped  #{} (command already exists): {}".format(
                    task_id, entry["command"][:60]
                ))
        except Exception as e:
            errors += 1
            print("  error       {}: {}".format(entry["command"][:60], e))

    print("\nImport complete: {} created, {} skipped, {} errors.".format(
        created, skipped, errors
    ))


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

    # import
    p = sub.add_parser("import", help="Parse an existing crontab and create tasks on the server.")
    p.add_argument("--schedule", required=True, help="Schedule name to import tasks into")
    p.add_argument(
        "--file",
        default=None,
        help="Crontab file to read (default: reads from 'crontab -l')",
    )

    return parser


COMMANDS = {
    "sync": cmd_sync,
    "show": cmd_show,
    "clear": cmd_clear,
    "import": cmd_import,
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
