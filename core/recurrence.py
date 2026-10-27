"""Recurring reminders: when the next occurrence is.

Stored in `core.recurrence` as one of:
    "mon,tue,wed,thu,fri@08:30"     Weekly: these weekdays at a local time
    "month:15@09:00"                Monthly: this day of the month at a local time
    "month:2tue@09:00"              MonthlyWeekday: the 2nd Tuesday of the month ("-1fri": the last Friday)
    "every:120m@2026-10-11T07:00Z"  Interval: every N minutes from a start (UTC)
    "event:-30m;Europe/Lisbon;20261029T2100Z;thu@21:00"
                                    Offset: 30 min before every occurrence of a repeating
                                    event (its repeat and timezone), except those skipped
    "rrule:Europe/Lisbon;20261022T210000;<exdates>;<rdates>;FREQ=WEEKLY;BYDAY=TH"
                                    RRuleSet: an event's repeat as an RFC 5545 RRULE (what
                                    Google Calendar uses), from its first occurrence (local),
                                    minus EXDATEs, plus RDATEs (stamps, comma-separated)

Events store their repeat as an RRULE (`to_rrule` converts the others); an
Offset's base is then an RRuleSet. An RRuleSet can end (UNTIL, COUNT), so
its next_after, and an Offset's, can be None.

Weekly and monthly times are local to the user, so a daily 09:00 reminder
stays at 09:00 across DST changes and if the user changes their timezone.
Intervals of whole days keep the local time of their start the same way.
"""

import calendar
import re

from calendar       import Day
from dataclasses    import dataclass
from datetime       import date, datetime, time, timedelta, timezone, tzinfo
from functools      import lru_cache
from typing         import Optional, Union
from zoneinfo       import ZoneInfo

from dateutil.rrule import rrulestr, rruleset


DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

EVERY_DAY = frozenset(Day)
WEEKENDS = frozenset({Day.SATURDAY, Day.SUNDAY})
WEEKDAYS = EVERY_DAY - WEEKENDS

ANCHOR_FORMAT = "%Y-%m-%dT%H:%MZ"
# A skipped occurrence of an event, in UTC (events.skipped, Offset)
STAMP_FORMAT = "%Y%m%dT%H%MZ"


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


