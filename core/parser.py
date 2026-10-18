"""Parse English reminder requests like "in two hours to call mom".

The parser is deliberately small and predictable: it understands a fixed set
of time expressions and refuses anything else, so the bot can ask the user to
rephrase instead of guessing wrong.

Supported "when" expressions (case-insensitive):
    in 2 hours / in two hours / in 1.5 hours / in 1h30m / in half an hour
    in an hour and a half / in 3 days / in a week
    at 9 / at 9am / at 9:30pm / at 18:00 / 18:00 / noon / midnight
    at 21.20 / 21.20 / at 9.20pm  (a dot works like a colon; "10.11" alone is a date)
    today / tonight / tomorrow / day after tomorrow
      (before 04:00, "tomorrow" means the coming day, not the day after)
    morning / afternoon / evening / night
    monday / on friday / next friday / next week
    24.12 / 24/12 / 2026-12-24 / dec 24 / 24th of december 2026
and combinations of a day and a time, e.g. "tomorrow at 9", "friday 18:00",
"at 9 tomorrow", "tomorrow morning", "on dec 24 at 10am".

Recurring expressions, optionally with a time (09:00 if none is given; a
bare "at 9" is 09:00 unless a day part says otherwise):
    every day / daily / every morning / every evening at 7
    every weekday / on weekdays / every weekend / weekends
    every monday / every mon and thu / mondays and fridays / every week
    every 2 hours / every 30 minutes / every hour        (from now, at least 15 min)
    every 3 days / every other day / every 2 weeks       (optionally "at 9")
    monthly / every month on the 15th / every 1st / the 1st of every month
e.g. "every day at 9", "at 8:30 on weekdays", "every friday 18:00",
"every 2 hours", "every month on the 1st at 10".
"""

import re

from calendar        import Day
from dataclasses     import dataclass
from datetime        import date, datetime, time, timedelta
from typing          import Optional

from core.numbers     import SPOKEN, normalize_numbers
from core.numbers     import TENS as NUMBER_TENS, UNITS as NUMBER_UNITS
from core.typos       import Vocabulary
from enums           import RepeatKind
from core.recurrence import (
    EVERY_DAY, WEEKDAYS as WORKDAYS, WEEKENDS, Interval, Monthly, Recurrence, Weekly,
)


class ParseError(ValueError):
    """The request could not be understood; the message is shown to the user."""


class MissingText(ParseError):
    """A time but nothing to remind about ("tomorrow at 12"): the bot asks what for."""


class MissingTime(ParseError):
    """No time the parser understands ("to call mom"): the bot asks when.

    `text` is the request cleaned up as reminder text ("call mom").
    """

    def __init__(self, message: str, text: str):
        super().__init__(message)
        self.text = text


@dataclass
class ParsedReminder:
    when: datetime   # timezone-aware, in the user's timezone; first occurrence if recurring
    text: str
    recurrence: Optional[Recurrence] = None


DEFAULT_TIME = time(9, 0)

# Before this time, "tomorrow" still means the coming day: at 01:00 on Sunday,
# "tomorrow at 9" is Sunday 09:00, not Monday.
LATE_NIGHT_END = time(4, 0)

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
}

UNITS = {
    "s": "seconds", "sec": "seconds", "secs": "seconds", "second": "seconds", "seconds": "seconds",
    "m": "minutes", "min": "minutes", "mins": "minutes", "minute": "minutes", "minutes": "minutes",
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours", "hours": "hours",
    "d": "days", "day": "days", "days": "days",
    "w": "weeks", "wk": "weeks", "wks": "weeks", "week": "weeks", "weeks": "weeks",
}

WEEKDAYS = {
    "monday": Day.MONDAY, "mon": Day.MONDAY,
    "tuesday": Day.TUESDAY, "tue": Day.TUESDAY, "tues": Day.TUESDAY,
    "wednesday": Day.WEDNESDAY, "wed": Day.WEDNESDAY,
    "thursday": Day.THURSDAY, "thu": Day.THURSDAY, "thur": Day.THURSDAY, "thurs": Day.THURSDAY,
    "friday": Day.FRIDAY, "fri": Day.FRIDAY,
    "saturday": Day.SATURDAY, "sat": Day.SATURDAY,
    "sunday": Day.SUNDAY, "sun": Day.SUNDAY,
}

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12,
}

