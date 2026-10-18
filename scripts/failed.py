"""Failed messages from the command line, for the auto-fix job on the Pi.

Usage (inside the bot container, where DB_CONNECTION is set):
    docker exec roman-tech-bot-bot-1 python scripts/failed.py <command>

    list                  open entries as JSON lines, oldest first
    check                 mark the ones the bot now understands as fixed (as on startup)
    fixed <id> <note>     mark one fixed
    ignore <id> <note>    mark one ignored, e.g. ignore 12 "garbled transcript"
    pr <id> <number>      link one to the pull request that fixes it ("none" unlinks)

The entries hold the user's own words: they stay on the Pi. Nothing here
sends them anywhere.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.timezones                 import to_local  # noqa: E402
from db.repositories.failed_message import FailedMessageRepository  # noqa: E402
from db.repositories.user           import UserRepository  # noqa: E402
from jobs.failed                    import resolve_understood  # noqa: E402

failed = FailedMessageRepository()
users = UserRepository()


def as_json(entry, tz_name: str) -> str:
    return json.dumps({
        "id": entry.id,
        "sent_at": to_local(entry.created_at, tz_name).isoformat(),
        "timezone": tz_name,
        "text": entry.text,
        "source": entry.source,
        "reason": entry.reason,
        "intent": entry.intent,
        "bot_understood": entry.bot_understood,
        "fix_pr": entry.fix_pr,
    }, ensure_ascii=False)


def run(args: list) -> int:
    command, rest = (args[0], args[1:]) if args else ("", [])

    if command == "list" and not rest:
        entries = list(reversed(failed.list_open()))
        timezones = users.get_timezones({e.user_id for e in entries})
        for entry in entries:
            print(as_json(entry, timezones.get(entry.user_id) or "UTC"))
        return 0

    if command == "check" and not rest:
        for entry in resolve_understood():
            print(f"fixed {entry.id}")
        return 0

    if command in ("fixed", "ignore") and len(rest) == 2 and rest[0].isdigit():
        close = failed.mark_fixed if command == "fixed" else failed.mark_ignored
        if close(int(rest[0]), rest[1]) is None:
            print(f"{rest[0]} isn't open", file=sys.stderr)
            return 1
        return 0

    if command == "pr" and len(rest) == 2 and rest[0].isdigit() and (rest[1].isdigit() or rest[1] == "none"):
        if failed.set_fix_pr(int(rest[0]), None if rest[1] == "none" else int(rest[1])) is None:
            print(f"{rest[0]} isn't open", file=sys.stderr)
            return 1
        return 0

    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