def format_stamp(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime(STAMP_FORMAT)


def parse_stamp(value: str) -> datetime:
    return datetime.strptime(value, STAMP_FORMAT).replace(tzinfo=timezone.utc)


def format_offset(minutes: int) -> str:
    """"30 min before", "1 h after", "at the start"."""
    if minutes == 0:
        return "at the start"
    return f"{format_interval(timedelta(minutes=abs(minutes)))} {'before' if minutes < 0 else 'after'}"


@dataclass(frozen=True)
class Offset:
    """A reminder some minutes before (negative) or after every occurrence of a repeating event.

    `base` is the event's repeat, in the event's own timezone (`tz_name`,
    not whoever asks); occurrences in `skipped` (aware) don't happen.
    """

    base: "Recurrence"
    minutes: int
    tz_name: str
    skipped: frozenset = frozenset()

    def serialize(self) -> str:
        skips = ",".join(sorted(format_stamp(s) for s in self.skipped))
        return f"event:{self.minutes}m;{self.tz_name};{skips};{self.base.serialize()}"

    def occurrence_after(self, after: datetime) -> Optional[datetime]:
        """The event's first occurrence strictly after `after` that isn't skipped; None once it has ended."""
        tz = ZoneInfo(self.tz_name)
        occurrence = self.base.next_after(after, tz)
        while occurrence is not None and occurrence in self.skipped:
            occurrence = self.base.next_after(occurrence, tz)
        return occurrence

    def next_after(self, after: datetime, tz: tzinfo) -> Optional[datetime]:
        delta = timedelta(minutes=self.minutes)
        occurrence = self.occurrence_after(after - delta)
        return (occurrence + delta).astimezone(tz) if occurrence is not None else None

    def describe(self, tz: tzinfo) -> str:
        """"30 min before, every Thu at 21:00" (the event's clock)."""
        return f"{format_offset(self.minutes)}, {self.base.describe(ZoneInfo(self.tz_name))}"


# --- RFC 5545 -----------------------------------------------------------------

RRULE_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
LOCAL_FORMAT = "%Y%m%dT%H%M%S"


def is_rrule(value: str) -> bool:
    """Whether a stored repeat is an RRULE ("FREQ=WEEKLY;BYDAY=TH"), not one of the formats above."""
    return value.upper().startswith(("FREQ=", "RRULE:"))


def to_rrule(recurrence) -> str:
    """The RRULE of one of the bot's own repeats, for an event that starts at its first occurrence.

    The time of day comes from the event's start (DTSTART). "the 31st"
    (the last day in shorter months) is the last of the 28th–31st that the
    month has.
    """
    if isinstance(recurrence, Weekly):
        if recurrence.days == EVERY_DAY:
            return "FREQ=DAILY"
        return "FREQ=WEEKLY;BYDAY=" + ",".join(RRULE_DAYS[d] for d in sorted(recurrence.days))
    if isinstance(recurrence, Monthly):
        if recurrence.day <= 28:
            return f"FREQ=MONTHLY;BYMONTHDAY={recurrence.day}"
        days = ",".join(str(d) for d in range(28, recurrence.day + 1))
        return f"FREQ=MONTHLY;BYMONTHDAY={days};BYSETPOS=-1"
    if isinstance(recurrence, MonthlyWeekday):
        return f"FREQ=MONTHLY;BYDAY={recurrence.nth}{RRULE_DAYS[recurrence.weekday]}"
    if isinstance(recurrence, Interval):
        minutes = int(recurrence.every.total_seconds() // 60)
        for unit, freq in ((7 * 24 * 60, "WEEKLY"), (24 * 60, "DAILY"), (60, "HOURLY"), (1, "MINUTELY")):
            if minutes % unit == 0:
                n = minutes // unit
                return f"FREQ={freq}" + (f";INTERVAL={n}" if n != 1 else "")
    if isinstance(recurrence, RRuleSet):
        return recurrence.rule
    raise ValueError(f"No RRULE for {recurrence!r}")


def rule_parts(rule: str) -> dict:
    """"FREQ=WEEKLY;BYDAY=TH" → {"FREQ": "WEEKLY", "BYDAY": "TH"}."""
    rule = rule.removeprefix("RRULE:")
    return {k.upper(): v for k, _, v in (part.partition("=") for part in rule.split(";") if part)}


def format_rule(parts: dict) -> str:
    """rule_parts back to an RRULE, FREQ first."""
    ordered = sorted(parts.items(), key=lambda kv: kv[0] != "FREQ")
    return ";".join(f"{k}={v}" for k, v in ordered)


def _utc_until(rule: str, start: datetime) -> str:
    """UNTIL in UTC, as dateutil needs with a timezone-aware DTSTART.

    Google sends a date ("UNTIL=20261224") for all-day events and sometimes
    a local time: both mean the end of that day / that time in `start`'s zone.
    """
    def fix(m):
        value = m.group(1)
        if value.endswith("Z"):
            return m.group(0)
        if "T" in value:
            local = datetime.strptime(value, LOCAL_FORMAT).replace(tzinfo=start.tzinfo)
        else:
            local = datetime.combine(datetime.strptime(value, "%Y%m%d").date(), time(23, 59, 59), tzinfo=start.tzinfo)
        return f"UNTIL={local.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"
    return re.sub(r"UNTIL=([0-9TZ]+)", fix, rule, flags=re.IGNORECASE)


@lru_cache(maxsize=512)
def _expand(rule: str, start: datetime, exdates: frozenset, rdates: frozenset) -> rruleset:
    occurrences = rruleset()
    occurrences.rrule(rrulestr(_utc_until(rule.removeprefix("RRULE:"), start), dtstart=start))
    for when in exdates:
        occurrences.exdate(when.astimezone(start.tzinfo))
    for when in rdates:
        occurrences.rdate(when.astimezone(start.tzinfo))
    return occurrences


def _describe_days(days: list) -> str:
    named = frozenset(Day(RRULE_DAYS.index(d)) for d in days)
    return Weekly(named, time(0, 0)).describe(timezone.utc).removesuffix(" at 00:00")


def describe_rule(rule: str, start: datetime) -> str:
    """"every Thu at 21:00", "every 2 weeks on Mon, Thu at 08:30", "monthly on the 2nd Tue at 19:00, until 24 Dec"."""
    parts = rule_parts(rule)
    freq, n = parts.get("FREQ", "").upper(), int(parts.get("INTERVAL", "1"))
    byday = [d for d in parts.get("BYDAY", "").upper().split(",") if d]
    plain_days = [d for d in byday if d in RRULE_DAYS]
    if freq == "DAILY":
        text = "every day" if n == 1 else f"every {n} days"
    elif freq == "WEEKLY":
        days = plain_days or [RRULE_DAYS[start.weekday()]]
        text = _describe_days(days) if n == 1 else f"every {n} weeks on {_describe_days(days).removeprefix('every ')}"
    elif freq == "MONTHLY":
        every = "monthly" if n == 1 else f"every {n} months"
        monthdays = [int(d) for d in parts.get("BYMONTHDAY", "").split(",") if d]
        if byday and not plain_days:
            m = re.fullmatch(r"([+-]?\d+)([A-Z]{2})", byday[0])
            nth = int(m.group(1))
            day = DAY_NAMES[RRULE_DAYS.index(m.group(2))].capitalize()
            text = f"{every} on the {'last' if nth == -1 else ordinal(nth)} {day}"
        elif monthdays:
            day = max(monthdays) if parts.get("BYSETPOS") == "-1" else monthdays[0]
            text = f"{every} on the {'last day' if day == -1 else ordinal(day)}"
        else:
            text = f"{every} on the {ordinal(start.day)}"
    elif freq == "YEARLY":
        text = "every year" if n == 1 else f"every {n} years"
        text += f" on {start:%d %b}"
    elif freq in ("HOURLY", "MINUTELY"):
        text = f"every {format_interval(timedelta(minutes=n * (60 if freq == 'HOURLY' else 1)))}"
        return text
    else:
        text = "repeats"
    text += f" at {start:%H:%M}"
    if "UNTIL" in parts:
        until = _utc_until(f"UNTIL={parts['UNTIL']}", start).removeprefix("UNTIL=")
        text += f", until {datetime.strptime(until, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).astimezone(start.tzinfo):%d %b %Y}"
    elif "COUNT" in parts:
        text += f", {parts['COUNT']} times"
    return text


@dataclass(frozen=True)
class RRuleSet:
    """An event's repeat as an RFC 5545 RRULE, from its first occurrence `start` (aware, in `tz_name`).

    Occurrences in `exdates` don't happen; those in `rdates` do too (a single
    occurrence moved in Google Calendar). It can end (UNTIL, COUNT).
    """

    rule: str
    start: datetime
    tz_name: str
    exdates: frozenset = frozenset()
    rdates: frozenset = frozenset()

    def _local_start(self) -> datetime:
        return self.start.astimezone(ZoneInfo(self.tz_name))

    def serialize(self) -> str:
        stamps = [",".join(sorted(format_stamp(s) for s in dates)) for dates in (self.exdates, self.rdates)]
        return f"rrule:{self.tz_name};{self._local_start():{LOCAL_FORMAT}};{stamps[0]};{stamps[1]};{self.rule}"

    def next_after(self, after: datetime, tz: tzinfo) -> Optional[datetime]:
        """The first occurrence strictly after `after` (in `tz`), None once it has ended."""
        start = self._local_start()
        occurrence = _expand(self.rule, start, self.exdates, self.rdates).after(after.astimezone(start.tzinfo))
        return occurrence.astimezone(tz) if occurrence is not None else None

    def describe(self, tz: tzinfo) -> str:
        return describe_rule(self.rule, self._local_start())


Recurrence = Union[Weekly, Monthly, MonthlyWeekday, Interval, Offset, RRuleSet]


def parse(value: str) -> Recurrence:
    """Read a stored recurrence (see the module docstring)."""
    if value.startswith("rrule:"):
        tz_name, start, exdates, rdates, rule = value.removeprefix("rrule:").split(";", 4)
        local = datetime.strptime(start, LOCAL_FORMAT).replace(tzinfo=ZoneInfo(tz_name))
        return RRuleSet(rule, local, tz_name, frozenset(parse_stamp(s) for s in exdates.split(",") if s),
                        frozenset(parse_stamp(s) for s in rdates.split(",") if s))
    if value.startswith("event:"):
        minutes, tz_name, skips, base = value.removeprefix("event:").split(";", 3)
        skipped = frozenset(parse_stamp(s) for s in skips.split(",") if s)
        return Offset(parse(base), int(minutes.removesuffix("m")), tz_name, skipped)
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
