"""Talking to the bot: asking back for what's missing, and what "it" means.

- **Asking back**: a reminder with a day but no time ("friday dentist")
  asks "What time?", and "every week" without a day asks which day. The
  answer is put into the request (`with_clock`, `with_day`), which is then
  parsed again, so one question is asked at a time.
- **The conversation**: for 10 minutes after the user's last message the
  bot remembers what it last made or changed (the subject) and the last
  numbered list it showed, so "move it to 10", "cancel that" and "cancel the
  second one" work without replying to a message (`parse_follow_up`).

No Telegram, no database: handlers/conversation.py acts on it.
"""

import re

from dataclasses    import dataclass, field
from datetime       import datetime, time, timedelta
from typing         import Optional

from core.parser    import FULL_WEEKDAYS, WEEKDAYS, ParseError, ParsedReminder, parse_reminder
from enums          import FollowUp


# How long "it" means the last thing, after the user's last message
CONTEXT_FOR = timedelta(minutes=10)

# The buttons under "What time?", and the same words typed
TIMES_OF_DAY = {"morning": time(9, 0), "afternoon": time(14, 0), "evening": time(19, 0)}

# "at 10", "10", "10:30", "9pm": a bare hour is a clock time here
BARE_CLOCK = re.compile(r"^\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?$")


# --- asking back ------------------------------------------------------------

EVERY_WEEK = re.compile(r"\b(?:every|each)\s+week\b", re.IGNORECASE)


def needs_day(request: str) -> bool:
    """ "every week to water the plants": a weekly repeat without a day."""
    if not EVERY_WEEK.search(request):
        return False
    words = re.findall(r"[a-z]+", request.lower())
    return not any(w in FULL_WEEKDAYS or (w.endswith("s") and w[:-1] in FULL_WEEKDAYS) for w in words)


def with_day(request: str, weekday: int) -> str:
    """ "every week to water the plants" → "every monday to water the plants"."""
    name = next(name for name in FULL_WEEKDAYS if WEEKDAYS[name] == weekday)
    return EVERY_WEEK.sub(f"every {name}", request, count=1)


def read_weekday(answer: str) -> Optional[int]:
    """The day in "monday", "on mon", "Tuesday." (Monday = 0), or None."""
    words = re.findall(r"[a-z]+", answer.lower())
    words = [w for w in words if w not in ("on", "every", "the", "a")]
    if len(words) != 1:
        return None
    word = words[0]
    if word not in WEEKDAYS and word.endswith("s"):
        word = word[:-1]
    return WEEKDAYS.get(word)


def clock_phrase(answer: str) -> str:
    """The answer to "What time?" as words the parser reads after a day: "10" → "at 10", "evening" → "at 19:00"."""
    answer = " ".join(answer.lower().strip().rstrip(".!").split())
    answer = re.sub(r"^(?:at|in the)\s+", "", answer)
    if answer in TIMES_OF_DAY:
        return f"at {TIMES_OF_DAY[answer]:%H:%M}"
    if BARE_CLOCK.match(answer):
        return f"at {answer}"
    return answer


def with_clock(request: str, answer: str) -> str:
    """ "friday dentist" + "10" → "friday dentist at 10"."""
    return f"{request} {clock_phrase(answer)}"


def untimed(request: str, now: datetime) -> Optional[ParsedReminder]:
    """The reminder in `request` if it has a day but no time of day ("friday dentist"), else None.

    "today dentist" in the afternoon too: a day alone means 09:00, which may
    have passed, but the day hasn't.
    """
    for start in (now, now.replace(hour=0, minute=0, second=1, microsecond=0)):
        try:
            parsed = parse_reminder(request, start)
        except ParseError:
            continue
        if parsed.timed or parsed.when.date() < now.date():
            return None
        return parsed
    return None


# --- the conversation -------------------------------------------------------

