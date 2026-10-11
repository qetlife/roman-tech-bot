import asyncio

from datetime   import datetime, time, timedelta, timezone
from zoneinfo   import ZoneInfo

import pytest

from reminders.parser       import ParseError, parse_recurrence, parse_reminder
from reminders.recurrence   import EVERY_DAY, WEEKDAYS, WEEKENDS, Interval, Monthly, Weekly, parse

TZ = ZoneInfo("Europe/Kyiv")
# Saturday 10 Oct 2026, 23:30
NOW = datetime(2026, 10, 10, 23, 30, tzinfo=TZ)


def dt(day, hour, minute=0, month=10):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


# --- Recurrence -------------------------------------------------------------

@pytest.mark.parametrize("recurrence, text", [
    (Weekly(EVERY_DAY, time(9)),            "mon,tue,wed,thu,fri,sat,sun@09:00"),
    (Weekly(frozenset({0, 3}), time(18, 5)), "mon,thu@18:05"),
])
def test_serialize_roundtrip(recurrence, text):
    assert recurrence.serialize() == text
    assert parse(text) == recurrence


@pytest.mark.parametrize("recurrence, expected", [
    (Weekly(EVERY_DAY, time(9)),            "every day at 09:00"),
    (Weekly(WEEKDAYS, time(8, 30)),         "weekdays at 08:30"),
    (Weekly(WEEKENDS, time(10)),            "weekends at 10:00"),
    (Weekly(frozenset({3, 0}), time(18)),   "every Mon, Thu at 18:00"),
])
def test_describe(recurrence, expected):
    assert recurrence.describe(TZ) == expected


@pytest.mark.parametrize("recurrence, after, expected", [
    (Weekly(EVERY_DAY, time(9)),    dt(10, 8),      dt(10, 9)),
    (Weekly(EVERY_DAY, time(9)),    dt(10, 9),      dt(11, 9)),     # strictly after
    (Weekly(WEEKDAYS, time(9)),     dt(10, 8),      dt(12, 9)),     # Sat -> Mon
    (Weekly(frozenset({5}), time(9)), dt(10, 9),    dt(17, 9)),     # a week later
    # DST ends on 25 Oct: still 09:00 local
    (Weekly(EVERY_DAY, time(9)),    dt(24, 10),     dt(25, 9)),
])
def test_next_after(recurrence, after, expected):
    result = recurrence.next_after(after, TZ)
    assert result == expected
    assert result.utcoffset() == expected.utcoffset()


def test_next_after_accepts_utc_input():
    after = datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)   # 08:00 in Kyiv
    assert Weekly(EVERY_DAY, time(9)).next_after(after, TZ) == dt(10, 9)


# --- parsing ----------------------------------------------------------------

@pytest.mark.parametrize("phrase, days, clock, first", [
    ("every day",                   EVERY_DAY,          time(9),        dt(11, 9)),
    ("daily at 7am",                EVERY_DAY,          time(7),        dt(11, 7)),
    ("every day at 9",              EVERY_DAY,          time(9),        dt(11, 9)),
    ("at 23:45 every day",          EVERY_DAY,          time(23, 45),   dt(10, 23, 45)),
    ("every morning",               EVERY_DAY,          time(9),        dt(11, 9)),
    ("every evening at 7",          EVERY_DAY,          time(19),       dt(11, 19)),
    ("every weekday at 8:30",       WEEKDAYS,           time(8, 30),    dt(12, 8, 30)),
    ("on weekdays at 8:30",         WEEKDAYS,           time(8, 30),    dt(12, 8, 30)),
    ("weekends",                    WEEKENDS,           time(9),        dt(11, 9)),
    ("every monday",                frozenset({0}),     time(9),        dt(12, 9)),
    ("every mon and thu 18:00",     frozenset({0, 3}),  time(18),       dt(12, 18)),
    ("mondays and fridays",         frozenset({0, 4}),  time(9),        dt(12, 9)),
    ("every week",                  frozenset({5}),     time(9),        dt(17, 9)),
])
def test_parse_recurrence(phrase, days, clock, first):
    when, recurrence = parse_recurrence(phrase, NOW)
    assert recurrence == Weekly(days, clock)
    assert when == first


@pytest.mark.parametrize("phrase", [
    "tomorrow", "every", "every day tomorrow", "every day in 2 hours",
    "every day at", "tues", "on monday",
])
def test_parse_recurrence_rejects(phrase):
    assert parse_recurrence(phrase, NOW) is None


@pytest.mark.parametrize("request_, text, recurrence", [
    ("every day at 9 to take pills",        "take pills",   "every day at 09:00"),
    ("to take pills daily",                 "take pills",   "every day at 09:00"),
    ("on weekdays at 8:30: standup",        "standup",      "weekdays at 08:30"),
    ("water plants mondays and fridays",    "water plants", "every Mon, Fri at 09:00"),
])
def test_parse_reminder_recurring(request_, text, recurrence):
    parsed = parse_reminder(request_, NOW)
    assert parsed.text == text
    assert parsed.recurrence.describe(TZ) == recurrence


