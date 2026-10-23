"""📅 Events and reminders relative to them: core/events.py, the parser's moves, handlers/events.py."""

import asyncio

from datetime   import datetime, time, timedelta, timezone
from types      import SimpleNamespace
from zoneinfo   import ZoneInfo

import pytest

from core           import recurrence as recurrences
from core.events    import (
    match_title, nearest_occurrence, next_occurrence, occurs_on, parse_event, reminder_time, split_move,
    split_move_statement, split_relative, unknown_title, with_skipped,
)
from core.parser    import MissingText, MissingTime, ParseError, parse_move
from tests.test_handlers import _active, _buttons, _replies, _update


TZ = ZoneInfo("Europe/Lisbon")
# Wednesday 21 October 2026, 10:00
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=TZ)


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def event(starts_at, recurrence=None, all_day=False, skipped=None, title="padel"):
    return SimpleNamespace(title=title, starts_at=starts_at, recurrence=recurrence, timezone="Europe/Lisbon",
                           skipped=skipped, all_day=all_day)


# --- parsing events ---------------------------------------------------------

def test_parse_event():
    parsed = parse_event("padel on thursday at 21:00", NOW)
    assert (parsed.title, parsed.starts_at, parsed.recurrence, parsed.all_day) == ("padel", at(22, 21), None, False)


def test_parse_repeating_event():
    parsed = parse_event("every thursday at 21:00: padel", NOW)
    assert parsed.recurrence.serialize() == "thu@21:00"
    assert parsed.starts_at == at(22, 21)


@pytest.mark.parametrize("request_, day", [("dentist on friday", 23), ("dentist today", 21), ("dentist tomorrow", 22)])
def test_a_day_without_a_time_is_all_day(request_, day):
    parsed = parse_event(request_, NOW)
    assert parsed.all_day and parsed.starts_at == datetime(2026, 10, day, 0, 0, tzinfo=TZ)
    assert parsed.title == "dentist"


def test_a_repeating_all_day_event_starts_at_midnight():
    parsed = parse_event("every friday: gym day", NOW)
    assert parsed.all_day and parsed.recurrence.serialize() == "fri@00:00"
    # Said on a Wednesday after 09:00: today is one of them
    assert parse_event("every wednesday: gym day", NOW).starts_at == at(21, 0)


def test_a_time_that_passed_today_is_still_refused():
    with pytest.raises(ParseError, match="already passed"):
        parse_event("dentist today at 09:00", NOW)


def test_missing_halves():
    with pytest.raises(MissingText):
        parse_event("on thursday at 21:00", NOW)
    with pytest.raises(MissingTime):
        parse_event("padel", NOW)


# --- before every occurrence ------------------------------------------------

def test_offset_round_trip_and_skips():
    weekly = recurrences.Weekly(frozenset({3}), time(21, 0))
    skip = at(29, 21)
    rule = recurrences.Offset(weekly, -30, "Europe/Lisbon", frozenset({skip}))
    stored = rule.serialize()
    assert stored == "event:-30m;Europe/Lisbon;20261029T2100Z;thu@21:00"
    assert recurrences.parse(stored) == rule
    # The 29th is skipped: after the 22nd comes 5 November
    assert rule.next_after(at(22, 20, 30), TZ) == datetime(2026, 11, 5, 20, 30, tzinfo=TZ)
    assert rule.next_after(NOW, TZ) == at(22, 20, 30)
    assert rule.describe(TZ) == "30 min before, every Thu at 21:00"


def test_reminder_time_once_or_every():
    padel = event(at(22, 21), "thu@21:00")
    assert reminder_time(padel, -30, NOW) == (at(22, 20, 30), None)
    when, rule = reminder_time(padel, -30, NOW, every=True)
    assert when == at(22, 20, 30) and rule.serialize() == "event:-30m;Europe/Lisbon;;thu@21:00"
    # Too late for this week's: the next one
    assert reminder_time(padel, -30, at(22, 20, 45).astimezone(timezone.utc))[0] == at(29, 20, 30)
    assert reminder_time(event(at(22, 21)), -60, NOW) == (at(22, 20), None)


