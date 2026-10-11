import asyncio

from datetime   import datetime, time, timedelta
from zoneinfo   import ZoneInfo

import pytest

from reminders.quiet        import is_quiet, quiet_end, skip_quiet
from reminders.recurrence   import EVERY_DAY, Interval, Weekly
from settings.registry      import (
    QUIET_HOURS, format_quiet_hours, parse_quiet_hours, quiet_window, validate_quiet_hours,
)

TZ = ZoneInfo("Europe/Kyiv")
NIGHT = (time(0), time(7))
LATE = (time(23), time(7))      # wraps midnight
DAYTIME = (time(13), time(14))


def dt(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


# --- setting ----------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("23:00-07:00",     ["23:00", "07:00"]),
    ("23 to 7",         ["23:00", "07:00"]),
    ("22:30 - 8",       ["22:30", "08:00"]),
    ("0–6:45",          ["00:00", "06:45"]),
    ("off",             []),
])
def test_parse_quiet_hours(text, expected):
    assert parse_quiet_hours(text) == expected


@pytest.mark.parametrize("text, message", [
    ("7-7",         "different times"),
    ("25-3",        "isn't a time"),
    ("night",       "start and an end"),
])
def test_parse_quiet_hours_errors(text, message):
    with pytest.raises(ValueError, match=message):
        parse_quiet_hours(text)


@pytest.mark.parametrize("value", [None, "00:00-07:00", ["00:00"], [0, 7], ["00:00", "07:00", "08:00"]])
def test_validate_quiet_hours_rejects(value):
    with pytest.raises(ValueError):
        validate_quiet_hours(value)


def test_quiet_default():
    assert validate_quiet_hours(QUIET_HOURS.default) == ["00:00", "07:00"]
    assert quiet_window(QUIET_HOURS.default) == NIGHT
    assert quiet_window([]) is None
    assert format_quiet_hours(QUIET_HOURS.default) == "00:00–07:00"
    assert format_quiet_hours([]) == "Off"


# --- window -----------------------------------------------------------------

@pytest.mark.parametrize("quiet, when, expected", [
    (NIGHT,     dt(11, 0),      True),
    (NIGHT,     dt(11, 6, 59),  True),
    (NIGHT,     dt(11, 7),      False),
    (NIGHT,     dt(10, 23, 59), False),
    (LATE,      dt(10, 23),     True),
    (LATE,      dt(11, 3),      True),
    (LATE,      dt(11, 12),     False),
    (DAYTIME,   dt(11, 13, 30), True),
    (None,      dt(11, 3),      False),
])
def test_is_quiet(quiet, when, expected):
    assert is_quiet(when, quiet, TZ) is expected


@pytest.mark.parametrize("quiet, when, expected", [
    (NIGHT, dt(11, 3),      dt(11, 7)),
    (LATE,  dt(10, 23, 30), dt(11, 7)),
    (LATE,  dt(11, 1),      dt(11, 7)),
])
def test_quiet_end(quiet, when, expected):
    assert quiet_end(when, quiet, TZ) == expected


def test_skip_quiet_moves_interval_past_the_night():
    every_2h = Interval(timedelta(hours=2), dt(10, 23, 30))
    assert skip_quiet(every_2h, dt(11, 1, 30), NIGHT, TZ) == dt(11, 7, 30)
    assert skip_quiet(every_2h, dt(11, 9, 30), NIGHT, TZ) == dt(11, 9, 30)


@pytest.mark.parametrize("recurrence", [
    Weekly(EVERY_DAY, time(3)),                     # explicit time
    Interval(timedelta(days=2), dt(11, 3)),         # whole days keep their time
])
def test_skip_quiet_keeps_explicit_times(recurrence):
    assert skip_quiet(recurrence, dt(11, 3), NIGHT, TZ) == dt(11, 3)


# --- delivery ---------------------------------------------------------------

from tests.test_recurrence import FakeBot, _reload, _reminder   # noqa: E402


def _deliver(reminder, now, quiet=NIGHT):
    from reminders.delivery import _deliver as deliver

    bot = FakeBot()
    asyncio.run(deliver(bot, reminder, now, [10], timedelta(minutes=5), TZ, quiet))
    return bot


def test_one_off_fires_in_quiet_hours_but_repeats_wait(user):
    reminder = _reminder(user, dt(11, 3), recurrence=None)
    assert _deliver(reminder, dt(11, 3)).sent == ["⏰ take pills"]

    bot = _deliver(_reload(reminder), dt(11, 3, 5))
    assert bot.sent == []
    assert _reload(reminder).next_fire_at == dt(11, 7)

    bot = _deliver(_reload(reminder), dt(11, 7))
    assert bot.sent == ["⏰ take pills\n\n🔁 Still waiting for your OK."]


def test_interval_occurrence_in_quiet_hours_is_skipped(user):
    from models.reminder import ReminderStatus

    reminder = _reminder(user, dt(11, 1, 30), recurrence="every:120m@2026-10-10T20:30Z")  # 23:30 Kyiv
    bot = _deliver(reminder, dt(11, 1, 30))
    assert bot.sent == []
    reloaded = _reload(reminder)
    assert reloaded.status == ReminderStatus.PENDING
    assert reloaded.remind_at == dt(11, 7, 30)


def test_interval_fires_when_quiet_hours_are_off(user):
    reminder = _reminder(user, dt(11, 1, 30), recurrence="every:120m@2026-10-10T20:30Z")
    assert _deliver(reminder, dt(11, 1, 30), quiet=None).sent == ["⏰ take pills"]


def test_daily_at_explicit_time_fires_in_quiet_hours(user):
    reminder = _reminder(user, dt(11, 3), recurrence="mon,tue,wed,thu,fri,sat,sun@03:00")
    assert _deliver(reminder, dt(11, 3)).sent == ["⏰ take pills"]


def test_repository_stores_off(user):
    from db.repository.settings_repository import SettingsRepository

    repo = SettingsRepository()
    assert repo.get(user.id, QUIET_HOURS) == ["00:00", "07:00"]
    repo.set(user.id, QUIET_HOURS, [])
    assert repo.get(user.id, QUIET_HOURS) == []
    repo.set(user.id, QUIET_HOURS, ["23:00", "07:00"])
    assert repo.get(user.id, QUIET_HOURS) == ["23:00", "07:00"]
