"""Spoken numbers (voice transcriptions) → what the parser reads."""

from datetime   import datetime, time
from zoneinfo   import ZoneInfo

import pytest

from core.numbers import normalize_numbers
from core.parser  import parse_recurrence, parse_reminder, parse_when

TZ = ZoneInfo("Europe/Kyiv")
# Saturday 10 Oct 2026, 14:00
AFTERNOON = datetime(2026, 10, 10, 14, 0, tzinfo=TZ)


def dt(day, hour, minute=0, month=10):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


@pytest.mark.parametrize("words, expected", [
    ("in twenty five minutes",      "in 25 minutes"),
    ("in twenty-five minutes",      "in 25 minutes"),
    ("in two hours",                "in 2 hours"),
    ("at nine",                     "at 9"),
    ("at nine thirty",              "at 9:30~"),
    ("at nine oh five",             "at 9:05~"),
    ("at nine o'clock",             "at 9"),
    ("at half past six",            "at 6:30~"),
    ("at a quarter past nine",      "at 9:15~"),
    ("at quarter to five",          "at 4:45~"),
    ("at quarter to one",           "at 12:45"),
    ("at ten to five",              "at 4:50~"),
    ("at twenty past six",          "at 6:20~"),
    ("at nine p m",                 "at 9 pm"),
    ("at nine thirty p m",          "at 9:30 pm"),
    ("at twelve thirty",            "at 12:30"),
    ("on the fifteenth",            "on the 15th"),
    ("on the first of may",         "on the 1st of may"),
    ("december twenty fourth",      "december 24th"),
    ("every fifth",                 "every 5th"),
    # left alone: not a day of the month, or not a time
    ("in a second",                 "in a second"),
    ("first thing",                 "first thing"),
    ("in 2 30 minutes",             "in 2 30 minutes"),
    ("half an hour",                "half an hour"),
])
def test_normalize_numbers(words, expected):
    assert " ".join(normalize_numbers(words.split())) == expected


@pytest.mark.parametrize("phrase, expected", [
    ("in twenty five minutes",          dt(10, 14, 25)),
    ("at nine",                         dt(10, 21)),          # the next 9 o'clock
    ("at nine thirty",                  dt(10, 21, 30)),      # spoken: the next 9:30
    ("at 9:30",                         dt(11, 9, 30)),       # typed: as written
    ("at nine thirty a m",              dt(11, 9, 30)),
    ("at half past six",                dt(10, 18, 30)),
    ("at a quarter to five",            dt(10, 16, 45)),
    ("at nine oh five tonight",         dt(10, 21, 5)),
    ("tomorrow at nine in the morning", dt(11, 9)),
    ("at seven in the evening",         dt(10, 19)),
    ("tomorrow in the evening",         dt(11, 19)),
    ("tonight",                         dt(10, 20)),
    ("tonight at nine",                 dt(10, 21)),
    ("at nine tonight",                 dt(10, 21)),
    ("on the fifteenth",                dt(15, 9)),
    ("on the 15th at 10",               dt(15, 10)),
    ("on the tenth",                    dt(10, 9, month=11)),  # today's 09:00 has passed
    ("on the 10th at 15:00",            dt(10, 15)),
    ("on december twenty fourth at ten", datetime(2026, 12, 24, 10, tzinfo=TZ)),
])
def test_spoken_times(phrase, expected):
    assert parse_when(phrase, AFTERNOON) == expected


def test_the_31st_skips_short_months():
    # 1 Nov: the next 31st is in December
    assert parse_when("on the 31st", datetime(2026, 11, 1, 8, tzinfo=TZ)) == datetime(2026, 12, 31, 9, tzinfo=TZ)


@pytest.mark.parametrize("request_, when, text", [
    ("tomorrow at nine thirty to call mom",       dt(11, 9, 30),  "call mom"),
    ("to buy two eggs in twenty minutes",         dt(10, 14, 20), "buy two eggs"),   # text keeps its words
    ("at seven in the evening to walk the dog",   dt(10, 19),     "walk the dog"),
    ("to call mom tonight at nine",               dt(10, 21),     "call mom"),
])
def test_spoken_reminders(request_, when, text):
    parsed = parse_reminder(request_, AFTERNOON)
    assert (parsed.when, parsed.text) == (when, text)


@pytest.mark.parametrize("phrase, clock", [
    ("every day at eight",              time(8)),
    ("every day at nine thirty",        time(9, 30)),
    ("every monday at half past six",   time(6, 30)),
])
def test_spoken_repeats(phrase, clock):
    _, recurrence = parse_recurrence(phrase, AFTERNOON)
    assert recurrence.clock == clock


def test_spoken_interval_and_monthly():
    _, every = parse_recurrence("every two hours", AFTERNOON)
    assert every.every.total_seconds() == 7200
    _, monthly = parse_recurrence("on the first of every month", AFTERNOON)
    assert monthly.day == 1


# --- settings answers by voice -------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("twenty three to seven",               ["23:00", "07:00"]),
    ("eleven pm to seven",                  ["23:00", "07:00"]),
    ("eleven thirty p m to six thirty",     ["23:30", "06:30"]),
    ("ten to five",                         ["10:00", "05:00"]),   # a range, not 4:50
])
def test_spoken_quiet_hours(text, expected):
    from core.settings import parse_quiet_hours

    assert parse_quiet_hours(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("ten minutes and one hour",    [10, 60]),
    ("five fifteen sixty",          [5, 15, 60]),                  # minutes, not 5:15
    ("five, fifteen, sixty",        [5, 15, 60]),
])
def test_spoken_snooze_options(text, expected):
    from core.settings import parse_snooze_options

    assert parse_snooze_options(text) == expected
