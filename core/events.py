"""Events ("padel on thursday at 21:00") and reminders relative to them
("30 min before padel, remind me to pack the racket").

No Telegram, no database: an event here is anything with the columns of
db/models/event.Event (`starts_at`, `ends_at`, `recurrence`, `timezone`,
`skipped`, `moved`, `all_day`, `title`); handlers/events.py looks them up
and saves them.

An event's repeat is an RFC 5545 RRULE (`recurrence`, "FREQ=WEEKLY;BYDAY=TH")
from its first occurrence `starts_at`, minus `skipped` (EXDATEs), with the
single occurrences moved in Google Calendar in `moved`. Events made before
RRULEs keep the bot's own format until they change; `rule_of` reads both.
An occurrence counts as on until it ends (`duration`).
"""

import re

from dataclasses    import dataclass, replace
from datetime       import date, datetime, time, timedelta
from typing         import Optional
from zoneinfo       import ZoneInfo

from core           import recurrence as recurrences
from core.parser    import MissingText, MissingTime, ParseError, TooFar, parse_duration, parse_reminder


@dataclass
class ParsedEvent:
    title: str
    starts_at: datetime     # aware, in the user's timezone; the first occurrence if repeating
    recurrence: Optional[recurrences.Recurrence] = None
    all_day: bool = False   # a day without a time ("dentist on friday"): starts_at is its midnight


def _all_day(parsed, now: datetime) -> ParsedEvent:
    """A day without a time: the whole day, from its midnight (repeats too)."""
    tz = now.tzinfo
    start = datetime.combine(parsed.when.date(), time(0, 0), tzinfo=tz)
    recurrence = parsed.recurrence
    if isinstance(recurrence, recurrences.Interval):
        recurrence = recurrences.Interval(recurrence.every, start)
    elif recurrence is not None:
        recurrence = replace(recurrence, clock=time(0, 0))
        # "every friday" said on a Friday: today is one of them (the parser's 09:00 may have passed)
        today = datetime.combine(now.date(), time(0, 0), tzinfo=tz)
        start = recurrence.next_after(today - timedelta(seconds=1), tz)
    return ParsedEvent(parsed.text, start, recurrence, all_day=True)


def parse_event(request: str, now: datetime) -> ParsedEvent:
    """Split "padel on thursday at 21:00" into a title and a time, like a reminder.

    Raises the parser's errors: MissingText (a time, no title), MissingTime
    (a title, no time) or ParseError. A day without a time ("dentist on
    friday", "today") is an all-day event.
    """
    if not request.split():
        raise ParseError("What's the event, and when?")
    try:
        parsed = parse_reminder(request, now)
    except (MissingText, MissingTime):
        raise
    except ParseError:
        # "today" in the afternoon: a day alone means 09:00, already passed,
        # but the whole day hasn't. Only a day without a time counts.
        start_of_day = now.replace(hour=0, minute=0, second=1, microsecond=0)
        try:
            parsed = parse_reminder(request, start_of_day)
        except ParseError:
            parsed = None
        if parsed is None or parsed.timed or parsed.when.date() < now.date():
            raise
    if not parsed.timed:
        return _all_day(parsed, now)
    return ParsedEvent(parsed.text, parsed.when, parsed.recurrence)


# --- occurrences ------------------------------------------------------------

def _stamps(value: Optional[str]) -> frozenset:
    return frozenset(recurrences.parse_stamp(s) for s in (value or "").split(",") if s)


def skipped(event) -> frozenset:
    """The occurrences of a repeating event that don't happen (events.skipped)."""
    return _stamps(event.skipped)


def moved(event) -> dict:
    """Single occurrences moved in Google Calendar: original start → new start (events.moved)."""
    pairs = (pair.split(">") for pair in (getattr(event, "moved", None) or "").split(",") if pair)
    return {recurrences.parse_stamp(old): recurrences.parse_stamp(new) for old, new in pairs}


def format_moved(pairs: dict) -> Optional[str]:
    return ",".join(f"{recurrences.format_stamp(o)}>{recurrences.format_stamp(n)}"
                    for o, n in sorted(pairs.items())) or None