@dataclass
class Conversation:
    """What "it" and "the second one" mean, kept in user_data while it's fresh."""

    last: datetime                          # the user's last message (or button)
    subject: Optional[tuple] = None         # (ItemKind, id): the last thing made or changed
    listed: list = field(default_factory=list)   # [(ItemKind, id)] as numbered in the last list

    def fresh(self, now: datetime) -> bool:
        return now - self.last <= CONTEXT_FOR

    def pick(self, target) -> Optional[tuple]:
        """(ItemKind, id) for a target of parse_follow_up: None for "it", a number for "the second one"."""
        if target is None:
            return self.subject
        if target == -1 and not self.listed:
            # "cancel the last one" without a list: the last one made
            return self.subject
        if not self.listed:
            return None
        if target == -1:
            return self.listed[-1]
        return self.listed[target - 1] if 1 <= target <= len(self.listed) else None


ORDINALS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5, "sixth": 6, "6th": 6, "seventh": 7, "7th": 7, "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9, "tenth": 10, "10th": 10, "last": -1,
}

TARGET = (
    r"(?:(?P<it>it|that|this|that one|this one)"
    r"|the\s+(?P<nth>\w+)(?:\s+(?:one|reminder|event))?"
    r"|(?:number\s+|no\.?\s*|#)(?P<num>\d{1,2}))"
)
FOLLOW_UPS = [
    (FollowUp.MOVE, re.compile(
        rf"^(?:move|change|reschedule|push|make|put|shift)\s+{TARGET}(?:\s+(?:to|for|until|till))?\s+(?P<when>.+)$")),
    (FollowUp.CANCEL, re.compile(rf"^(?:cancel|delete|remove|drop|scrap)\s+{TARGET}$")),
    (FollowUp.COPY, re.compile(
        r"^(?:and\s+)?(?:also|again|the\s+same(?:\s+(?:thing|one|time))?(?:\s+again)?"
        r"|same(?:\s+(?:thing|one|time))?(?:\s+again)?|do\s+the\s+same)\s+(?P<when>.+)$")),
]
# Polite words before or after: "please cancel it", "ok, move it to 10"
LEADING = re.compile(r"^(?:(?:hey|hi|ok|okay|please|pls|actually|oh|oops|no)[\s,!]+)+")
TRAILING = re.compile(r"(?:[\s,]+(?:please|pls|thanks|thank you))+$")


@dataclass
class FollowUpRequest:
    action: FollowUp
    target: Optional[int] = None    # None: "it" (the subject); a number: the nth listed (-1 = the last)
    when: Optional[str] = None      # MOVE, COPY: the new time, as written


def parse_follow_up(text: str) -> Optional[FollowUpRequest]:
    """ "move it to 10", "cancel that", "cancel the second one", "and the same next week"; None if it isn't one."""
    text = " ".join(text.lower().strip().rstrip(".!?").split())
    text = TRAILING.sub("", LEADING.sub("", text))
    for action, pattern in FOLLOW_UPS:
        m = pattern.match(text)
        if m is None:
            continue
        target = None
        groups = m.groupdict()
        if groups.get("nth") is not None:
            if groups["nth"] not in ORDINALS:
                # "move the dentist to 11": a name, for the other commands
                return None
            target = ORDINALS[groups["nth"]]
        elif groups.get("num") is not None:
            target = int(groups["num"])
        return FollowUpRequest(action, target, groups.get("when"))
    return None


# Drops the question the bot is asking ("never mind"), when one is waiting
NEVER_MIND = re.compile(
    r"^(?:never\s*mind|forget\s+(?:it|that|about it)|cancel(?:\s+(?:it|that|this))?|stop|skip(?:\s+it)?"
    r"|leave\s+it|nothing|no|nope|no thanks)$"
)


def is_never_mind(text: str) -> bool:
    return NEVER_MIND.match(" ".join(text.lower().strip().rstrip(".!").split())) is not None