def test_occurrences():
    padel = event(at(22, 21), "thu@21:00", skipped="20261029T2100Z")
    assert next_occurrence(padel, at(22, 22)) == datetime(2026, 11, 5, 21, tzinfo=TZ)
    assert occurs_on(padel, at(22, 0).date(), TZ) and not occurs_on(padel, at(29, 0).date(), TZ)
    assert nearest_occurrence(padel, at(29, 20)) == at(29, 21)
    assert next_occurrence(event(at(20, 21)), NOW) is None
    # All day: all of today
    assert next_occurrence(event(at(21, 0), all_day=True), NOW) == at(21, 0)


def test_with_skipped_drops_the_past():
    padel = event(at(15, 21), "thu@21:00", skipped="20261015T2000Z")
    assert with_skipped(padel, at(29, 21), NOW) == "20261029T2100Z"


# --- what a message says ----------------------------------------------------

@pytest.mark.parametrize("request_, minutes, event_words, text", [
    ("30 min before padel to pack the racket", -30, "padel to pack the racket", None),
    ("an hour before the padel", -60, "the padel", None),
    ("to stretch 10 minutes after padel", 10, "padel", "to stretch"),
    ("1h30m before padel", -90, "padel", None),
    ("the day before the trip to pack", -1440, "the trip to pack", None),
])
def test_split_relative(request_, minutes, event_words, text):
    relative = split_relative(request_)
    assert relative.minutes == minutes
    assert " ".join(relative.event) == event_words
    assert (" ".join(relative.text) if relative.text else None) == text


@pytest.mark.parametrize("request_", ["tomorrow at 9 to call mom", "to call mom after work", "before padel"])
def test_not_relative(request_):
    assert split_relative(request_) is None


def test_match_title():
    titles = ["padel", "padel tournament", "trip to porto"]
    assert match_title("the padel tournament to pack".split(), titles) == ("padel tournament", ["to", "pack"])
    assert match_title("my Padel, pack".split(), titles) == ("padel", ["pack"])
    assert match_title("trip to porto event".split(), titles) == ("trip to porto", [])
    assert match_title("tennis to pack".split(), titles) is None
    assert unknown_title("the tennis to pack".split()) == "tennis"


def test_split_move():
    titles = ["padel"]
    assert split_move("padel to 20:00", titles) == ("padel", "20:00")
    assert split_move("the padel to friday at 8", titles) == ("padel", "friday at 8")
    assert split_move_statement("padel is at 20:00 now", titles) == ("padel", "at 20:00")
    assert split_move_statement("Padel is now on friday.", titles) == ("padel", "on friday")
    assert split_move_statement("tennis is at 20:00", titles) is None


# --- moving -----------------------------------------------------------------

@pytest.mark.parametrize("phrase, when, timed", [
    ("20:00", at(22, 20), True),
    ("8", at(22, 20), True),            # closer to 21:00 than 08:00 is
    ("friday", at(23, 21), False),      # the same time of day
    ("friday at 9am", at(23, 9), True),
])
def test_parse_move(phrase, when, timed):
    moved = parse_move(phrase, at(22, 21), NOW)
    assert (moved.when, moved.recurrence, moved.timed) == (when, None, timed)


def test_parse_move_a_repeat():
    weekly = recurrences.Weekly(frozenset({3}), time(21, 0))
    moved = parse_move("20:00", at(22, 21), NOW, weekly)
    assert moved.recurrence.serialize() == "thu@20:00" and moved.when == at(22, 20)
    assert parse_move("friday", at(22, 21), NOW, weekly).recurrence.serialize() == "fri@21:00"
    assert parse_move("every monday at 19:00", at(22, 21), NOW, weekly).recurrence.serialize() == "mon@19:00"
    # A day of a weekday repeat with several days, or a date: ✏️ Edit instead
    assert parse_move("friday", at(22, 21), NOW, recurrences.Weekly(frozenset({0, 3}), time(21, 0))) is None
    assert parse_move("dec 24", at(22, 21), NOW, weekly) is None