# Only full names have plurals ("mondays"); "tues" is not "tue" + s.
FULL_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}

DAY_PARTS = {
    "morning": time(9, 0), "afternoon": time(15, 0), "evening": time(19, 0),
    "night": time(21, 0), "noon": time(12, 0), "midday": time(12, 0), "midnight": time(0, 0),
}

# Shortest "every N minutes" reminder.
MIN_INTERVAL = timedelta(minutes=15)

# Words of time expressions whose typos are fixed on a second try
# ("tomorow", "wensday", "evry"), each with its meaning (core/typos.py).
TIME_VOCABULARY = Vocabulary({
    **{w: f"weekday:{d}" for w, d in WEEKDAYS.items()},
    **{f"{w}s": f"weekdays:{WEEKDAYS[w]}" for w in FULL_WEEKDAYS},
    **{w: f"month:{n}" for w, n in MONTHS.items()},
    **{w: f"unit:{u}" for w, u in UNITS.items()},
    **{w: f"number:{n}" for w, n in {**NUMBER_UNITS, **NUMBER_TENS}.items()},
    **{w: w for w in DAY_PARTS},
    **{w: w for w in [
        "today", "tonight", "tomorrow", "next", "after", "every", "everyday", "daily", "monthly",
        "weekday", "weekdays", "weekend", "weekends", "month", "other", "half", "quarter", "past",
    ]},
})

# Parts of the day that make "at 9" mean 21:00.
EVENING_PARTS = {"tonight", "afternoon", "evening", "night"}

# Words that may sit between parts of a time expression ("on friday at 9").
CONNECTORS = {"at", "on", "by", "for", "this", "the", "of", "and"}

# Words that separate the time expression from the reminder text.
TEXT_PREFIXES = ("to ", "that ", "about ", "for ", ": ", "- ", "— ")

COMPACT_DURATION = re.compile(r"^(?:(\d+(?:\.\d+)?)(h|m|d|w|s))+$")
COMPACT_PART = re.compile(r"(\d+(?:\.\d+)?)(h|m|d|w|s)")
TIME_RE = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?(am|pm|a\.m\.|p\.m\.)?$")
NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$")
# "21.20" could be a date (24.12) or a time; see _parse_when_tokens.
DOTTED_CLOCK_RE = re.compile(r"^\d{1,2}\.\d{2}$")
ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
ORDINAL_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?$")
MONTH_DAY_ONLY_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)$")


@dataclass
class _When:
    delta: Optional[timedelta] = None
    day: Optional[date] = None
    weekday: Optional[int] = None
    next_week: bool = False
    clock: Optional[time] = None
    clock_ambiguous: bool = False   # "at 9": could be 09:00 or 21:00
    explicit_year: bool = False
    part: Optional[str] = None      # "tonight", or "in the evening" etc.: applied to the clock at the end
    month_day: Optional[int] = None # "on the 15th": a day of whichever month comes next


def _number(token: str) -> Optional[float]:
    if token in NUMBER_WORDS:
        return float(NUMBER_WORDS[token])
    try:
        return float(token)
    except ValueError:
        return None


def _read_duration(tokens: list, i: int):
    """Read "2 hours and 30 minutes" / "1h30m" / "half an hour" starting at i.

    Returns (next index, timedelta) or (i, None) if nothing was read.
    """
    total = timedelta()
    start = i
    while i < len(tokens):
        tok = tokens[i]

        if COMPACT_DURATION.match(tok):
            for value, unit in COMPACT_PART.findall(tok):
                total += timedelta(**{UNITS[unit]: float(value)})
            i += 1
        elif tok == "half" and tokens[i + 1:i + 3] in (["an", "hour"], ["a", "day"]):
            unit = UNITS[tokens[i + 2]]
            total += timedelta(**{unit: 0.5})
            i += 3
        elif (value := _number(tok)) is not None and i + 1 < len(tokens) and tokens[i + 1] in UNITS:
            unit = UNITS[tokens[i + 1]]
            i += 2
            # "an hour and a half"
            if tokens[i:i + 3] == ["and", "a", "half"]:
                value += 0.5
                i += 3
            total += timedelta(**{unit: value})
        elif tok == "and" and i > start and i + 1 < len(tokens):
            i += 1
            continue
        else:
            break

    if i == start or total <= timedelta():
        return start, None
    return i, total