def test_parse_reminder_one_off_has_no_recurrence():
    assert parse_reminder("tomorrow at 9 to pay rent", NOW).recurrence is None


def test_parse_reminder_recurring_needs_text():
    with pytest.raises(ParseError, match="What should I remind you about?"):
        parse_reminder("every day at 9", NOW)


# --- monthly and interval ---------------------------------------------------

UTC = timezone.utc


@pytest.mark.parametrize("recurrence, text", [
    (Monthly(15, time(9)),                                          "month:15@09:00"),
    (Interval(timedelta(hours=2), datetime(2026, 10, 11, 7, 0, tzinfo=UTC)),  "every:120m@2026-10-11T07:00Z"),
])
def test_serialize_roundtrip_other_kinds(recurrence, text):
    assert recurrence.serialize() == text
    assert parse(text) == recurrence


@pytest.mark.parametrize("recurrence, after, expected", [
    (Monthly(15, time(9)),  dt(10, 8),              dt(15, 9)),
    (Monthly(15, time(9)),  dt(15, 9),              dt(15, 9, month=11)),
    (Monthly(31, time(9)),  dt(31, 10),             dt(30, 9, month=11)),   # last day of a short month
    (Monthly(1, time(9)),   dt(1, 10, month=12),    datetime(2027, 1, 1, 9, tzinfo=TZ)),
    (Interval(timedelta(hours=2), dt(10, 8)),       dt(10, 7),      dt(10, 8)),
    (Interval(timedelta(hours=2), dt(10, 8)),       dt(10, 8),      dt(10, 10)),
    (Interval(timedelta(hours=2), dt(10, 8)),       dt(10, 13, 5),  dt(10, 14)),
    (Interval(timedelta(days=3), dt(10, 9)),        dt(10, 9),      dt(13, 9)),
    # Whole days keep 09:00 local across the DST change on 25 Oct
    (Interval(timedelta(days=7), dt(20, 9)),        dt(26, 10),     dt(27, 9)),
])
def test_next_after_other_kinds(recurrence, after, expected):
    result = recurrence.next_after(after, TZ)
    assert result == expected
    assert result.utcoffset() == expected.utcoffset()


@pytest.mark.parametrize("recurrence, expected", [
    (Monthly(1, time(10)),                          "monthly on the 1st at 10:00"),
    (Monthly(22, time(9)),                          "monthly on the 22nd at 09:00"),
    (Monthly(11, time(9)),                          "monthly on the 11th at 09:00"),
    (Interval(timedelta(minutes=30), dt(10, 8)),    "every 30 min"),
    (Interval(timedelta(minutes=90), dt(10, 8)),    "every 1 h 30 min"),
    (Interval(timedelta(days=1), dt(10, 8)),        "every day at 08:00"),
    (Interval(timedelta(days=3), dt(10, 8)),        "every 3 days at 08:00"),
    (Interval(timedelta(days=14), dt(10, 8)),       "every 2 weeks at 08:00"),
])
def test_describe_other_kinds(recurrence, expected):
    assert recurrence.describe(TZ) == expected


@pytest.mark.parametrize("phrase, recurrence, first", [
    ("monthly",                         Monthly(10, time(9)),   dt(10, 9, month=11)),
    ("every month on the 15th",         Monthly(15, time(9)),   dt(15, 9)),
    ("on the 15th every month at 10",   Monthly(15, time(10)),  dt(15, 10)),
    ("every 1st",                       Monthly(1, time(9)),    dt(1, 9, month=11)),
    ("every 1st of the month at 8am",   Monthly(1, time(8)),    dt(1, 8, month=11)),
    ("the 31st of every month",         Monthly(31, time(9)),   dt(31, 9)),
    ("each month on the 2nd",           Monthly(2, time(9)),    dt(2, 9, month=11)),
    ("every 2 hours",                   Interval(timedelta(hours=2), dt(11, 1, 30)),     dt(11, 1, 30)),
    ("every hour",                      Interval(timedelta(hours=1), dt(11, 0, 30)),     dt(11, 0, 30)),
    ("every 30 minutes",                Interval(timedelta(minutes=30), dt(11, 0)),      dt(11, 0)),
    ("every 1h30m",                     Interval(timedelta(minutes=90), dt(11, 1)),      dt(11, 1)),
    ("every 3 days",                    Interval(timedelta(days=3), dt(11, 9)),          dt(11, 9)),
    ("every other day at 20:00",        Interval(timedelta(days=2), dt(11, 20)),         dt(11, 20)),
    ("every 2 weeks at 7am",            Interval(timedelta(days=14), dt(11, 7)),         dt(11, 7)),
])
def test_parse_other_kinds(phrase, recurrence, first):
    assert parse_recurrence(phrase, NOW) == (first, recurrence)