# --- handlers ---------------------------------------------------------------

def _events(telegram_id):
    from db.repositories.event import EventRepository
    from db.repositories.user import UserRepository

    return EventRepository().list_active(UserRepository().get_by_telegram_id(telegram_id).id)


def _reminders(event_id):
    from db.repositories.reminder import ReminderRepository

    return ReminderRepository().list_for_event(event_id)


def _press(chat, data):
    from handlers.events import on_event_button
    return chat(data=data, handler=on_event_button)


def _local(when):
    return when.astimezone(TZ)


def test_create_an_event(chat):
    update = chat("event padel on dec 24 at 21:00")
    reply = _replies(update)[0]
    assert reply.startswith("📅 Added: padel\n🗓 ")
    [padel] = _events(chat.telegram_id)
    assert (_local(padel.starts_at).month, _local(padel.starts_at).day, _local(padel.starts_at).hour) == (12, 24, 21)
    keyboard = _buttons(update.effective_message.reply_text.call_args.kwargs["reply_markup"])
    assert keyboard[0] == [("⏰ 15 min before", f"evt:rem:{padel.id}:-15"), ("⏰ 30 min before", f"evt:rem:{padel.id}:-30"),
                           ("⏰ 1 h before", f"evt:rem:{padel.id}:-60")]
    assert keyboard[1] == [("↩️ Undo", f"evt:undo:{padel.id}"), ("✏️ Edit", f"evt:edit:{padel.id}"),
                           ("👎 Wrong", f"evt:wrong:{padel.id}")]


@pytest.mark.parametrize("message", [
    "put padel on dec 24 at 21:00 in my calendar", "add to my calendar: padel on dec 24 at 21:00",
    "add an event padel on dec 24 at 21:00", "please create an event: padel on dec 24 at 21:00",
])
def test_other_ways_to_create(chat, message):
    assert _replies(chat(message))[0].startswith("📅 Added: padel")


def test_add_without_calendar_isnt_an_event(chat):
    assert _replies(chat("add milk to the list"))[0].startswith("I didn't get that.")
    assert _events(chat.telegram_id) == []


def test_asks_when_and_what(chat):
    assert _replies(chat("event padel"))[0].startswith("📅 When is “padel”?")
    assert _replies(chat("dec 24 at 21:00"))[0].startswith("📅 Added: padel")
    assert _replies(chat("event on dec 25 at 10:00"))[0] == "📅 on dec 25 at 10:00: what's the event?"
    assert _replies(chat("christmas brunch"))[0].startswith("📅 Added: christmas brunch")


def test_quick_reminder_on_an_event(chat):
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat.telegram_id)
    update = _press(chat, f"evt:rem:{padel.id}:-30")
    assert _replies(update)[0].startswith("⏰ Got it: padel\n📅 30 min before padel\n🗓 ")
    [reminder] = _reminders(padel.id)
    assert reminder.remind_at == padel.starts_at - timedelta(minutes=30) and reminder.recurrence is None


def test_reminder_relative_to_an_event_by_text(chat):
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat.telegram_id)
    update = chat("remind me 1 hour before padel to pack the racket")
    assert _replies(update)[0].startswith("⏰ Got it: pack the racket\n📅 1 h before padel")
    [reminder] = _reminders(padel.id)
    assert (reminder.text, reminder.event_offset) == ("pack the racket", -60)
    assert reminder.remind_at == padel.starts_at - timedelta(hours=1)


def test_reminder_relative_to_an_unknown_event(chat):
    update = chat("remind me 30 min before tennis to pack the racket")
    assert _replies(update)[0].startswith("I don't have an event called “tennis”.")


@pytest.mark.parametrize("request_", [
    "remind me 2000 days before padel", "remind me 99999999 days before padel", "remind me 9999999999 days after padel",
])
def test_too_far_from_the_event(chat, request_):
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat.telegram_id)
    assert _replies(chat(request_))[0].startswith("That's too far from the event")
    assert _reminders(padel.id) == []


