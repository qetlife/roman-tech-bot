"""Parse English reminder requests like "in two hours to call mom".

The parser is deliberately small and predictable: it understands a fixed set
of time expressions and refuses anything else, so the bot can ask the user to
rephrase instead of guessing wrong.

Supported "when" expressions (case-insensitive):
    in 2 hours / in two hours / in 1.5 hours / in 1h30m / in half an hour
    in an hour and a half / in 3 days / in a week
    at 9 / at 9am / at 9:30pm / at 18:00 / 18:00 / noon / midnight
    today / tonight / tomorrow / day after tomorrow
    morning / afternoon / evening / night
    monday / on friday / next friday / next week
    24.12 / 24/12 / 2026-12-24 / dec 24 / 24th of december 2026
and combinations of a day and a time, e.g. "tomorrow at 9", "friday 18:00",
"at 9 tomorrow", "tomorrow morning", "on dec 24 at 10am".
"""

import re

from dataclasses    import dataclass
from datetime       import date, datetime, time, timedelta
from typing         import Optional


class ParseError(ValueError):
    """The request could not be understood; the message is shown to the user."""


@dataclass
class ParsedReminder:
    when: datetime   # timezone-aware, in the user's timezone
    text: str


DEFAULT_TIME = time(9, 0)

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
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12,
}

DAY_PARTS = {
    "morning": time(9, 0), "afternoon": time(15, 0), "evening": time(19, 0),
    "night": time(21, 0), "noon": time(12, 0), "midday": time(12, 0), "midnight": time(0, 0),
}

# Words that may sit between parts of a time expression ("on friday at 9").
CONNECTORS = {"at", "on", "by", "for", "this", "the", "of", "and"}

# Words that separate the time expression from the reminder text.
TEXT_PREFIXES = ("to ", "that ", "about ", "for ", ": ", "- ", "— ")

COMPACT_DURATION = re.compile(r"^(?:(\d+(?:\.\d+)?)(h|m|d|w|s))+$")
COMPACT_PART = re.compile(r"(\d+(?:\.\d+)?)(h|m|d|w|s)")
TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(am|pm|a\.m\.|p\.m\.)?$")
NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$")
ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
ORDINAL_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?$")


@dataclass
class _When:
    delta: Optional[timedelta] = None
    day: Optional[date] = None
    weekday: Optional[int] = None
    next_week: bool = False
    clock: Optional[time] = None
    clock_ambiguous: bool = False   # "at 9": could be 09:00 or 21:00
    explicit_year: bool = False


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

    m = TIME_RE.match(tok)
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
        # "at 9" could be 09:00 or 21:00; "9:30", "09" and "18:00" are taken as written.
        ambiguous = m.group(2) is None and 1 <= hour <= 11 and not m.group(1).startswith("0")

    if hour > 23 or minute > 59:
        return i, None, False
    return nxt, time(hour, minute), ambiguous


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
    return tokens


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
                    and tokens[i + 2] in DAY_PARTS and w.clock is None:
                # "in the morning"
                w.clock = DAY_PARTS[tokens[i + 2]]
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
                w.day, i = today, i + 1
                if w.clock is None:
                    w.clock = time(20, 0)
                continue
            if tok == "tomorrow":
                w.day, i = today + timedelta(days=1), i + 1
                continue
            if tokens[i:i + 3] == ["day", "after", "tomorrow"]:
                w.day, i = today + timedelta(days=2), i + 3
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
            j, d, explicit_year = _read_date(tokens, i, today)
            if j != i:
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
        elif day < today and not w.explicit_year:
            # "dec 24" said on dec 25 means next year
            result = result.replace(year=result.year + 1)

    return result


def parse_when(phrase: str, now: datetime) -> Optional[datetime]:
    """Parse a complete time expression, or return None."""
    tokens = _tokenize(phrase)
    if not tokens:
        return None
    w = _parse_when_tokens(tokens, now)
    if w is None:
        return None
    return _resolve(w, now)


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
    return bool(text) and parse_when(text, now) is None


def parse_reminder(request: str, now: datetime) -> ParsedReminder:
    """Split "in two hours to call mom" into a time and a text.

    `request` is the message with the trigger phrase ("remind me") already
    removed. `now` must be timezone-aware, in the user's timezone.
    """
    words = request.split()
    if not words:
        raise ParseError("What should I remind you about, and when?")

    best = None   # (number of words used for the time, when, text)
    for k in range(len(words), 0, -1):
        # Time expression at the start: "tomorrow at 9 to pay rent"
        when = parse_when(" ".join(words[:k]), now)
        if when is not None:
            text = _clean_text(" ".join(words[k:]))
            if _is_text(text, now) and (best is None or k > best[0]):
                best = (k, when, text)
        # Time expression at the end: "to pay rent tomorrow at 9"
        when = parse_when(" ".join(words[-k:]), now)
        if when is not None:
            text = _clean_text(" ".join(words[:-k]))
            if _is_text(text, now) and (best is None or k > best[0]):
                best = (k, when, text)
        if best is not None:
            break

    if best is None:
        if parse_when(request, now) is not None:
            raise ParseError("What should I remind you about?")
        raise ParseError("I couldn't understand when.")

    _, when, text = best
    if when <= now:
        raise ParseError("That time has already passed.")
    return ParsedReminder(when=when, text=text)
