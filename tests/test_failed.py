"""Closing failed messages: the startup re-check (jobs/failed.py) and scripts/failed.py."""

import json

from datetime   import datetime
from zoneinfo   import ZoneInfo

import pytest

from enums      import FailureReason, FailureStatus, IntentName, MessageSource

# Saturday 10 Oct 2026, 08:00
NOW = datetime(2026, 10, 10, 8, 0, tzinfo=ZoneInfo("Europe/Lisbon"))


@pytest.mark.parametrize("text, intent, expected", [
    # No trigger phrase matched when it was sent
    ("remind me tomorrow at 9 to stretch",  None,                       True),
    ("my reminders",                        None,                       True),
    ("that's wrong",                        None,                       True),
    ("remind me someday to stretch",        None,                       False),
    ("hello there",                         None,                       False),
    # The time and text of a reminder (after "remind me", or the answer to ✏️ Edit)
    ("tomorrow at 9 to stretch",            IntentName.REMINDER_CREATE, True),
    ("at 9 to stretch",                     IntentName.REMINDER_EDIT,   True),
    ("someday to stretch",                  IntentName.REMINDER_CREATE, False),
    ("tomorrow at 9",                       IntentName.REMINDER_CREATE, False),
])
def test_understood(text, intent, expected):
    from jobs.failed import understood
    assert understood(text, intent, NOW) is expected


def test_understood_at_the_moment_it_was_sent():
    from jobs.failed import understood
    # At 08:00 "today at 7:30" has passed; at 06:00 it hadn't.
    assert not understood("today at 7:30 to stretch", IntentName.REMINDER_CREATE, NOW)
    assert understood("today at 7:30 to stretch", IntentName.REMINDER_CREATE, NOW.replace(hour=6))


def _create(user, text, reason=FailureReason.NOT_UNDERSTOOD, intent=None):
    from db.repositories.failed_message import FailedMessageRepository
    return FailedMessageRepository().create(user.id, text, MessageSource.TYPED, reason, intent)


def _get(entry):
    from db.repositories.failed_message import FailedMessageRepository
    return FailedMessageRepository().get(entry.id)


def test_resolve_understood_closes_only_what_is_understood_now(user):
    from jobs.failed import FIXED_NOTE, resolve_understood

    learned = _create(user, "remind me tomorrow at 9 to stretch")
    learned_time = _create(user, "tomorrow at 9 to stretch", intent=IntentName.REMINDER_CREATE)
    still_failing = _create(user, "remind me someday to stretch")
    # Wrong results are never closed automatically: the bot did understand something.
    wrong = _create(user, "tomorrow at 9 to stretch", FailureReason.WRONG_RESULT, IntentName.REMINDER_CREATE)

    resolved = {e.id for e in resolve_understood()}
    assert {learned.id, learned_time.id} <= resolved
    assert not {still_failing.id, wrong.id} & resolved

    assert (_get(learned).status, _get(learned).note) == (FailureStatus.FIXED, FIXED_NOTE)
    assert _get(learned).fixed_at is not None
    assert _get(still_failing).status == FailureStatus.OPEN
    assert _get(wrong).status == FailureStatus.OPEN
    # Already closed: not closed again
    assert learned.id not in {e.id for e in resolve_understood()}


def test_ignore_and_fix_pr(user):
    from db.repositories.failed_message import FailedMessageRepository
    repo = FailedMessageRepository()

    entry = _create(user, "to and the and twelve")
    assert repo.set_fix_pr(entry.id, 41).fix_pr == 41
    assert repo.set_fix_pr(entry.id, None).fix_pr is None
    ignored = repo.mark_ignored(entry.id, "garbled transcript")
    assert (ignored.status, ignored.note) == (FailureStatus.IGNORED, "garbled transcript")
    assert entry.id not in {e.id for e in repo.list_open()}
    # Closed entries can't be changed any more
    assert repo.mark_fixed(entry.id) is None
    assert repo.set_fix_pr(entry.id, 42) is None


# --- scripts/failed.py ----------------------------------------------------------

def test_script(user, capsys):
    from db.repositories.user import UserRepository
    from scripts.failed import run

    UserRepository().set_timezone(user.telegram_id, "Europe/Lisbon")
    entry = _create(user, "remind to call the bank")

    assert run(["list"]) == 0
    [line] = [json.loads(l) for l in capsys.readouterr().out.splitlines() if json.loads(l)["id"] == entry.id]
    assert line["text"] == "remind to call the bank"
    assert (line["timezone"], line["reason"], line["intent"], line["fix_pr"]) == (
        "Europe/Lisbon", "not_understood", None, None,
    )
    assert line["sent_at"].endswith(("+00:00", "+01:00"))

    assert run(["pr", str(entry.id), "43"]) == 0
    assert _get(entry).fix_pr == 43
    assert run(["pr", str(entry.id), "none"]) == 0
    assert _get(entry).fix_pr is None

    assert run(["ignore", str(entry.id), "a test"]) == 0
    assert (_get(entry).status, _get(entry).note) == (FailureStatus.IGNORED, "a test")
    assert run(["fixed", str(entry.id), "again"]) == 1     # not open any more

    assert run(["check"]) == 0
    assert run([]) == 2
    assert run(["ignore", "abc", "x"]) == 2
    assert run(["pr", str(entry.id), "soon"]) == 2
