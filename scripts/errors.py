"""Unexpected errors from the command line, to review now and then (core/errors.py).

Usage (inside the bot container, where ERRORS_DIR is set):
    docker compose exec bot python scripts/errors.py <command>

    list [--since YYYY-MM-DD]   the errors by kind, most frequent first: number, count, first and last seen
    show <n>                    one kind from `list` in full: message, where, context, traceback

The entries can hold bits of what users sent (an error's message): they stay
on the Pi. Nothing here sends them anywhere; a fix goes in a GitHub issue
without them.
"""

import json
import os
import sys

from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

from core.errors import group, read  # noqa: E402


def _since(args: list):
    """--since YYYY-MM-DD → (datetime, the other args); None for a bad date."""
    if args[:1] != ["--since"]:
        return True, None, args
    try:
        day = datetime.strptime(args[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (IndexError, ValueError):
        return False, None, args
    return True, day, args[2:]


def run(args: list, directory: str = None) -> int:
    directory = directory or config.ERRORS_DIR
    command, rest = (args[0], args[1:]) if args else ("", [])
    ok, since, rest = _since(rest)

    if ok and command == "list" and not rest:
        groups = group(read(directory), since)
        if not groups:
            print("No errors.")
        for n, g in enumerate(groups, 1):
            print(f"{n}. {g.key}  ×{g.count}  first {g.first:%Y-%m-%d %H:%M}  last {g.last:%Y-%m-%d %H:%M} UTC")
            if g.sample:
                print(f"   {g.sample.get('message', '')[:200]}")
        return 0

    if ok and command == "show" and len(rest) == 1 and rest[0].isdigit():
        groups = group(read(directory), since)
        n = int(rest[0])
        if not 1 <= n <= len(groups):
            print(f"No error {n}: see `list`", file=sys.stderr)
            return 1
        g = groups[n - 1]
        print(f"{g.key}  ×{g.count}  first {g.first.isoformat()}  last {g.last.isoformat()}")
        if not g.sample:
            # Its full entry rotated out; only counts are left
            print("(only counts left: the full entry is in a file that rotated out)")
            return 0
        for name in ("time", "type", "message"):
            print(f"{name}: {g.sample.get(name)}")
        print("where: " + json.dumps(g.sample.get("where"), ensure_ascii=False))
        print("context: " + json.dumps(g.sample.get("context"), ensure_ascii=False))
        print(g.sample.get("traceback", ""))
        return 0

    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
