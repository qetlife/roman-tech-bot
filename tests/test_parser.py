from datetime   import datetime
from zoneinfo   import ZoneInfo

import pytest

from core.parser import ParseError, parse_reminder, parse_when

TZ = ZoneInfo("Europe/Kyiv")
# Saturday 10 Oct 2026, 23:30
NOW = datetime(2026, 10, 10, 23, 30, tzinfo=TZ)
# Saturday 10 Oct 2026, 14:00
AFTERNOON = datetime(2026, 10, 10, 14, 0, tzinfo=TZ)
# Saturday 10 Oct 2026, 01:30 and 04:00
LATE_NIGHT = datetime(2026, 10, 10, 1, 30, tzinfo=TZ)
EARLY_MORNING = datetime(2026, 10, 10, 4, 0, tzinfo=TZ)


def dt(day, hour, minute=0, month=10, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


@pytest.mark.parametrize("phrase, now, expected", [
    ("in two hours",              NOW, dt(11, 1, 30)),
    ("in 2 hours",                NOW, dt(11, 1, 30)),
    ("in 30 minutes",             NOW, dt(11, 0, 0)),
    ("in 30 min",                 NOW, dt(11, 0, 0)),
    ("in 1.5 hours",              NOW, dt(11, 1, 0)),
    ("in 1h30m",                  NOW, dt(11, 1, 0)),
    ("in 1 hour and 15 minutes",  NOW, dt(11, 0, 45)),
    ("in half an hour",           NOW, dt(11, 0, 0)),
    ("in an hour and a half",     NOW, dt(11, 1, 0)),
    ("in a couple of hours",      NOW, dt(11, 1, 30)),
    ("in 3 days",                 NOW, dt(13, 23, 30)),
    ("in a week",                 NOW, dt(17, 23, 30)),
    ("tomorrow",                  NOW, dt(11, 9)),
    ("tomorrow at 9",             NOW, dt(11, 9)),
    ("tomorrow 9am",              NOW, dt(11, 9)),
    ("tomorrow at 9:30 pm",       NOW, dt(11, 21, 30)),
    ("at 9 tomorrow",             NOW, dt(11, 9)),
    ("tomorrow morning",          NOW, dt(11, 9)),
    ("tomorrow in the evening",   NOW, dt(11, 19)),
    ("day after tomorrow",        NOW, dt(12, 9)),
    ("at 9",                      NOW, dt(11, 9)),
    ("at 9",                      AFTERNOON, dt(10, 21)),
    ("at 18:00",                  NOW, dt(11, 18)),
    ("18:00",                     AFTERNOON, dt(10, 18)),
    ("at 09:00",                  AFTERNOON, dt(11, 9)),
    ("at noon",                   NOW, dt(11, 12)),
    ("tonight",                   AFTERNOON, dt(10, 20)),
    ("today at 5",                AFTERNOON, dt(10, 17)),
    ("friday 18:00",              NOW, dt(16, 18)),
    ("on friday",                 NOW, dt(16, 9)),
    ("next monday",               NOW, dt(12, 9)),
    ("saturday at 10",            AFTERNOON, dt(17, 10)),
    ("next week",                 NOW, dt(17, 9)),
    ("24.12",                     NOW, dt(24, 9, month=12)),
    ("24/12 10:00",               NOW, dt(24, 10, month=12)),
    ("2027-01-05 at 8am",         NOW, datetime(2027, 1, 5, 8, tzinfo=TZ)),
    ("dec 24",                    NOW, dt(24, 9, month=12)),
    ("on december 24th at 10am",  NOW, dt(24, 10, month=12)),
    ("24th of december",          NOW, dt(24, 9, month=12)),
    ("jan 3",                     NOW, datetime(2027, 1, 3, 9, tzinfo=TZ)),
    # A dot works like a colon in times; "10.11" on its own stays a date
    ("thursday at 21.20",         NOW, dt(15, 21, 20)),
    ("on thursday at 21.20",      NOW, dt(15, 21, 20)),
    ("at 21.20",                  AFTERNOON, dt(10, 21, 20)),
    ("21.20",                     AFTERNOON, dt(10, 21, 20)),
    ("at 21.20 tomorrow",         NOW, dt(11, 21, 20)),
    ("tomorrow at 7.05",          NOW, dt(11, 7, 5)),
    ("at 9.20pm",                 AFTERNOON, dt(10, 21, 20)),
    ("at 9.20 pm",                AFTERNOON, dt(10, 21, 20)),
    ("at 10.11",                  NOW, dt(11, 10, 11)),
    ("10.11",                     NOW, dt(10, 9, month=11)),
    ("at 24.12",                  NOW, dt(24, 9, month=12)),
    # Shortly after midnight "tomorrow" is the coming day
    ("tomorrow",                  LATE_NIGHT, dt(10, 9)),
    ("tomorrow at 9",             LATE_NIGHT, dt(10, 9)),
    ("tomorrow evening",          LATE_NIGHT, dt(10, 19)),
    ("day after tomorrow",        LATE_NIGHT, dt(11, 9)),
    ("today at 9",                LATE_NIGHT, dt(10, 9)),
    ("in 2 hours",                LATE_NIGHT, dt(10, 3, 30)),
    ("tomorrow at 9",             EARLY_MORNING, dt(11, 9)),
])
def test_parse_when(phrase, now, expected):
    assert parse_when(phrase, now) == expected


@pytest.mark.parametrize("phrase", [
    "call mom", "pay rent", "9", "may", "in", "at", "someday", "in two", "31.02",
    "tomorrow tomorrow", "in 2 hours tomorrow", "25.70",
])
def test_parse_when_rejects(phrase):
    assert parse_when(phrase, NOW) is None


@pytest.mark.parametrize("request_, expected_when, expected_text", [
    ("in two hours to call mom",              dt(11, 1, 30), "call mom"),
    ("to call mom in two hours",              dt(11, 1, 30), "call mom"),
    ("tomorrow at 9 to pay rent",             dt(11, 9),     "pay rent"),
    ("to pay rent tomorrow at 9",             dt(11, 9),     "pay rent"),
    ("call mom tomorrow",                     dt(11, 9),     "call mom"),
    ("for friday 18:00: dentist",             dt(16, 18),    "dentist"),
    ("buy 2 eggs tomorrow",                   dt(11, 9),     "buy 2 eggs"),
    ("that the Laundry is done in 45 min",    dt(11, 0, 15), "the Laundry is done"),
    ("about the meeting at 10 am tomorrow",   dt(11, 10),    "the meeting"),
    ("in 1 hour - take pills",                dt(11, 0, 30), "take pills"),
    ("on thursday at 21.20 to call mom",      dt(15, 21, 20), "call mom"),
])
def test_parse_reminder(request_, expected_when, expected_text):
    parsed = parse_reminder(request_, NOW)
    assert parsed.when == expected_when
    assert parsed.text == expected_text


@pytest.mark.parametrize("request_, message", [
    ("",                      "What should I remind you about"),
    ("tomorrow at 9",         "What should I remind you about?"),
    ("to call mom",           "couldn't understand when"),
    ("to call mom someday",   "couldn't understand when"),
])
def test_parse_reminder_errors(request_, message):
    with pytest.raises(ParseError, match=message):
        parse_reminder(request_, NOW)


@pytest.mark.parametrize("request_, expected_when, expected_text", [
    ("in a fortnight to pay",                 dt(24, 23, 30), "pay"),
    ("in 2 fortnights to renew",              dt(7, 23, 30, month=11), "renew"),
    ("next month to renew",                   dt(10, 9, month=11), "renew"),
    ("next month at 10 to renew",             dt(10, 10, month=11), "renew"),
    ("end of the month to pay rent",          dt(31, 9), "pay rent"),
    ("by end of month: report",               dt(31, 9), "report"),
])
def test_more_time_phrases(request_, expected_when, expected_text):
    parsed = parse_reminder(request_, NOW)
    assert (parsed.when, parsed.text) == (expected_when, expected_text)


def test_next_month_on_the_31st_is_its_last_day():
    jan31 = datetime(2027, 1, 31, 12, 0, tzinfo=TZ)
    assert parse_reminder("next month to pay", jan31).when == datetime(2027, 2, 28, 9, 0, tzinfo=TZ)


def test_end_of_the_month_after_it_is_next_months():
    late = datetime(2026, 10, 31, 12, 0, tzinfo=TZ)
    assert parse_reminder("end of the month to pay", late).when == datetime(2026, 11, 30, 9, 0, tzinfo=TZ)


def test_past_time_rejected():
    with pytest.raises(ParseError, match="already passed"):
        parse_reminder("today at 9:00 to call mom", AFTERNOON)


@pytest.mark.parametrize("request_text", [
    "to borrow at nine twenty am too start the oven",
    "to borrow at nine twenty am to start the oven",
])
def test_misheard_tomorrow(request_text):
    r = parse_reminder(request_text, NOW)
    assert r.when == datetime(2026, 10, 11, 9, 20, tzinfo=TZ)
    assert r.text == "start the oven"


def test_to_borrow_as_written_is_text():
    r = parse_reminder("to borrow a book at 5pm", NOW)
    assert r.text == "borrow a book"


def test_misheard_tomorrow_keeps_too_in_text():
    r = parse_reminder("to borrow at nine am buy milk too and eggs", NOW)
    assert r.when == datetime(2026, 10, 11, 9, 0, tzinfo=TZ)
    assert r.text == "buy milk too and eggs"
