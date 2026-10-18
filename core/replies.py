"""Replies to a reminder message: "done", "snooze 20 min", "move it to 10", "cancel".

parse_reply() reads the reply; handlers/replies.py acts on it. Anything else
isn't a reply command, and is handled like any other message.
"""

import re

from dataclasses    import dataclass
from datetime       import timedelta
from typing         import Optional

from core.parser    import parse_duration
from enums          import ReplyCommand


DONE = re.compile(r"^(?:done|ok|okay|did it|finished|got it|✅|👍)$")
SNOOZE = re.compile(r"^(?:snooze|later|remind me later|remind me again)(?:\s+(?:for|in))?(?:\s+(?P<duration>.+))?$")
MOVE = re.compile(r"^(?:move|change|reschedule|push|make)(?:\s+it)?(?:\s+(?:to|for))?\s+(?P<when>.+)$")
CANCEL = re.compile(r"^(?:cancel|delete|remove|stop)(?:\s+it)?$")
# "move it to 10": a bare hour is a clock time here
BARE_HOUR = re.compile(r"^\d{1,2}(?:[:.]\d{2})?(?:am|pm)?$")


@dataclass
class Reply:
    command: ReplyCommand
    snooze: Optional[timedelta] = None    # SNOOZE: how long; None = the first snooze option
    when: Optional[str] = None            # MOVE: the new time, as written


def parse_reply(text: str) -> Optional[Reply]:
    """The command in a reply to a reminder, or None if it isn't one."""
    text = " ".join(text.lower().strip().rstrip(".!").split())
    if DONE.match(text):
        return Reply(ReplyCommand.DONE)
    if CANCEL.match(text):
        return Reply(ReplyCommand.CANCEL)
    if m := SNOOZE.match(text):
        if m.group("duration") is None:
            return Reply(ReplyCommand.SNOOZE)
        duration = parse_duration(m.group("duration"))
        return Reply(ReplyCommand.SNOOZE, snooze=duration) if duration else None
    if m := MOVE.match(text):
        when = m.group("when")
        return Reply(ReplyCommand.MOVE, when=f"at {when}" if BARE_HOUR.match(when) else when)
    return None
