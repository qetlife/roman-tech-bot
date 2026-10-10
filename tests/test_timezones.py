from datetime   import datetime, timedelta, timezone

import pytest

from reminders.timezones import format_delta, format_when, resolve_timezone


@pytest.mark.parametrize("text, expected", [
    ("Europe/Kyiv", "Europe/Kyiv"),
    ("europe/kyiv", "Europe/Kyiv"),
    ("Kyiv", "Europe/Kyiv"),
    ("new york", "America/New_York"),
    ("New_York", "America/New_York"),
    ("UTC", "UTC"),
    ("utc+3", "Etc/GMT-3"),
    ("GMT -5", "Etc/GMT+5"),
    ("utc+0", "UTC"),
    ("atlantis", None),
    ("", None),
    ("utc+20", None),
])
def test_resolve_timezone(text, expected):
    assert resolve_timezone(text) == expected


@pytest.mark.parametrize("delta, expected", [
    (timedelta(seconds=20), "1 min"),
    (timedelta(minutes=90), "1 h 30 min"),
    (timedelta(hours=2), "2 h"),
    (timedelta(days=3, hours=4, minutes=5), "3 d 4 h"),
])
def test_format_delta(delta, expected):
    assert format_delta(delta) == expected


def test_format_when():
    now = datetime(2026, 10, 10, 20, 30, tzinfo=timezone.utc)   # 23:30 in Kyiv
    assert format_when(now + timedelta(minutes=20), "Europe/Kyiv", now) == "Today, 23:50 (in 20 min)"
    assert format_when(now + timedelta(hours=9, minutes=30), "Europe/Kyiv", now) == "Tomorrow, 09:00 (in 9 h 30 min)"
    assert format_when(now + timedelta(days=6), "Europe/Kyiv", now) == "Fri 16 Oct, 23:30 (in 6 d)"
    assert format_when(now + timedelta(days=90), "Europe/Kyiv", now) == "Fri 08 Jan 2027, 22:30 (in 90 d)"
