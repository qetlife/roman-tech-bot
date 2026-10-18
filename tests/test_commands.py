"""Plain-language commands (core/commands.py)."""

from datetime   import date, datetime, timedelta
from zoneinfo   import ZoneInfo

import pytest

from core.commands import matches, occurs_on, parse_day, search_words

TZ = ZoneInfo("Europe/Lisbon")
# Sunday 18 Oct 2026, 14:00
NOW = datetime(2026, 10, 18, 14, 0, tzinfo=TZ)


@pytest.mark.parametrize("request_, words", [
    ("the dentist reminder",    ["dentist"]),
    ("my reminder to call mom", ["call", "mom"]),
    ("reminder about the gym",  ["gym"]),
    ("reminders",               []),
    ("",                        []),
])
def test_search_words(request_, words):
    assert search_words(request_) == words


@pytest.mark.parametrize("text, words, expected", [
    ("Dentist at 5",    ["dentist"],        True),
    ("call mom",        ["call", "mo"],     True),      # the start of a word is enough
    ("call dad",        ["mom"],            False),
    ("go to the gym",   ["gym", "go"],      True),
    ("gymnastics",      ["gym"],            True),
])
def test_matches(text, words, expected):
    assert matches(text, words) is expected


@pytest.mark.parametrize("request_, expected", [
    ("tomorrow?",       date(2026, 10, 19)),
    ("on friday",       date(2026, 10, 23)),
    ("for dec 24",      date(2026, 12, 24)),
    ("today",           date(2026, 10, 18)),
    ("this week",       None),
    ("my mind",         None),
    ("",                None),
])
def test_parse_day(request_, expected):
    assert parse_day(request_, NOW) == expected


def test_occurs_on():
    monday_9 = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    daily, mondays = "mon,tue,wed,thu,fri,sat,sun@09:00", "mon@09:00"
    assert occurs_on(monday_9, None, monday_9.date(), TZ)
    assert not occurs_on(monday_9, None, monday_9.date() + timedelta(days=1), TZ)
    assert occurs_on(monday_9, daily, monday_9.date() + timedelta(days=3), TZ)
    assert not occurs_on(monday_9, mondays, monday_9.date() + timedelta(days=3), TZ)
    assert occurs_on(monday_9, mondays, monday_9.date() + timedelta(days=7), TZ)
    # Not before it starts
    assert not occurs_on(monday_9, daily, monday_9.date() - timedelta(days=1), TZ)