def _read_clock(tokens: list, i: int, after_at: bool):
    """Read "9", "9am", "9 pm", "9:30", "18:00", "noon" starting at i."""
    tok = tokens[i]

    if tok in DAY_PARTS:
        return i + 1, DAY_PARTS[tok], False

    # Spoken clock times ("nine thirty" → "9:30~", see core/numbers.py) are
    # ambiguous like "at 9": the next 09:30 or 21:30.
    spoken = tok.endswith(SPOKEN)
    m = TIME_RE.match(tok.removesuffix(SPOKEN))
    if not m:
        return i, None, False

    hour, minute, suffix = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    nxt = i + 1
    if suffix is None and nxt < len(tokens) and tokens[nxt] in ("am", "pm", "a.m.", "p.m."):
        suffix = tokens[nxt]
        nxt += 1

    # A bare number is only a time right after "at" ("at 9"), never on its own.
    if suffix is None and m.group(2) is None and not after_at:
        return i, None, False

    if suffix:
        if not 1 <= hour <= 12:
            return i, None, False
        hour = hour % 12 + (12 if suffix.startswith("p") else 0)
        ambiguous = False
    else:
        # "at 9" could be 09:00 or 21:00; typed "9:30", "09" and "18:00" are taken as written.
        ambiguous = (m.group(2) is None or spoken) and 1 <= hour <= 11 and not m.group(1).startswith("0")

    if hour > 23 or minute > 59:
        return i, None, False
    return nxt, time(hour, minute), ambiguous


def _is_dotted_clock(tokens: list, i: int) -> bool:
    """"21.20" or "9.20 pm": a valid time written with a dot instead of a colon."""
    return bool(DOTTED_CLOCK_RE.match(tokens[i])) and _read_clock(tokens, i, after_at=True)[1] is not None


def _read_date(tokens: list, i: int, today: date):
    """Read "24.12", "2026-12-24", "dec 24", "24th of december 2026"."""
    tok = tokens[i]

    if m := ISO_DATE_RE.match(tok):
        return i + 1, _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))), True

    if m := NUMERIC_DATE_RE.match(tok):
        year = m.group(3)
        if year is not None:
            year = int(year) + (2000 if len(year) == 2 else 0)
        return i + 1, _safe_date(year or today.year, int(m.group(2)), int(m.group(1))), year is not None

    # "dec 24" / "december 24th" [2026]
    if tok in MONTHS and i + 1 < len(tokens) and (d := ORDINAL_RE.match(tokens[i + 1])):
        return _with_year(tokens, i + 2, today, MONTHS[tok], int(d.group(1)))

    # "24 dec" / "24th of december" [2026]
    if d := ORDINAL_RE.match(tok):
        j = i + 1
        if j < len(tokens) and tokens[j] == "of":
            j += 1
        if j < len(tokens) and tokens[j] in MONTHS:
            return _with_year(tokens, j + 1, today, MONTHS[tokens[j]], int(d.group(1)))

    return i, None, False


def _next_month_day(start: date, day: int) -> Optional[date]:
    """The first date on or after `start` that is that day of a month (skipping short months)."""
    if not 1 <= day <= 31:
        return None
    year, month = start.year, start.month
    for _ in range(13):
        candidate = _safe_date(year, month, day)
        if candidate is not None and candidate >= start:
            return candidate
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def _with_year(tokens, j, today, month, day):
    if j < len(tokens) and re.fullmatch(r"\d{4}", tokens[j]):
        return j + 1, _safe_date(int(tokens[j]), month, day), True
    return j, _safe_date(today.year, month, day), False


def _safe_date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _tokenize(phrase: str) -> list:
    phrase = re.sub(r"\b(?:a )?couple of\b", "2", phrase.lower())
    tokens = []
    for raw in phrase.replace(",", " ").split():
        tok = raw.strip(":;!?")
        if tok.endswith(".") and not tok.endswith(("a.m.", "p.m.")):
            tok = tok[:-1]
        if tok:
            tokens.append(tok)
    return normalize_numbers(tokens)


