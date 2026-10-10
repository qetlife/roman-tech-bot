import re

from datetime   import datetime, timedelta
from functools  import lru_cache
from typing     import Optional
from zoneinfo   import ZoneInfo, available_timezones

# Offered as buttons; anything else can be typed.
COMMON_TIMEZONES = [
    "Europe/Kyiv", "Europe/Warsaw", "Europe/Berlin",
    "Europe/London", "America/New_York", "UTC",
]

OFFSET_RE = re.compile(r"^(?:utc|gmt)\s*([+-])\s*(\d{1,2})$")


@lru_cache(maxsize=1)
def _zones_by_key() -> dict:
    """Lookup keys -> IANA name: full name and city part, lowercased."""
    zones = {}
    for name in sorted(available_timezones()):
        if name.startswith(("Etc/", "SystemV/", "posix/", "right/")) and name != "Etc/UTC":
            continue
        zones.setdefault(name.lower(), name)
        city = name.rsplit("/", 1)[-1].replace("_", " ").lower()
        zones.setdefault(city, name)
    return zones


def resolve_timezone(text: str) -> Optional[str]:
    """Turn "Europe/Kyiv", "kyiv", "New York" or "UTC+3" into an IANA name."""
    key = " ".join(text.strip().lower().replace("_", " ").split())
    if not key:
        return None
    if key in ("utc", "gmt", "z"):
        return "UTC"

    if m := OFFSET_RE.match(key):
        hours = int(m.group(2))
        if hours == 0:
            return "UTC"
        if hours > 14:
            return None
        # POSIX-style names have the sign inverted: UTC+3 is Etc/GMT-3.
        return f"Etc/GMT{'-' if m.group(1) == '+' else '+'}{hours}"

    zones = _zones_by_key()
    return zones.get(key) or zones.get(key.replace(" ", "/"))


def to_local(when: datetime, tz_name: str) -> datetime:
    return when.astimezone(ZoneInfo(tz_name))


def format_delta(delta: timedelta) -> str:
    minutes = max(1, round(delta.total_seconds() / 60))
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    if minutes and not days:
        parts.append(f"{minutes} min")
    return " ".join(parts)


def format_when(when: datetime, tz_name: str, now: datetime) -> str:
    """"Sun 11 Oct, 09:00 (in 9 h 30 min)" in the user's timezone."""
    local = to_local(when, tz_name)
    today = to_local(now, tz_name).date()
    if local.date() == today:
        day = "Today"
    elif local.date() == today + timedelta(days=1):
        day = "Tomorrow"
    else:
        day = local.strftime("%a %d %b") + (f" {local.year}" if local.year != today.year else "")
    return f"{day}, {local:%H:%M} (in {format_delta(when - now)})"
