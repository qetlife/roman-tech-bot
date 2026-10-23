"""Google Calendar events ↔ the bot's events: reading Google's JSON, writing ours.

No Telegram, no database, no HTTP (services/google_calendar.py talks to
Google, handlers/calendar.py syncs). Times come back aware.
"""

from dataclasses    import dataclass, field
from datetime       import date, datetime, time, timedelta
from typing         import Optional
from zoneinfo       import ZoneInfo, ZoneInfoNotFoundError

from core.events    import duration, rrule, skipped


@dataclass
class GoogleEvent:
    id: str
    cancelled: bool
    title: str = ""
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    all_day: bool = False
    timezone: str = "UTC"
    rule: Optional[str] = None                      # the RRULE, without "RRULE:"
    exdates: frozenset = field(default_factory=frozenset)
    # Extra occurrences (RDATE), and for an exception: which repeating event and which of its occurrences
    rdates: frozenset = field(default_factory=frozenset)
    recurring_event_id: Optional[str] = None
    original_start: Optional[datetime] = None
    updated: Optional[datetime] = None
    etag: Optional[str] = None


def _zone(name: Optional[str], fallback: str) -> str:
    for candidate in (name, fallback):
        if candidate:
            try:
                ZoneInfo(candidate)
                return candidate
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return "UTC"


def _when(value: Optional[dict], tz_name: str) -> tuple:
    """Google's {"dateTime"} or {"date"} → (aware datetime or None, all day)."""
    if not value:
        return None, False
    if "date" in value:
        day = date.fromisoformat(value["date"])
        return datetime.combine(day, time(0, 0), tzinfo=ZoneInfo(tz_name)), True
    when = datetime.fromisoformat(value["dateTime"])
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(tz_name))
    return when, False


def _dates(line: str, tz_name: str) -> set:
    """The dates of an "EXDATE;TZID=Europe/Lisbon:20261029T210000,…" / "EXDATE;VALUE=DATE:20261029" line."""
    head, _, values = line.partition(":")
    params = dict(p.partition("=")[::2] for p in head.split(";")[1:])
    tz = ZoneInfo(_zone(params.get("TZID"), tz_name))
    found = set()
    for value in values.split(","):
        value = value.strip()
        if not value:
            continue
        if "T" not in value:
            found.add(datetime.combine(datetime.strptime(value, "%Y%m%d").date(), time(0, 0), tzinfo=tz))
        elif value.endswith("Z"):
            found.add(datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC")))
        else:
            found.add(datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz))
    return found


def from_google(item: dict, calendar_tz: Optional[str]) -> GoogleEvent:
    """One item of events.list. A cancelled one may have little more than its id."""
    tz_name = _zone((item.get("start") or {}).get("timeZone"), calendar_tz or "UTC")
    starts_at, all_day = _when(item.get("start"), tz_name)
    ends_at, _ = _when(item.get("end"), tz_name)
    rule, exdates, rdates = None, set(), set()
    for line in item.get("recurrence") or []:
        name = line.split(":", 1)[0].split(";", 1)[0].upper()
        if name == "RRULE":
            rule = line.split(":", 1)[1]
        elif name == "EXDATE":
            exdates |= _dates(line, tz_name)
        elif name == "RDATE":
            rdates |= _dates(line, tz_name)
    original, _ = _when(item.get("originalStartTime"), tz_name)
    updated = datetime.fromisoformat(item["updated"]) if item.get("updated") else None
    return GoogleEvent(
        id=item["id"], cancelled=item.get("status") == "cancelled", title=(item.get("summary") or "").strip()
        or "(no title)", starts_at=starts_at, ends_at=ends_at, all_day=all_day, timezone=tz_name, rule=rule,
        exdates=frozenset(exdates), rdates=frozenset(rdates), recurring_event_id=item.get("recurringEventId"),
        original_start=original, updated=updated, etag=item.get("etag"),
    )


def _time(when: datetime, tz_name: str, all_day: bool) -> dict:
    local = when.astimezone(ZoneInfo(tz_name))
    if all_day:
        return {"date": local.date().isoformat()}
    return {"dateTime": local.isoformat(), "timeZone": tz_name}


def to_google(event) -> dict:
    """The body for events.insert / events.patch.

    Without an end, a timed event lasts an hour in Google (its default) and
    an all-day one its day; the bot keeps showing it without an end. The
    days skipped in the bot go as EXDATEs; occurrences moved in Google are
    Google's own exceptions and aren't sent back.
    """
    tz_name = event.timezone
    end = event.ends_at or event.starts_at + (duration(event) if event.all_day else timedelta(hours=1))
    body = {
        "summary": event.title,
        "start": _time(event.starts_at, tz_name, event.all_day),
        "end": _time(end, tz_name, event.all_day),
    }
    rule = rrule(event)
    lines = []
    if rule is not None:
        lines.append(f"RRULE:{rule}")
        tz = ZoneInfo(tz_name)
        stamps = sorted(s.astimezone(tz) for s in skipped(event))
        if stamps and event.all_day:
            lines.append("EXDATE;VALUE=DATE:" + ",".join(f"{s:%Y%m%d}" for s in stamps))
        elif stamps:
            lines.append(f"EXDATE;TZID={tz_name}:" + ",".join(f"{s:%Y%m%dT%H%M%S}" for s in stamps))
    body["recurrence"] = lines
    return body


def stored_rule(rule: Optional[str]) -> Optional[str]:
    """An RRULE as events.recurrence keeps it."""
    return rule.removeprefix("RRULE:") if rule else None