def _tomorrow(now: datetime) -> date:
    if now.time() < LATE_NIGHT_END:
        # Still "last night": the user hasn't slept yet.
        return now.date()
    return now.date() + timedelta(days=1)


def _parse_when_tokens(tokens: list, now: datetime) -> Optional[_When]:
    """Parse tokens that must form one complete time expression."""
    w = _When()
    today = now.date()
    i = 0
    after_at = False

    while i < len(tokens):
        tok = tokens[i]

        if tok == "in" and w.delta is None:
            j, delta = _read_duration(tokens, i + 1)
            if delta is not None:
                w.delta, i = delta, j
                continue
            if tokens[i + 1:i + 2] == ["the"] and i + 2 < len(tokens) \
                    and tokens[i + 2] in DAY_PARTS and w.part is None:
                # "in the morning"; after a time, "at 7 in the evening" means 19:00
                w.part = tokens[i + 2]
                i += 3
                continue
            return None

        if tok in CONNECTORS:
            after_at = tok == "at"
            i += 1
            continue

        if w.day is None and w.weekday is None and not w.next_week:
            if tok == "today":
                w.day, i = today, i + 1
                continue
            if tok == "tonight":
                w.day, w.part, i = today, "tonight", i + 1
                continue
            if tok == "tomorrow":
                w.day, i = _tomorrow(now), i + 1
                continue
            if tokens[i:i + 3] == ["day", "after", "tomorrow"]:
                w.day, i = _tomorrow(now) + timedelta(days=1), i + 3
                continue
            if tok == "next" and i + 1 < len(tokens) and tokens[i + 1] in WEEKDAYS:
                w.weekday, w.next_week, i = WEEKDAYS[tokens[i + 1]], True, i + 2
                continue
            if tok == "next" and tokens[i + 1:i + 2] == ["week"]:
                w.day, i = today + timedelta(days=7), i + 2
                continue
            if tok in WEEKDAYS:
                w.weekday, i = WEEKDAYS[tok], i + 1
                continue
            # "on the 15th" (no month): the next 15th
            if (m := MONTH_DAY_ONLY_RE.match(tok)) and tokens[i + 1:i + 2] != ["of"] \
                    and not (i + 1 < len(tokens) and tokens[i + 1] in MONTHS):
                w.month_day = int(m.group(1))
                w.day, i = _next_month_day(today, w.month_day), i + 1
                if w.day is None:
                    return None
                continue
            j, d, explicit_year = _read_date(tokens, i, today)
            # "21.20" is no date, and "at 10.11" is a time: read them as a clock below.
            if j != i and not ((d is None or after_at) and _is_dotted_clock(tokens, i)):
                if d is None:
                    return None
                w.day, w.explicit_year, i = d, explicit_year, j
                continue

        if w.clock is None:
            j, clock, ambiguous = _read_clock(tokens, i, after_at)
            if clock is not None:
                w.clock, w.clock_ambiguous, i = clock, ambiguous, j
                after_at = False
                continue

        return None

    if tokens[-1] in CONNECTORS:
        # "tomorrow at" is not a complete time
        return None
    if w.part is not None:
        if w.delta is not None:
            return None
        if w.clock is None:
            w.clock = time(20, 0) if w.part == "tonight" else DAY_PARTS[w.part]
        elif w.part in EVENING_PARTS and w.clock.hour < 12:
            # "tonight at 9", "at 7 in the evening"
            w.clock = time(w.clock.hour + 12, w.clock.minute)
        w.clock_ambiguous = False
    if w.delta is None and w.day is None and w.weekday is None and w.clock is None:
        return None
    if w.delta is not None and (w.day or w.weekday is not None or w.clock):
        return None
    return w


