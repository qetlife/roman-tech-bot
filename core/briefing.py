"""The web app's briefing (#61): the greeting, and what's left today in a sentence or two.

Items are the web app's day items ({"kind", "time", "text"}, time "HH:MM" or
None for all day), soonest first, as handlers/webapp.days_ahead gives them.
"""

from    datetime        import datetime, timedelta

from    core.timezones  import format_delta


def greeting(now: datetime, name: str = None) -> str:
    """"Good evening, Roman" by the user's clock."""
    part = "morning" if 5 <= now.hour < 12 else "afternoon" if 12 <= now.hour < 18 else "evening"
    return f"Good {part}, {name}" if name else f"Good {part}"


def left_today(items: list, now: datetime) -> list:
    """Today's items that haven't happened yet (all-day ones too)."""
    return [i for i in items if i["time"] is None or i["time"] >= f"{now:%H:%M}"]


def _at(now: datetime, clock: str) -> datetime:
    hour, minute = map(int, clock.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def today_text(left: list, now: datetime) -> str:
    """"2 things left today. Padel is next, at 19:00, in 1 h 18 min." """
    if not left:
        return "Nothing else today."
    timed = [i for i in left if i["time"] is not None]
    count = "One thing" if len(left) == 1 else f"{len(left)} things"
    if not timed:
        return f"{count} today: {left[0]['text']}, all day." if len(left) == 1 else f"{count} today, all day."
    first = timed[0]
    soon = _at(now, first["time"]) - now
    when = "now" if soon < timedelta(minutes=1) else f"in {format_delta(soon)}"
    if len(left) == 1:
        return f"One thing left today: {first['text']} at {first['time']}, {when}."
    return f"{count} left today. {first['text']} is next, at {first['time']}, {when}."


def tomorrow_text(items: list) -> str:
    """"Tomorrow starts at 09:00 with dentist, 3 things in all." """
    if not items:
        return "Tomorrow is free."
    timed = [i for i in items if i["time"] is not None]
    if timed:
        text = f"Tomorrow starts at {timed[0]['time']} with {timed[0]['text']}"
    else:
        text = f"Tomorrow: {items[0]['text']}, all day"
    return text + (f", {len(items)} things in all." if len(items) > 1 else ".")
