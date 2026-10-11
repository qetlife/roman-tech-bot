"""All user settings: key, default, validation and label.

Defaults live here, in code. The user_settings table only stores values a
user changed. To add a setting, add a Setting below (no migration needed).
"""

import re

from datetime    import time

from dataclasses import dataclass
from typing      import Any, Callable

from core.numbers import SPOKEN, normalize_numbers
from core.parser  import parse_duration


@dataclass(frozen=True)
class Setting:
    key: str
    default: Any
    # Returns the normalized value or raises ValueError (message shown to the user).
    validate: Callable[[Any], Any]
    label: str


# --- snooze options ---------------------------------------------------------

SNOOZE_MIN_MINUTES = 1
SNOOZE_MAX_MINUTES = 24 * 60
SNOOZE_MAX_OPTIONS = 3


def validate_snooze_options(value) -> list:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("Give at least one snooze option.")
    if any(not isinstance(m, int) or isinstance(m, bool) for m in value):
        raise ValueError("Snooze options must be whole minutes.")
    minutes = sorted(set(value))
    if len(minutes) > SNOOZE_MAX_OPTIONS:
        raise ValueError(f"At most {SNOOZE_MAX_OPTIONS} snooze options.")
    if minutes[0] < SNOOZE_MIN_MINUTES or minutes[-1] > SNOOZE_MAX_MINUTES:
        raise ValueError("Each snooze option must be between 1 minute and 24 hours.")
    return minutes


def parse_snooze_options(text: str) -> list:
    """"10m, 1h, 3h" / "5 15 60" / "10 min, 1 hour" / "ten minutes and one hour" -> sorted minutes."""
    # Spoken numbers (voice messages): "ten" → "10"
    text = " ".join(normalize_numbers(text.lower().replace(",", " , ").split(), clocks=False))
    parts = [p.strip() for p in re.split(r"[,;]|\band\b", text) if p.strip()]
    if len(parts) == 1 and len(parts[0].split()) > 1:
        # "5 15 60" or "10m 1h": no commas, so each word is an option
        words = parts[0].split()
        if all(re.fullmatch(r"\d+|(?:\d+(?:\.\d+)?[hmdw])+", w) for w in words):
            parts = words

    minutes = []
    for part in parts:
        if part.isdigit():
            minutes.append(int(part))
            continue
        delta = parse_duration(part)
        if delta is None:
            raise ValueError(f"I don't understand “{part}”.")
        total = delta.total_seconds() / 60
        if total != int(total):
            raise ValueError(f"“{part}” isn't a whole number of minutes.")
        minutes.append(int(total))
    return validate_snooze_options(minutes)


def format_minutes(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h" if not mins else f"{hours} h {mins} min"


SNOOZE_OPTIONS = Setting(
    key="reminders.snooze_options",
    default=[10, 60],
    validate=validate_snooze_options,
    label="💤 Snooze options",
)

SNOOZE_PRESETS = [[5, 15, 60], [10, 60], [10, 30, 120]]


# --- repeat interval --------------------------------------------------------

REPEAT_MIN_MINUTES = 1
REPEAT_MAX_MINUTES = 60


def validate_repeat_minutes(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("The repeat interval must be whole minutes.")
    if not REPEAT_MIN_MINUTES <= value <= REPEAT_MAX_MINUTES:
        raise ValueError("The repeat interval must be between 1 and 60 minutes.")
    return value


REPEAT_MINUTES = Setting(
    key="reminders.repeat_minutes",
    default=5,
    validate=validate_repeat_minutes,
    label="🔁 Repeat interval",
)

REPEAT_PRESETS = [2, 5, 10, 15, 30, 60]


# --- quiet hours ------------------------------------------------------------
# Stored as ["00:00", "07:00"] (local start, end); [] = off.

CLOCK_RE = re.compile(r"^([01]?\d|2[0-3])(?::([0-5]\d))?$")


def _clock(text: str) -> time:
    m = CLOCK_RE.match(text.strip())
    if not m:
        raise ValueError(f"“{text.strip()}” isn't a time like 23:00.")
    return time(int(m.group(1)), int(m.group(2) or 0))


def validate_quiet_hours(value) -> list:
    if value == []:
        return []
    if not isinstance(value, (list, tuple)) or len(value) != 2 \
            or not all(isinstance(v, str) for v in value):
        raise ValueError("Quiet hours need a start and an end.")
    start, end = (_clock(v) for v in value)
    if start == end:
        raise ValueError("Quiet hours must start and end at different times.")
    return [f"{start:%H:%M}", f"{end:%H:%M}"]


SPOKEN_CLOCK_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$")


def _to_24h(part: str) -> str:
    """"11 pm" / "eleven thirty p m" / "23" -> "23" / "23:30" / "23"; anything else unchanged."""
    words = " ".join(normalize_numbers(part.split())).replace(SPOKEN, "")
    m = SPOKEN_CLOCK_RE.match(words)
    if not m or not m.group(3):
        return words
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if not 1 <= hour <= 12:
        return part
    hour = hour % 12 + (12 if m.group(3).startswith("p") else 0)
    return f"{hour}:{minute:02d}"


def parse_quiet_hours(text: str) -> list:
    """"23:00-07:00" / "23 to 7" / "22:30 - 8" / "eleven pm to seven" / "off" -> stored value."""
    text = text.strip().lower()
    if text in ("off", "none", "no", "disable", "disabled"):
        return []
    # Split first: in "ten to five", "to" separates the start and the end.
    parts = re.split(r"\s*(?:-|–|—|\bto\b|\buntil\b|\btill\b)\s*", text)
    if len(parts) != 2:
        raise ValueError("Send a start and an end, e.g. “23:00-07:00”.")
    return validate_quiet_hours([_to_24h(p) for p in parts])


def quiet_window(value):
    """Stored value -> (start, end) times, or None when off."""
    if not value:
        return None
    return _clock(value[0]), _clock(value[1])


def format_quiet_hours(value) -> str:
    return f"{value[0]}–{value[1]}" if value else "Off"


QUIET_HOURS = Setting(
    key="reminders.quiet_hours",
    default=["00:00", "07:00"],
    validate=validate_quiet_hours,
    label="🌙 Quiet hours",
)

QUIET_PRESETS = [["00:00", "07:00"], ["23:00", "07:00"], ["22:00", "08:00"]]


SETTINGS = {s.key: s for s in [SNOOZE_OPTIONS, REPEAT_MINUTES, QUIET_HOURS]}