def _resolve(w: _When, now: datetime) -> datetime:
    if w.delta is not None:
        return now + w.delta

    tz = now.tzinfo
    today = now.date()

    if w.weekday is not None:
        ahead = (w.weekday - today.weekday()) % 7
        if w.next_week and ahead == 0:
            ahead = 7
        day = today + timedelta(days=ahead)
    else:
        day = w.day

    def at(d, clock):
        return datetime.combine(d, clock, tzinfo=tz)

    if day is None:
        # Time only: the next occurrence of that time (today or tomorrow).
        candidates = [w.clock]
        if w.clock_ambiguous:
            candidates.append(time(w.clock.hour + 12, w.clock.minute))
        options = [at(today + timedelta(days=n), c) for n in (0, 1) for c in candidates]
        return min(o for o in options if o > now)

    clock = w.clock or DEFAULT_TIME
    result = at(day, clock)

    if w.clock_ambiguous and w.weekday is None and result <= now:
        # "today at 5" in the afternoon means 17:00
        later = at(day, time(clock.hour + 12, clock.minute))
        if later > now:
            result = later

    if result <= now:
        if w.weekday is not None:
            # "friday 9:00" said on Friday at 10:00 means next Friday
            result += timedelta(days=7)
        elif w.month_day is not None:
            # "the 15th" said on the 15th after that time means next month's
            nxt = _next_month_day(day + timedelta(days=1), w.month_day)
            result = at(nxt, clock)
        elif day < today and not w.explicit_year:
            # "dec 24" said on dec 25 means next year
            result = result.replace(year=result.year + 1)

    return result


def parse_duration(phrase: str) -> Optional[timedelta]:
    """Parse a complete duration like "10m", "1 hour", "1h30m" or "half an hour"."""
    tokens = _tokenize(phrase)
    if not tokens:
        return None
    j, delta = _read_duration(tokens, 0)
    if delta is None or j != len(tokens):
        return None
    return delta


def parse_when(phrase: str, now: datetime) -> Optional[datetime]:
    """Parse a complete time expression, or return None."""
    tokens = _tokenize(phrase)
    if not tokens:
        return None
    w = _parse_when_tokens(tokens, now)
    if w is None:
        return None
    return _resolve(w, now)


def _read_weekday_list(tokens: list, i: int, plural: bool):
    """Read "monday and thursday" / "mondays, fridays" starting at i."""
    def weekday(tok):
        if plural:
            return WEEKDAYS[tok[:-1]] if tok.endswith("s") and tok[:-1] in FULL_WEEKDAYS else None
        return WEEKDAYS.get(tok)

    days = set()
    while i < len(tokens) and (d := weekday(tokens[i])) is not None:
        days.add(d)
        i += 1
        if tokens[i:i + 1] == ["and"] and i + 1 < len(tokens) and weekday(tokens[i + 1]) is not None:
            i += 1
    return i, days


# Ordinal day of the month in a monthly expression: "15th", "1st".
MONTH_DAY_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)$")
MONTH_WORDS = (["of", "every", "month"], ["of", "the", "month"], ["every", "month"])


@dataclass
class _Repeat:
    kind: RepeatKind
    days: frozenset = None              # weekly
    day: Optional[int] = None           # monthly; None = to be found, or today's
    every: Optional[timedelta] = None   # interval
    clock: Optional[time] = None        # from a day part ("every evening")


def _month_day(tok: str) -> Optional[int]:
    m = MONTH_DAY_RE.match(tok)
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 31 else None


def _skip_month_words(tokens: list, j: int) -> int:
    for words in MONTH_WORDS:
        if tokens[j:j + len(words)] == words:
            return j + len(words)
    return j


