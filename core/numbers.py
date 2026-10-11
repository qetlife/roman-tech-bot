"""Spoken numbers → digits, so the parser reads speech like typed text.

Voice transcriptions (Vosk) spell everything out: "remind me at nine thirty",
"in twenty five minutes", "at half past six", "on the fifteenth". This turns
tokens like those into what the parser already understands: "9:30", "25",
"6:30", "15th". Used on the time expression only, never on the reminder text.
"""

# Marks a clock time that was spoken ("nine thirty" → "9:30~"): the parser
# treats it like "at 9" (the next 09:30 or 21:30), not as a literal 24-hour time.
SPOKEN = "~"

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

ORDINAL_UNITS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
}
ORDINAL_TENS = {"twentieth": 20, "thirtieth": 30}

# An ordinal is a day of the month only after these ("on the first", "every
# fifth", "december twenty fourth") or before "of" ("the first of may"), so
# "in a second" or "first thing" are left alone.
ORDINAL_BEFORE = {"the", "every", "each"}

MONTH_NAMES = {
    "january", "jan", "february", "feb", "march", "mar", "april", "apr", "may",
    "june", "jun", "july", "jul", "august", "aug", "september", "sep", "sept",
    "october", "oct", "november", "nov", "december", "dec",
}


def _suffix(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _read_number(tokens: list, i: int):
    """"twenty five" / "nine" → (next index, 25 / 9), or (i, None)."""
    tok = tokens[i]
    if tok in TENS:
        value = TENS[tok]
        if i + 1 < len(tokens) and tokens[i + 1] in UNITS and 1 <= UNITS[tokens[i + 1]] <= 9:
            return i + 2, value + UNITS[tokens[i + 1]]
        return i + 1, value
    if tok in UNITS:
        return i + 1, UNITS[tok]
    return i, None


def _read_ordinal(tokens: list, i: int):
    """"twenty fourth" / "first" → (next index, 24 / 1), or (i, None)."""
    tok = tokens[i]
    if tok in ORDINAL_TENS:
        return i + 1, ORDINAL_TENS[tok]
    if tok in ORDINAL_UNITS:
        return i + 1, ORDINAL_UNITS[tok]
    if tok in TENS and i + 1 < len(tokens) and tokens[i + 1] in ORDINAL_UNITS \
            and ORDINAL_UNITS[tokens[i + 1]] <= 9:
        return i + 2, TENS[tok] + ORDINAL_UNITS[tokens[i + 1]]
    return i, None


def _words_to_digits(tokens: list) -> list:
    out = []
    i = 0
    while i < len(tokens):
        prev = out[-1] if out else None
        j, day = _read_ordinal(tokens, i)
        if day is not None and 1 <= day <= 31 and (
                prev in ORDINAL_BEFORE or prev in MONTH_NAMES or tokens[j:j + 1] == ["of"]):
            out.append(f"{day}{_suffix(day)}")
            i = j
            continue
        j, value = _read_number(tokens, i)
        if value is not None:
            out.append(str(value))
            i = j
            continue
        out.append(tokens[i])
        i += 1
    return out


def _hour(tok: str):
    return int(tok) if tok.isdigit() and 0 <= int(tok) <= 23 else None


def _clock(hour: int, minute: int) -> str:
    """"9:30~" for 1-11 o'clock (could be morning or evening), "21:30" / "12:30" otherwise."""
    return f"{hour}:{minute:02d}" + (SPOKEN if 1 <= hour <= 11 else "")


def _clock_phrases(tokens: list) -> list:
    """Digits → clock times: "half past 6" → 6:30, "quarter to 5" → 4:45, "9 30" → 9:30."""
    out = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        after = tokens[i + 2] if i + 2 < len(tokens) else None

        # "(a) quarter past 9", "half past 6", "20 past 6", "quarter to 5", "10 to 5"
        minutes = {"half": 30, "quarter": 15}.get(tok) or (int(tok) if tok.isdigit() and 1 <= int(tok) <= 30 else None)
        if minutes is not None and nxt in ("past", "after", "to", "before") and after is not None \
                and (hour := _hour(after)) is not None and 1 <= hour <= 12 and not (tok == "half" and nxt in ("to", "before")):
            if out and out[-1] == "a" and tok == "quarter":
                out.pop()
            if nxt in ("past", "after"):
                out.append(_clock(hour, minutes))
            else:
                hour = 12 if hour == 1 else hour - 1
                out.append(_clock(hour, 60 - minutes))
            i += 3
            continue

        hour = _hour(tok)
        if hour is not None and nxt is not None:
            # "9 o'clock" → "9"
            if nxt in ("o'clock", "oclock"):
                out.append(tok)
                i += 2
                continue
            # "9 oh 5" → "9:05"
            if nxt == "oh" and after is not None and after.isdigit() and 1 <= int(after) <= 9:
                out.append(_clock(hour, int(after)))
                i += 3
                continue
            # "9 30" / "9 45" → "9:30" (minutes 10-59; "9 5" is too ambiguous)
            if nxt.isdigit() and 10 <= int(nxt) <= 59 and len(nxt) == 2 \
                    and not (after in _UNIT_WORDS):
                out.append(_clock(hour, int(nxt)))
                i += 2
                continue

        # "p m" / "a m" → "pm" / "am" after a time
        if tok in ("p", "a") and nxt == "m" and out and (out[-1].isdigit() or ":" in out[-1]):
            if out[-1].endswith(SPOKEN):
                out[-1] = out[-1].removesuffix(SPOKEN)
            out.append(tok + "m")
            i += 2
            continue

        out.append(tok)
        i += 1
    return out


# "2 30 minutes" is not 2:30
_UNIT_WORDS = {
    "s", "sec", "secs", "second", "seconds", "m", "min", "mins", "minute", "minutes",
    "h", "hr", "hrs", "hour", "hours", "d", "day", "days", "w", "wk", "wks", "week", "weeks",
}


def normalize_numbers(tokens: list, clocks: bool = True) -> list:
    """Lowercase tokens with spoken numbers → tokens with digits and clock times.

    clocks=False only converts numbers ("five fifteen sixty" → "5 15 60", for
    lists of minutes), without joining them into clock times.
    """
    split = []
    for tok in tokens:
        # "twenty-five" → "twenty", "five"
        if "-" in tok and all(part in UNITS or part in TENS or part in ORDINAL_UNITS for part in tok.split("-")):
            split.extend(tok.split("-"))
        else:
            split.append(tok)
    digits = _words_to_digits(split)
    return _clock_phrases(digits) if clocks else digits