def duration(event) -> timedelta:
    """How long each occurrence lasts: to `ends_at`, a whole day if all day, else 0 (a moment)."""
    if getattr(event, "ends_at", None) is not None:
        return max(event.ends_at - event.starts_at, timedelta())
    return timedelta(days=1) if event.all_day else timedelta()


def rrule(event) -> Optional[str]:
    """The event's repeat as an RRULE, also for one stored in the bot's older format; None for a one-off."""
    if not event.recurrence:
        return None
    if recurrences.is_rrule(event.recurrence):
        return event.recurrence.removeprefix("RRULE:")
    return recurrences.to_rrule(recurrences.parse(event.recurrence))


def rule_of(event, with_skipped: bool = True) -> Optional[recurrences.RRuleSet]:
    """A repeating event's occurrences, or None for a one-off."""
    rule = rrule(event)
    if rule is None:
        return None
    shifted = moved(event)
    exdates = (skipped(event) if with_skipped else frozenset()) | frozenset(shifted)
    return recurrences.RRuleSet(rule, event.starts_at.astimezone(ZoneInfo(event.timezone)), event.timezone,
                                exdates, frozenset(shifted.values()))


def schedule(event) -> Optional[recurrences.Offset]:
    """A repeating event's occurrences as an Offset of 0 minutes (what reminders build on), or None."""
    rule = rule_of(event)
    return recurrences.Offset(rule, 0, event.timezone) if rule is not None else None


def with_skipped(event, occurrence: datetime, now: datetime) -> str:
    """events.skipped with `occurrence` added; those already over are dropped."""
    length = duration(event)
    kept = {s for s in skipped(event) if s + length > now} | {occurrence}
    return ",".join(sorted(recurrences.format_stamp(s) for s in kept))


def next_occurrence(event, now: datetime) -> Optional[datetime]:
    """The start of the occurrence that is on now or comes next (all day: all of its day), or None if it's over."""
    length = duration(event)
    rule = schedule(event)
    if rule is None:
        return event.starts_at if event.starts_at + length > now or event.starts_at > now else None
    return rule.occurrence_after(max(now - length, event.starts_at - timedelta(seconds=1)))