def _read_recurrence(tokens: list, i: int, now: datetime):
    """Read "every day", "daily", "on weekdays", "mondays", "every 2 hours",
    "monthly", "the 1st of every month" starting at i.

    Returns (next index, _Repeat), or (i, None).
    """
    tok = tokens[i]
    nxt = tokens[i + 1] if i + 1 < len(tokens) else None

    if tok in ("daily", "everyday"):
        return i + 1, _Repeat(RepeatKind.WEEKLY, days=EVERY_DAY)
    if tok == "weekdays":
        return i + 1, _Repeat(RepeatKind.WEEKLY, days=WORKDAYS)
    if tok == "weekends":
        return i + 1, _Repeat(RepeatKind.WEEKLY, days=WEEKENDS)
    if tok == "monthly":
        return i + 1, _Repeat(RepeatKind.MONTHLY)
    j, days = _read_weekday_list(tokens, i, plural=True)
    if days:
        return j, _Repeat(RepeatKind.WEEKLY, days=frozenset(days))
    # "the 1st of every month"
    if (day := _month_day(tok)) is not None and (j := _skip_month_words(tokens, i + 1)) > i + 1:
        return j, _Repeat(RepeatKind.MONTHLY, day=day)

    if tok != "every" or nxt is None:
        return i, None
    if nxt == "day":
        return i + 2, _Repeat(RepeatKind.WEEKLY, days=EVERY_DAY)
    if nxt == "weekday":
        return i + 2, _Repeat(RepeatKind.WEEKLY, days=WORKDAYS)
    if nxt == "weekend":
        return i + 2, _Repeat(RepeatKind.WEEKLY, days=WEEKENDS)
    if nxt == "week":
        return i + 2, _Repeat(RepeatKind.WEEKLY, days=frozenset({Day(now.weekday())}))
    if nxt == "month":
        return i + 2, _Repeat(RepeatKind.MONTHLY)
    if nxt in ("morning", "afternoon", "evening", "night"):
        return i + 2, _Repeat(RepeatKind.WEEKLY, days=EVERY_DAY, clock=DAY_PARTS[nxt])
    # "every 15th [of the month]"
    if (day := _month_day(nxt)) is not None:
        return _skip_month_words(tokens, i + 2), _Repeat(RepeatKind.MONTHLY, day=day)
    j, days = _read_weekday_list(tokens, i + 1, plural=False)
    if days:
        return j, _Repeat(RepeatKind.WEEKLY, days=frozenset(days))
    # "every hour" / "every other day" / "every 2 hours"
    if nxt in UNITS and UNITS[nxt] != "seconds":
        return i + 2, _Repeat(RepeatKind.INTERVAL, every=timedelta(**{UNITS[nxt]: 1}))
    if nxt == "other" and i + 2 < len(tokens) and UNITS.get(tokens[i + 2]) in ("days", "weeks"):
        return i + 3, _Repeat(RepeatKind.INTERVAL, every=timedelta(**{UNITS[tokens[i + 2]]: 2}))
    j, delta = _read_duration(tokens, i + 1)
    if delta is not None:
        return j, _Repeat(RepeatKind.INTERVAL, every=delta)
    return i, None


def _repeat_clock(rest: list, now: datetime, part_clock: Optional[time]):
    """The time of day from the words around a repeat: (ok, clock or None)."""
    if not rest or all(t in CONNECTORS for t in rest):
        return (not rest or rest[-1] != "at"), part_clock
    w = _parse_when_tokens(rest, now)
    if w is None or w.clock is None or w.delta is not None \
            or w.day is not None or w.weekday is not None or w.next_week:
        return False, None
    clock = w.clock
    if w.clock_ambiguous and part_clock is not None and part_clock.hour >= 12:
        # "every evening at 7" is 19:00
        clock = time(clock.hour + 12, clock.minute)
    return True, clock


def parse_recurrence(phrase: str, now: datetime) -> Optional[tuple]:
    """Parse a complete recurring expression: (first occurrence, Recurrence) or None.

    Raises ParseError for an understood but unsupported interval.
    """
    tokens = ["every" if t == "each" else t for t in _tokenize(phrase)]
    for i in range(len(tokens)):
        j, repeat = _read_recurrence(tokens, i, now)
        if repeat is not None:
            break
    else:
        return None

    rest = tokens[:i] + tokens[j:]
    if repeat.kind == RepeatKind.MONTHLY and repeat.day is None:
        # "every month on the 15th"
        for k, tok in enumerate(rest):
            if (day := _month_day(tok)) is not None:
                repeat.day = day
                del rest[k]
                break

    ok, clock = _repeat_clock(rest, now, repeat.clock)
    if not ok:
        return None

    if repeat.kind == RepeatKind.WEEKLY:
        recurrence = Weekly(repeat.days, clock or DEFAULT_TIME)
    elif repeat.kind == RepeatKind.MONTHLY:
        recurrence = Monthly(repeat.day or now.day, clock or DEFAULT_TIME)
    else:
        every = repeat.every
        if every < MIN_INTERVAL:
            raise ParseError(f"The shortest repeat is every {MIN_INTERVAL.seconds // 60} minutes.")
        if every % timedelta(minutes=1):
            raise ParseError("Repeats must be in whole minutes.")
        if every % timedelta(days=1) == timedelta():
            # "every 3 days [at 9]": the first one at the next 09:00
            first = Weekly(EVERY_DAY, clock or DEFAULT_TIME).next_after(now, now.tzinfo)
        elif clock is not None:
            return None
        else:
            # "every 2 hours": the first one 2 hours from now
            first = (now + every).replace(second=0, microsecond=0)
        recurrence = Interval(every, first)

    return recurrence.next_after(now, now.tzinfo), recurrence


