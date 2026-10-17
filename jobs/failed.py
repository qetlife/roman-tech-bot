"""On startup, mark failed messages the bot now understands as fixed.

Every deploy restarts the bot, so a parser fix closes the messages it was
made for without anyone tapping ✅. Only "not understood" messages are
checked: for a wrong result the bot did understand something, and only a
person (or the auto-fix job) can tell whether it is right now.
"""

import logging

from    datetime                        import datetime
from    typing                          import Optional

from    core.intents                    import match_intent
from    core.parser                     import ParseError, parse_reminder
from    core.timezones                  import to_local
from    db.repositories.failed_message  import FailedMessageRepository
from    db.repositories.user            import UserRepository
from    enums                           import FailureReason, IntentName
from    handlers.intents                import INTENTS


logger = logging.getLogger(__name__)

failed = FailedMessageRepository()
users = UserRepository()

FIXED_NOTE = "understood after an update"


def understood(text: str, intent: Optional[str], now: datetime) -> bool:
    """Whether the bot would now handle `text`, sent at `now` (in the user's timezone).

    `intent` is where it failed: a reminder's time and text (create, or the
    answer to ✏️ Edit), or None for a message that matched no trigger phrase.
    """
    if intent not in (IntentName.REMINDER_CREATE, IntentName.REMINDER_EDIT):
        match = match_intent(text, INTENTS)
        if match is None:
            return False
        if match.intent.name != IntentName.REMINDER_CREATE:
            return True
        text = match.rest
    try:
        parse_reminder(text, now)
    except ParseError:
        return False
    return True


def resolve_understood() -> list:
    """Mark the open "not understood" messages the bot now understands as fixed; returns them.

    Each is replayed at the moment it was sent, so "tomorrow at 9" means the
    same day it meant then.
    """
    entries = [e for e in failed.list_open() if e.reason == FailureReason.NOT_UNDERSTOOD]
    timezones = users.get_timezones({e.user_id for e in entries})
    resolved = []
    for entry in entries:
        now = to_local(entry.created_at, timezones.get(entry.user_id) or "UTC")
        if understood(entry.text, entry.intent, now) and failed.mark_fixed(entry.id, FIXED_NOTE):
            resolved.append(entry)
    if resolved:
        logger.info("Failed messages now understood, marked fixed: %s", [e.id for e in resolved])
    return resolved