def test_skip_today_of_an_all_day_repeat(chat):
    from db.models.reminder import utcnow
    from handlers.events import users as event_users

    tz = ZoneInfo(event_users.get_by_telegram_id(chat.telegram_id).timezone)
    weekday = utcnow().astimezone(tz).strftime("%A").lower()
    chat(f"event every {weekday}: gym day")
    [gym] = _events(chat.telegram_id)
    today = next_occurrence(gym, utcnow())
    assert today.astimezone(tz).date() == utcnow().astimezone(tz).date()
    update = _press(chat, f"evt:skip:{gym.id}:{recurrences.format_stamp(today)}")
    assert update.callback_query.answer.call_args.args[0].startswith("No gym day on ")
    assert next_occurrence(_events(chat.telegram_id)[0], utcnow()) == today + timedelta(days=7)


def test_before_and_after_without_an_event_is_an_ordinary_reminder(chat):
    update = chat("remind me to take pills 30 min after breakfast every day")
    assert _replies(update)[0].startswith("⏰ Got it: take pills 30 min after breakfast\n")


def test_moving_an_all_day_event(chat):
    chat("event dentist on dec 24")
    [dentist] = _events(chat.telegram_id)
    assert _replies(chat("move dentist to dec 23"))[0].startswith("📅 Moved: dentist\n🗓 Wed 23 Dec (all day)")
    assert _replies(chat("move dentist to 10:30"))[0].startswith("📅 Moved: dentist\n🗓 Wed 23 Dec, 10:30")
    [moved] = _events(chat.telegram_id)
    assert not moved.all_day


@pytest.mark.parametrize("answer, every", [("evt:every", True), ("evt:once", False)])
def test_a_repeating_event_asks_once_or_every_time(chat, answer, every):
    chat("event every thursday at 21:00: padel")
    [padel] = _events(chat.telegram_id)
    update = chat("remind me 30 min before padel to pack the racket")
    assert _replies(update)[0] == "⏰ pack the racket, 30 min before padel: just the next one, or every time?"
    update = _press(chat, f"{answer}:{padel.id}")
    assert _replies(update)[0].startswith("⏰ Got it: pack the racket")
    [reminder] = _reminders(padel.id)
    first = next_occurrence(padel, reminder.created_at)
    assert reminder.remind_at == first - timedelta(minutes=30)
    assert (reminder.recurrence is not None) == every
    if every:
        assert "🔁 30 min before, every Thu at 21:00" in _replies(update)[0]


def test_the_question_expires(chat):
    chat("event every thursday at 21:00: padel")
    [padel] = _events(chat.telegram_id)
    update = _press(chat, f"evt:every:{padel.id}")
    assert "expired" in update.callback_query.answer.call_args.args[0]
    assert _reminders(padel.id) == []


def test_moving_an_event_moves_its_reminders(chat):
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat.telegram_id)
    _press(chat, f"evt:rem:{padel.id}:-30")
    update = chat("move padel to 20:00")
    assert _replies(update)[0].startswith("📅 Moved: padel\n🗓 ")
    assert "⏰ Its reminder moved with it." in _replies(update)[0]
    [moved] = _events(chat.telegram_id)
    assert (_local(moved.starts_at).day, _local(moved.starts_at).hour) == (24, 20)
    assert _reminders(padel.id)[0].remind_at == moved.starts_at - timedelta(minutes=30)


def test_moving_a_repeating_event(chat):
    chat("event every thursday at 21:00: padel")
    [padel] = _events(chat.telegram_id)
    chat("remind me 30 min before padel to pack the racket")
    _press(chat, f"evt:every:{padel.id}")
    update = chat("padel is at 20:00 now")
    assert _replies(update)[0].startswith("📅 Moved: padel")
    [moved] = _events(chat.telegram_id)
    assert moved.recurrence == "thu@20:00"
    [reminder] = _reminders(padel.id)
    assert reminder.recurrence.endswith(";thu@20:00")
    assert _local(reminder.remind_at).time() == time(19, 30)


