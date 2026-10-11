"""All user settings: key, default, validation and label.

Defaults live here, in code. The user_settings table only stores values a
user changed. To add a setting, add a Setting below (no migration needed).
"""

import re

from dataclasses        import dataclass
from typing             import Any, Callable

from reminders.parser   import parse_duration


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
    """"10m, 1h, 3h" / "5 15 60" / "10 min, 1 hour" -> sorted minutes."""
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


SETTINGS = {s.key: s for s in [SNOOZE_OPTIONS, REPEAT_MINUTES]}
