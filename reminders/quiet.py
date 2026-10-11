"""Quiet hours: a nightly window without interval reminders or repeats.

Reminders set for a specific time still fire in it; what waits is
"every 2 hours"-style occurrences (skipped) and re-sends of an unanswered
reminder (paused until the window ends).
"""

from datetime   import datetime, time, timedelta, tzinfo
from typing     import Optional, Tuple

from reminders.recurrence import Interval


QuietHours = Optional[Tuple[time, time]]   # (start, end), local; None = off

# Guards against an interval that never leaves the window.
MAX_SKIPS = 1000


def is_quiet(when: datetime, quiet: QuietHours, tz: tzinfo) -> bool:
    if quiet is None:
        return False
    start, end = quiet
    t = when.astimezone(tz).time()
    if start < end:
        return start <= t < end
    # Wraps midnight, e.g. 23:00-07:00
    return t >= start or t < end


def quiet_end(when: datetime, quiet: QuietHours, tz: tzinfo) -> datetime:
    """When the quiet window that `when` falls in ends."""
    local = when.astimezone(tz)
    end = datetime.combine(local.date(), quiet[1], tzinfo=tz)
    return end if end > local else end + timedelta(days=1)


def skip_quiet(recurrence, when: datetime, quiet: QuietHours, tz: tzinfo) -> datetime:
    """Move an interval occurrence ("every 2 hours") past quiet hours.

    Other recurrences and whole-day intervals have an explicit time and
    are returned unchanged.
    """
    if not isinstance(recurrence, Interval) or recurrence.whole_days:
        return when
    for _ in range(MAX_SKIPS):
        if not is_quiet(when, quiet, tz):
            break
        when = recurrence.next_after(when, tz)
    return when