@pytest.mark.parametrize("phrase", [
    "every 2 hours at 9", "every month tomorrow", "every 32nd", "every 15",
])
def test_parse_other_kinds_rejects(phrase):
    assert parse_recurrence(phrase, NOW) is None


@pytest.mark.parametrize("phrase, message", [
    ("every 5 minutes",     "shortest repeat is every 15 minutes"),
    ("every 30 seconds",    "shortest repeat"),
])
def test_parse_interval_too_short(phrase, message):
    with pytest.raises(ParseError, match=message):
        parse_recurrence(phrase, NOW)


@pytest.mark.parametrize("request_, text, recurrence", [
    ("every 2 hours to drink water",            "drink water",  "every 2 h"),
    ("to pay rent on the 1st of every month",   "pay rent",     "monthly on the 1st at 09:00"),
    ("every other day at 9: water plants",      "water plants", "every 2 days at 09:00"),
])
def test_parse_reminder_other_kinds(request_, text, recurrence):
    parsed = parse_reminder(request_, NOW)
    assert parsed.text == text
    assert parsed.recurrence.describe(TZ) == recurrence


def test_interval_delivery_catches_up(user):
    reminder = _reminder(user, dt(11, 9), recurrence="every:120m@2026-10-11T06:00Z")   # 09:00 Kyiv
    _deliver(reminder, dt(11, 9, 1))
    # Unanswered at 11:00: that one takes over.
    _deliver(_reload(reminder), dt(11, 11, 0))
    assert _reload(reminder).remind_at == dt(11, 11)


# --- delivery ---------------------------------------------------------------

class FakeBot:
    def __init__(self):
        self.sent, self.edited, self.deleted = [], [], []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(text)

        class Message:
            message_id = 100 + len(self.sent)
        return Message()

    async def edit_message_text(self, chat_id, message_id, text):
        self.edited.append(text)

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


def _deliver(reminder, now):
    from reminders.delivery import _deliver as deliver

    bot = FakeBot()
    asyncio.run(deliver(bot, reminder, now, [10], timedelta(minutes=5), TZ))
    return bot


def _reminder(user, remind_at, recurrence="mon,tue,wed,thu,fri,sat,sun@09:00"):
    from db.repository.reminder_repository import ReminderRepository
    return ReminderRepository().create(user, 1, "take pills", remind_at, recurrence)


def _reload(reminder):
    from db.db import SessionLocal
    from models.reminder import Reminder
    with SessionLocal() as s:
        return s.get(Reminder, reminder.id)


def test_recurring_fires_like_a_one_off(user):
    from models.reminder import ReminderStatus

    reminder = _reminder(user, dt(11, 9))
    bot = _deliver(reminder, dt(11, 9, 1))
    assert bot.sent == ["⏰ take pills"]
    assert _reload(reminder).status == ReminderStatus.FIRING


def test_recurring_unanswered_moves_to_the_next_occurrence(user):
    from models.reminder import ReminderStatus

    reminder = _reminder(user, dt(11, 9))
    _deliver(reminder, dt(11, 9, 1))

    # Still firing when the next day's 09:00 comes: that one takes over.
    bot = _deliver(_reload(reminder), dt(12, 9))
    assert bot.sent == [] and "the next one is due" in bot.edited[0]
    reloaded = _reload(reminder)
    assert reloaded.status == ReminderStatus.PENDING
    assert reloaded.remind_at == dt(12, 9)

    bot = _deliver(reloaded, dt(12, 9))
    assert bot.sent == ["⏰ take pills"]


def test_recurring_catches_up_to_the_latest_occurrence(user):
    # The bot was down for three days: only today's occurrence is sent.
    reminder = _reminder(user, dt(11, 9))
    _deliver(reminder, dt(14, 10))
    assert _reload(reminder).remind_at == dt(14, 9)


def test_weekly_gives_up_after_24_hours(user):
    from models.reminder import ReminderStatus

    reminder = _reminder(user, dt(12, 9), recurrence="mon@09:00")
    _deliver(reminder, dt(12, 9, 1))
    bot = _deliver(_reload(reminder), dt(13, 9, 1))
    assert "no response for 24 h" in bot.edited[0]
    reloaded = _reload(reminder)
    assert reloaded.status == ReminderStatus.PENDING
    assert reloaded.remind_at == dt(19, 9)


def test_one_off_still_marked_missed(user):
    from models.reminder import ReminderStatus

    reminder = _reminder(user, dt(12, 9), recurrence=None)
    _deliver(reminder, dt(12, 9, 1))
    _deliver(_reload(reminder), dt(13, 9, 1))
    assert _reload(reminder).status == ReminderStatus.MISSED
