"""Plain-language commands about reminders: which ones "cancel the dentist
reminder" means, and which day "what do I have tomorrow?" asks about.

No Telegram, no database: handlers/reminders.py looks the reminders up.
"""

import re

from datetime       import date, datetime, timedelta, tzinfo
from typing         import Optional

from core           import recurrence as recurrences
from core.parser    import parse_when


# Words around what identifies a reminder: "the dentist reminder", "my reminder to call mom"
FILLER = {"the", "my", "a", "that", "this", "reminder", "reminders", "to", "about", "for", "called", "named"}


def search_words(request: str) -> list:
    """The words that pick a reminder: "the dentist reminder" → ["dentist"]."""
    words = re.findall(r"[\w']+", request.lower())
    return [w for w in words if w not in FILLER]


# Shorter words must match a whole word: "go" isn't "google".
MIN_PREFIX = 3


def matches(text: str, words: list) -> bool:
    """Whether a reminder's text has all the words (as words, or the start of one if 3+ letters)."""
    own = re.findall(r"[\w']+", text.lower())
    return all(any(o == w or (len(w) >= MIN_PREFIX and o.startswith(w)) for o in own) for w in words)


def parse_day(request: str, now: datetime) -> Optional[date]:
    """The day in "tomorrow?", "on friday", "for dec 24", or None."""
    phrase = request.strip().strip("?!. ").lower()
    phrase = re.sub(r"^(?:for|on)\s+", "", phrase)
    if not phrase:
        return None
    # A day: read it from early today, so "sunday" on a Sunday afternoon is
    # today, not next week (a day alone means 09:00, which may have passed).
    # Not before 04:00, when "tomorrow" still means the coming day.
    if now.hour >= 4:
        now = now.replace(hour=4, minute=0, second=0, microsecond=0)
    when = parse_when(phrase, now)
    return when.date() if when is not None else None


def occurs_on(remind_at: datetime, recurrence: Optional[str], day: date, tz: tzinfo,
              created_at: datetime) -> bool:
    """Whether a reminder is due on `day` (local), including earlier that day.

    `remind_at` is its next time; a repeat (`recurrence`) also counts on any
    day it falls on since it was made (`created_at`), so a daily 08:00 one
    that already went off today is still on today's list.
    """
    if remind_at.astimezone(tz).date() == day:
        return True
    if not recurrence:
        return False
    start = max(datetime.combine(day, datetime.min.time(), tzinfo=tz), created_at)
    following = recurrences.parse(recurrence).next_after(start - timedelta(seconds=1), tz)
    return following.astimezone(tz).date() == day
