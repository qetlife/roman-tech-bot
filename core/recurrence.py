"""Recurring reminders: when the next occurrence is.

Stored in `core.recurrence` as one of:
    "mon,tue,wed,thu,fri@08:30"     Weekly: these weekdays at a local time
    "month:15@09:00"                Monthly: this day of the month at a local time
    "month:2tue@09:00"              MonthlyWeekday: the 2nd Tuesday of the month ("-1fri": the last Friday)
    "every:120m@2026-10-11T07:00Z"  Interval: every N minutes from a start (UTC)

Weekly and monthly times are local to the user, so a daily 09:00 reminder
stays at 09:00 across DST changes and if the user changes their timezone.
Intervals of whole days keep the local time of their start the same way.
"""

import calendar

from calendar       import Day
from dataclasses    import dataclass
from datetime       import date, datetime, time, timedelta, timezone, tzinfo
from typing         import Union


DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

EVERY_DAY = frozenset(Day)
WEEKENDS = frozenset({Day.SATURDAY, Day.SUNDAY})
WEEKDAYS = EVERY_DAY - WEEKENDS

ANCHOR_FORMAT = "%Y-%m-%dT%H:%MZ"


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def format_interval(every: timedelta) -> str:
    """"30 min", "2 h", "1 h 30 min", "3 days", "2 weeks"."""
    minutes = int(every.total_seconds() // 60)
    days, rest = divmod(minutes, 24 * 60)
    if days and not rest:
        if days % 7 == 0:
            weeks = days // 7
            return "week" if weeks == 1 else f"{weeks} weeks"
        return "day" if days == 1 else f"{days} days"
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h" if not mins else f"{hours} h {mins} min"


@dataclass(frozen=True)
class Weekly:
    days: frozenset     # calendar.Day values (Monday = 0)
    clock: time         # local time of day

    def serialize(self) -> str:
        return ",".join(DAY_NAMES[d] for d in sorted(self.days)) + f"@{self.clock:%H:%M}"

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

    def describe(self, tz: tzinfo) -> str:
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


@dataclass(frozen=True)
class Monthly:
    day: int            # 1-31; in shorter months, the last day
    clock: time

    def serialize(self) -> str:
        return f"month:{self.day}@{self.clock:%H:%M}"

    def next_after(self, after: datetime, tz: tzinfo) -> datetime:
        local = after.astimezone(tz)
        year, month = local.year, local.month
        for _ in range(3):
            day = min(self.day, calendar.monthrange(year, month)[1])
            candidate = datetime.combine(date(year, month, day), self.clock, tzinfo=tz)
            if candidate > after:
                return candidate
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        raise AssertionError("unreachable")

    def describe(self, tz: tzinfo) -> str:
        return f"monthly on the {ordinal(self.day)} at {self.clock:%H:%M}"


@dataclass(frozen=True)
class MonthlyWeekday:
    nth: int            # 1-5, or -1 for the last; months without a 5th are skipped
    weekday: int        # calendar.Day value
    clock: time

    def serialize(self) -> str:
        return f"month:{self.nth}{DAY_NAMES[self.weekday]}@{self.clock:%H:%M}"

    def day_in(self, year: int, month: int):
        """This month's date, or None if it has no such weekday (a 5th)."""
        days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1)
                if date(year, month, d).weekday() == self.weekday]
        if self.nth == -1:
            return date(year, month, days[-1])
        return date(year, month, days[self.nth - 1]) if self.nth <= len(days) else None

    def next_after(self, after: datetime, tz: tzinfo) -> datetime:
        local = after.astimezone(tz)
        year, month = local.year, local.month
        for _ in range(14):
            day = self.day_in(year, month)
            if day is not None:
                candidate = datetime.combine(day, self.clock, tzinfo=tz)
                if candidate > after:
                    return candidate
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        raise AssertionError("unreachable")

    def describe(self, tz: tzinfo) -> str:
        nth = "last" if self.nth == -1 else ordinal(self.nth)
        return f"monthly on the {nth} {DAY_NAMES[self.weekday].capitalize()} at {self.clock:%H:%M}"


@dataclass(frozen=True)
class Interval:
    every: timedelta
    anchor: datetime    # the first occurrence (aware)

    @property
    def whole_days(self) -> bool:
        return self.every % timedelta(days=1) == timedelta()

    def serialize(self) -> str:
        minutes = int(self.every.total_seconds() // 60)
        return f"every:{minutes}m@{self.anchor.astimezone(timezone.utc):{ANCHOR_FORMAT}}"

    def next_after(self, after: datetime, tz: tzinfo) -> datetime:
        if after < self.anchor:
            return self.anchor.astimezone(tz)
        steps = (after - self.anchor) // self.every
        if not self.whole_days:
            return (self.anchor + (steps + 1) * self.every).astimezone(tz)

        # Whole days: step in local dates so the clock time survives DST.
        start = self.anchor.astimezone(tz)
        step_days = self.every.days
        n = max(0, steps - 1)
        while True:
            candidate = datetime.combine(start.date() + timedelta(days=n * step_days), start.time(), tzinfo=tz)
            if candidate > after:
                return candidate
            n += 1

    def describe(self, tz: tzinfo) -> str:
        text = f"every {format_interval(self.every)}"
        if self.whole_days:
            text += f" at {self.anchor.astimezone(tz):%H:%M}"
        return text


Recurrence = Union[Weekly, Monthly, MonthlyWeekday, Interval]


def parse(value: str) -> Recurrence:
    """Read a stored recurrence (see the module docstring)."""
    rule, _, at = value.partition("@")
    if rule.startswith("every:"):
        minutes = int(rule.removeprefix("every:").removesuffix("m"))
        anchor = datetime.strptime(at, ANCHOR_FORMAT).replace(tzinfo=timezone.utc)
        return Interval(timedelta(minutes=minutes), anchor)

    hour, minute = at.split(":")
    clock = time(int(hour), int(minute))
    if rule.startswith("month:"):
        day = rule.removeprefix("month:")
        if day[-3:] in DAY_NAMES:
            return MonthlyWeekday(int(day[:-3]), Day(DAY_NAMES.index(day[-3:])), clock)
        return Monthly(int(day), clock)
    return Weekly(frozenset(Day(DAY_NAMES.index(d)) for d in rule.split(",")), clock)
