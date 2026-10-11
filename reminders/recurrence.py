"""Recurring reminders: which weekdays, and at what local time.

Stored in `reminders.recurrence` as e.g. "mon,tue,wed,thu,fri@08:30". The
time is local to the user, so a daily 09:00 reminder stays at 09:00 across
DST changes and if the user changes their timezone.
"""

from dataclasses    import dataclass
from datetime       import datetime, time, timedelta, tzinfo


DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

EVERY_DAY = frozenset(range(7))
WEEKDAYS = frozenset(range(5))
WEEKENDS = frozenset({5, 6})


@dataclass(frozen=True)
class Recurrence:
    days: frozenset     # weekday numbers, Monday = 0
    clock: time         # local time of day

    def serialize(self) -> str:
        return ",".join(DAY_NAMES[d] for d in sorted(self.days)) + f"@{self.clock:%H:%M}"

    @classmethod
    def parse(cls, value: str) -> "Recurrence":
        days, _, clock = value.partition("@")
        hour, minute = clock.split(":")
        return cls(frozenset(DAY_NAMES.index(d) for d in days.split(",")), time(int(hour), int(minute)))

    def next_after(self, after: datetime, tz: tzinfo) -> datetime:
        """The first occurrence strictly after `after`, in the user's timezone."""
        local = after.astimezone(tz)
        for n in range(8):
            day = local.date() + timedelta(days=n)
            if day.weekday() in self.days:
                candidate = datetime.combine(day, self.clock, tzinfo=tz)
                if candidate > after:
                    return candidate
        raise ValueError(f"Recurrence without days: {self.serialize()}")

    def describe(self) -> str:
        """"every day at 09:00", "weekdays at 08:30", "every Mon, Thu at 18:00"."""
        if self.days == EVERY_DAY:
            days = "every day"
        elif self.days == WEEKDAYS:
            days = "weekdays"
        elif self.days == WEEKENDS:
            days = "weekends"
        else:
            days = "every " + ", ".join(DAY_NAMES[d].capitalize() for d in sorted(self.days))
        return f"{days} at {self.clock:%H:%M}"