def test_move_an_unknown_event(chat):
    assert _replies(chat("move tennis to 20:00"))[0].startswith("I don't have an event called “tennis”.")


def test_cancelling_an_event_cancels_its_reminders(chat):
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat.telegram_id)
    _press(chat, f"evt:rem:{padel.id}:-30")
    update = chat("cancel padel")
    assert _replies(update)[0].startswith("Cancel “padel”?")
    keyboard = _buttons(update.effective_message.reply_text.call_args.kwargs["reply_markup"])
    assert keyboard == [[("🗑 Cancel it", f"evt:del:{padel.id}")]]
    _press(chat, f"evt:del:{padel.id}")
    assert _events(chat.telegram_id) == [] and _reminders(padel.id) == []


def test_cancel_a_reminder_still_works(chat):
    chat("event padel on dec 24 at 21:00")
    chat("remind me on dec 24 at 9 to call the dentist")
    assert _replies(chat("cancel the dentist"))[0].startswith("Cancel “call the dentist”?")


def test_skipping_one_occurrence(chat):
    chat("event every thursday at 21:00: padel")
    [padel] = _events(chat.telegram_id)
    chat("remind me 30 min before padel to pack the racket")
    _press(chat, f"evt:every:{padel.id}")
    chat("remind me 1 hour before padel to book a court")
    _press(chat, f"evt:once:{padel.id}")
    first = next_occurrence(padel, padel.created_at)
    update = chat("cancel padel")
    keyboard = _buttons(update.effective_message.reply_text.call_args.kwargs["reply_markup"])
    stamp = recurrences.format_stamp(first)
    assert keyboard[0][0][1] == f"evt:skip:{padel.id}:{stamp}"
    _press(chat, f"evt:skip:{padel.id}:{stamp}")
    [every] = _reminders(padel.id)    # the one for that occurrence only is cancelled
    assert every.text == "pack the racket"
    assert every.remind_at == first + timedelta(days=7, minutes=-30)
    assert stamp in every.recurrence


def test_untriggered_asks_event_or_reminder(chat):
    from handlers.events import on_pick

    update = chat("padel on dec 24 at 21:00")
    assert _replies(update)[0].endswith("Is this an event or a reminder?")
    update = chat(data="pick:event", handler=on_pick)
    assert _replies(update)[0].startswith("📅 Added: padel")
    chat("tennis on dec 25 at 10:00")
    update = chat(data="pick:reminder", handler=on_pick)
    assert _replies(update)[0].startswith("⏰ Got it: tennis")


def test_wrong_saves_the_event_as_failed(chat):
    from db.repositories.failed_message import FailedMessageRepository

    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat.telegram_id)
    _press(chat, f"evt:rem:{padel.id}:-30")
    update = _press(chat, f"evt:wrong:{padel.id}")
    assert update.callback_query.edit_message_text.call_args.args[0].startswith(
        "👎 Cancelled: padel and its reminder")
    entry = FailedMessageRepository().open_for_event(padel.id)
    assert (entry.text, entry.intent, entry.bot_understood["title"]) == ("padel on dec 24 at 21:00", "event.create", "padel")
    assert _events(chat.telegram_id) == []


def test_thats_wrong_after_an_event(chat):
    chat("remind me on dec 24 at 9 to call mom")
    chat("event padel on dec 24 at 21:00")
    assert _replies(chat("that's wrong"))[0].startswith("👎 Cancelled: padel")
    assert len(_active(chat.telegram_id)) == 1