def _parse_time(phrase: str, now: datetime) -> Optional[tuple]:
    """A one-off or recurring time expression: (when, Recurrence or None)."""
    when = parse_when(phrase, now)
    if when is not None:
        return when, None
    return parse_recurrence(phrase, now)


def _clean_text(text: str) -> str:
    text = text.strip()
    lowered = text.lower()
    for prefix in TEXT_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text.strip(" ,:;-—").strip()


def _is_text(text: str, now: datetime) -> bool:
    # Leftover words that are themselves a time ("tomorrow" in
    # "tomorrow at 9") mean the split was wrong.
    return bool(text) and _parse_time(text, now) is None


def _split(words: list, time_words: list, fixed: list, now: datetime) -> Optional[tuple]:
    """The longest time expression at the start or the end: (k, (when, recurrence), text).

    The time is read from `time_words`, the text is taken from `words`, and
    the text must not be a time even with typos fixed (`fixed`), so
    "tomorow at 9" isn't a reminder called “tomorow”. All three are word
    for word the same message.
    """
    best = None   # (number of words used for the time, (when, recurrence), text)
    for k in range(len(words), 0, -1):
        # Time expression at the start: "tomorrow at 9 to pay rent"
        parsed = _parse_time(" ".join(time_words[:k]), now)
        if parsed is not None and _is_text(_clean_text(" ".join(fixed[k:])), now):
            text = _clean_text(" ".join(words[k:]))
            if best is None or k > best[0]:
                best = (k, parsed, text)
        # Time expression at the end: "to pay rent tomorrow at 9"
        parsed = _parse_time(" ".join(time_words[-k:]), now)
        if parsed is not None and _is_text(_clean_text(" ".join(fixed[:-k])), now):
            text = _clean_text(" ".join(words[:-k]))
            if best is None or k > best[0]:
                best = (k, parsed, text)
        if best is not None:
            return best
    return None


def _mishearings(words: list, now: datetime) -> list:
    """Words with speech-to-text mishearings fixed: "to borrow" is "tomorrow",
    and a "too" right after the time is "to". Only used on a second try."""
    out, i = [], 0
    while i < len(words):
        if words[i].lower() == "to" and i + 1 < len(words) and words[i + 1].lower() == "borrow":
            out.append("tomorrow")
            i += 2
            # "to borrow at 9 too start ...": the first "too" is "to" only if
            # everything before it is the time, so a "too" inside the text stays.
            for j in range(i, len(words)):
                if words[j].lower() == "too":
                    before = TIME_VOCABULARY.fix_all(out + words[i:j])
                    if j + 1 < len(words) and _parse_time(" ".join(before), now) is not None:
                        words = words[:j] + ["to"] + words[j + 1:]
                    break
        else:
            out.append(words[i])
            i += 1
    return out


def parse_reminder(request: str, now: datetime) -> ParsedReminder:
    """Split "in two hours to call mom" into a time and a text.

    `request` is the message with the trigger phrase ("remind me") already
    removed. `now` must be timezone-aware, in the user's timezone.
    """
    words = request.split()
    if not words:
        raise ParseError("What should I remind you about, and when?")

    fixed = TIME_VOCABULARY.fix_all(words)
    best = _split(words, words, fixed, now)
    if best is None and fixed != words:
        # Second try with typos in time words fixed ("tomorow at 9"). The
        # text keeps the words as written.
        best = _split(words, fixed, fixed, now)

    if best is None:
        heard = _mishearings(words, now)
        if heard != words:
            fixed = TIME_VOCABULARY.fix_all(heard)
            words = heard
            best = _split(words, fixed, fixed, now)

    if best is None:
        if _parse_time(request, now) is not None or _parse_time(" ".join(fixed), now) is not None:
            raise MissingText("What should I remind you about?")
        raise MissingTime("I couldn't understand when.", _clean_text(request))

    _, (when, recurrence), text = best
    if when <= now:
        raise ParseError("That time has already passed.")
    return ParsedReminder(when=when, text=text, recurrence=recurrence)
