"""Reading replies to a reminder message (core/replies.py)."""

from datetime   import timedelta

import pytest

from core.replies import parse_reply
from enums        import ReplyCommand


@pytest.mark.parametrize("text, command, snooze, when", [
    ("done",                    ReplyCommand.DONE,   None,                   None),
    ("Done!",                   ReplyCommand.DONE,   None,                   None),
    ("ok",                      ReplyCommand.DONE,   None,                   None),
    ("👍",                      ReplyCommand.DONE,   None,                   None),
    ("snooze",                  ReplyCommand.SNOOZE, None,                   None),
    ("snooze 20 min",           ReplyCommand.SNOOZE, timedelta(minutes=20),  None),
    ("snooze for 2 hours",      ReplyCommand.SNOOZE, timedelta(hours=2),     None),
    ("remind me later",         ReplyCommand.SNOOZE, None,                   None),
    ("later",                   ReplyCommand.SNOOZE, None,                   None),
    ("move it to 10",           ReplyCommand.MOVE,   None,                   "at 10"),
    ("Move to tomorrow at 9",   ReplyCommand.MOVE,   None,                   "tomorrow at 9"),
    ("change it to friday",     ReplyCommand.MOVE,   None,                   "friday"),
    ("make it 18:30",           ReplyCommand.MOVE,   None,                   "at 18:30"),
    ("cancel",                  ReplyCommand.CANCEL, None,                   None),
    ("delete it",               ReplyCommand.CANCEL, None,                   None),
])
def test_parse_reply(text, command, snooze, when):
    reply = parse_reply(text)
    assert (reply.command, reply.snooze, reply.when) == (command, snooze, when)


@pytest.mark.parametrize("text", ["thanks", "snooze until whenever", "done with it", "move", "ok cool", ""])
def test_not_a_reply_command(text):
    assert parse_reply(text) is None