def test_list_and_screen(chat):
    from handlers.events import on_events_menu

    chat("event every thursday at 21:00: padel")
    chat("event dentist on dec 24")
    update = chat("my events")
    text = _replies(update)[0]
    assert text.startswith("📅 Your events:\n\n1. padel\n    🗓 ") and "🔁 every Thu at 21:00" in text
    assert "2. dentist\n    🗓 Thu 24 Dec (all day)" in text
    [padel, dentist] = _events(chat.telegram_id)
    chat(data="menu:events", handler=on_events_menu)
    _press(chat, f"evt:open:{padel.id}")
    text, keyboard = chat.screen()
    assert text.startswith("📅 padel\n🗓 ")
    assert [b[0] for b in _buttons(keyboard)[1]][0] == "✏️ Edit" and _buttons(keyboard)[1][1][0].startswith("⏭ Skip")
    _press(chat, f"evt:open:{dentist.id}")
    assert [b[0] for b in _buttons(chat.screen()[1])[0]] == ["⏰ the day before, 09:00", "⏰ on the day, 09:00"]


def test_agenda_shows_events(chat):
    chat("event padel on dec 24 at 21:00")
    chat("remind me on dec 24 at 9 to call mom")
    text = _replies(chat("what do I have on dec 24?"))[0]
    assert text.startswith("📅 Events on Thu 24 Dec:\n• 21:00 padel\n\nYour reminders on Thu 24 Dec")


def test_edit_an_event(chat):
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat.telegram_id)
    _press(chat, f"evt:rem:{padel.id}:-15")
    _press(chat, f"evt:edit:{padel.id}")
    update = chat("padel tournament on dec 26 at 10:00")
    assert _replies(update)[0].startswith("✏️ Updated: padel tournament")
    [reminder] = _reminders(padel.id)
    assert (_local(reminder.remind_at).day, _local(reminder.remind_at).time()) == (26, time(9, 45))


def test_move_during_a_question_is_an_answer(chat):
    chat("remind me tomorrow at 9")
    assert _replies(chat("move the car"))[0].startswith("⏰ Got it: move the car")


def test_someone_elses_event_button(chat):
    from db.repositories.event import EventRepository
    from db.repositories.user import UserRepository

    other = UserRepository().get_or_create(chat.telegram_id + 7)
    foreign = EventRepository().create(other.id, "secret", datetime(2026, 12, 24, 21, tzinfo=TZ), "Europe/Lisbon")
    update = _press(chat, f"evt:del:{foreign.id}")
    assert update.callback_query.answer.call_args.args[0] == "This event isn't yours."


def test_delivered_reminder_names_its_event(chat):
    from tests.test_recurrence import FakeBot
    from db.repositories.event import EventRepository
    from db.repositories.reminder import ReminderRepository
    from jobs.delivery import _deliver

    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat.telegram_id)
    _press(chat, f"evt:rem:{padel.id}:-30")
    [reminder] = _reminders(padel.id)
    bot = FakeBot()
    asyncio.run(_deliver(bot, reminder, reminder.remind_at, [10], timedelta(minutes=5), TZ,
                         event=EventRepository().get(padel.id)))
    assert bot.sent == ["⏰ padel\n📅 padel: Today, 21:00 (in 30 min)"]
    assert ReminderRepository().get(reminder.id).status == "firing"


def test_first_event_asks_for_the_timezone(db):
    import random
    from unittest.mock import MagicMock

    from db.repositories.user import UserRepository
    from handlers.text import on_text

    telegram_id = random.randint(10**9, 10**12)
    UserRepository().get_or_create(telegram_id)
    context = MagicMock(user_data={}, chat_data={})
    update = _update(telegram_id, text="event padel on dec 24 at 21:00")
    asyncio.run(on_text(update, context))
    assert "Which timezone" in _replies(update)[0]
    update = _update(telegram_id, text="Lisbon")
    asyncio.run(on_text(update, context))
    assert _replies(update)[1].startswith("📅 Added: padel")


@pytest.mark.parametrize("text, intent, fixed", [
    ("padel on dec 24 at 21:00", "event.create", True),
    ("padel on the moon", "event.create", True),      # asks when
    ("on the moon", "event.when", False),
    ("dec 24 at 9", "event.when", True),
    ("event padel on dec 24 at 21:00", None, True),
    ("padel to 20:00", "event.move", False),
])
def test_failed_recheck_knows_events(text, intent, fixed):
    from jobs.failed import understood
    assert understood(text, intent, NOW) == fixed