def occurrence_on(event, day: date, tz) -> Optional[datetime]:
    """The start of the first occurrence that is on during `day` (local, in `tz`), or None."""
    day_start = datetime.combine(day, time(0, 0), tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    length = duration(event)
    rule = schedule(event)
    if rule is None:
        start = event.starts_at
        on = start < day_end and (start + length > day_start if length else start >= day_start)
        return start if on else None
    after = day_start - length if length else day_start - timedelta(seconds=1)
    start = rule.occurrence_after(max(after, event.starts_at - timedelta(seconds=1)))
    return start if start is not None and start < day_end else None


def occurs_on(event, day: date, tz) -> bool:
    """Whether the event is on during `day` (local, in `tz`)."""
    return occurrence_on(event, day, tz) is not None


def nearest_occurrence(event, around: datetime) -> Optional[datetime]:
    """The occurrence of a repeating event closest to `around`, skipped ones included."""
    rule = rule_of(event, with_skipped=False)
    tz = ZoneInfo(event.timezone)
    occurrence = best = rule.next_after(around - timedelta(days=1), tz)
    while occurrence is not None and occurrence <= around + timedelta(days=1):
        if abs(occurrence - around) < abs(best - around):
            best = occurrence
        occurrence = rule.next_after(occurrence, tz)
    return best


def reminder_time(event, minutes: int, now: datetime, every: bool = False) -> tuple:
    """When a reminder `minutes` from the event's start goes off: (remind_at or None, Offset or None).

    `every` (repeating events only): before every occurrence, as an Offset
    repeat; otherwise only the next occurrence whose reminder is still ahead.
    None if a repeating event has no occurrence left for it.
    """
    delta = timedelta(minutes=minutes)
    rule = schedule(event)
    if rule is None:
        return event.starts_at + delta, None
    rule = replace(rule, minutes=minutes)
    first = rule.next_after(max(now, event.starts_at + delta - timedelta(seconds=1)), ZoneInfo(event.timezone))
    return first, (rule if every else None)


# --- what a message says about events ---------------------------------------

# Words around an event's name: "the padel", "my padel event"
FILLER = {"the", "my", "a", "an", "event", "events", "calendar", "this", "that", "next"}

# "30 min before padel", "an hour after the meeting", "the day before the trip"
RELATIVE_WORDS = {"before": -1, "after": 1}


# More minutes than any duration the parser reads (MAX_DURATION)
TOO_FAR = 10**12


@dataclass
class Relative:
    minutes: int    # negative: before
    event: list     # the words naming the event (and, if `text` is None, the text after it)
    text: Optional[list] = None  # the words before the duration ("to pack the racket 30 min before padel")


def split_relative(request: str) -> Optional[Relative]:
    """Read "30 min before padel to pack the racket" (or "to pack the racket 30 min before padel").

    Only a duration followed by "before" or "after" counts; the event isn't
    looked up here (see match_title).
    """
    words = request.split()
    for i, word in enumerate(words):
        sign = RELATIVE_WORDS.get(word.lower())
        if sign is None or i == len(words) - 1:
            continue
        if [w.lower() for w in words[max(0, i - 2):i]] == ["the", "day"]:
            return Relative(sign * 24 * 60, words[i + 1:], words[:i - 2] or None)
        # The longest duration right before it: "1 hour 30 min", "half an hour"
        for j in range(0, i):
            try:
                delta = parse_duration(" ".join(words[j:i]))
            except TooFar:
                # "99999999999 days": too far for any event (the handler says so)
                return Relative(sign * TOO_FAR, words[i + 1:], words[:j] or None)
            if delta is not None:
                return Relative(sign * int(delta.total_seconds() // 60), words[i + 1:], words[:j] or None)
    return None


def _key(words: list) -> list:
    return [re.sub(r"[^\w']", "", w.lower()) for w in words]


def match_title(words: list, titles) -> Optional[tuple]:
    """The longest of `titles` at the start of `words`, after filler ("the", "my"): (title, the words after).

    Titles are compared word for word, ignoring case and punctuation.
    """
    start = 0
    while start < len(words) and _key(words[start:start + 1])[0] in FILLER:
        start += 1
    best = None
    for title in titles:
        title_words = _key(title.split())
        n = len(title_words)
        if n and _key(words[start:start + n]) == title_words and (best is None or n > len(best[0].split())):
            best = (title, words[start + n:])
    if best is None:
        return None
    title, rest = best
    # "padel event", "my padel calendar entry": trailing filler
    while rest and _key(rest[:1])[0] in {"event", "entry"}:
        rest = rest[1:]
    return title, rest


def unknown_title(words: list) -> str:
    """What an event the bot doesn't know is called: the words up to “to”, “:” or “,”."""
    name = []
    for word in words:
        if word.lower() == "to" and name:
            break
        name.append(word)
        if word.endswith((",", ":")):
            break
    while name and _key(name[:1])[0] in FILLER:
        name = name[1:]
    return " ".join(name).strip(",:;") or " ".join(words)


def clean_text(words: list) -> str:
    """The reminder text after an event's name: "to pack the racket" → "pack the racket"."""
    text = " ".join(words).strip(" ,:;-—")
    for prefix in ("to ", "that ", "about ", "for "):
        if text.lower().startswith(prefix):
            return text[len(prefix):].strip()
    return text


MOVE_STATEMENT = re.compile(r"^(?P<rest>.+?)\s+(?:is|has moved|moved)\s+(?:now\s+)?(?P<when>(?:at|on|to)\s.+?)(?:\s+now)?[.!]?$",
                            re.IGNORECASE)


def split_move(request: str, titles) -> Optional[tuple]:
    """"padel to 20:00" (after "move"): (title, the new time), or None if no event's name starts it."""
    found = match_title(request.split(), titles)
    if found is None:
        return None
    title, rest = found
    if rest and rest[0].lower() == "to":
        rest = rest[1:]
    return title, " ".join(rest)


def split_move_statement(text: str, titles) -> Optional[tuple]:
    """"padel is at 20:00 now": (title, "at 20:00"), if it starts with an event's name."""
    m = MOVE_STATEMENT.match(text.strip())
    if m is None:
        return None
    found = match_title(m.group("rest").split(), titles)
    if found is None or found[1]:
        return None
    when = m.group("when")
    if when.lower().startswith("to "):
        when = when[3:]
    return found[0], when
