"""Telegram handlers end to end, with mocked Telegram objects."""

import asyncio
import random

from unittest.mock import AsyncMock, MagicMock

import pytest


def _update(telegram_id, data=None, text=None):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.effective_chat.id = telegram_id
    if data is None:
        update.callback_query = None
    else:
        query = update.callback_query
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.message.reply_text = AsyncMock()
    update.effective_message.text = text
    update.effective_message.voice = None     # typed, not a voice message
    update.effective_message.reply_text = AsyncMock()
    return update


def _replies(update):
    return [c.args[0] for c in update.effective_message.reply_text.call_args_list]


@pytest.fixture
def chat(db, monkeypatch):
    """A new user with a timezone, and a function to send them messages/buttons.

    Menu screens aren't sent; `chat.screen()` is the last one rendered: (text, keyboard).
    """
    from db.repositories.user import UserRepository
    from handlers import commands, menus, reminders, settings
    from handlers.text import on_text

    render = AsyncMock()
    for module in (commands, menus, reminders, settings):
        monkeypatch.setattr(module, "render_menu", render)

    telegram_id = random.randint(10**9, 10**12)
    UserRepository().get_or_create(telegram_id)
    UserRepository().set_timezone(telegram_id, "Europe/Lisbon")
    context = MagicMock(user_data={}, chat_data={})
    context.bot.edit_message_text = AsyncMock()

    def send(text=None, data=None, handler=None):
        update = _update(telegram_id, data=data, text=text)
        asyncio.run((handler or on_text)(update, context))
        return update

    send.telegram_id = telegram_id
    send.context = context
    send.screen = lambda: render.call_args.args[2:4]
    return send


def _buttons(keyboard):
    """[[(text, callback data), ...], ...] of an inline keyboard."""
    return [[(b.text, b.callback_data) for b in row] for row in keyboard.inline_keyboard]


def _active(telegram_id):
    from db.repositories.reminder import ReminderRepository
    from db.repositories.user import UserRepository

    return ReminderRepository().list_active(UserRepository().get_by_telegram_id(telegram_id).id)


def test_create_snooze_and_delete(chat):
    from handlers.reminders import on_reminder_button

    update = chat("remind me tomorrow at 9 to call mom")
    assert _replies(update)[0].startswith("⏰ Got it: call mom")
    reminder_id = _active(chat.telegram_id)[0].id

    update = chat(data=f"rem:snz:{reminder_id}:15", handler=on_reminder_button)
    assert update.callback_query.edit_message_text.call_args.args[0].startswith("💤 call mom")

    chat(data=f"rem:del:{reminder_id}", handler=on_reminder_button)
    assert _active(chat.telegram_id) == []


def test_edit(chat):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    reminder_id = _active(chat.telegram_id)[0].id

    chat(data=f"rem:edit:{reminder_id}", handler=on_reminder_button)
    update = chat("every day at 10 to call dad")
    assert "✏️ Updated: call dad" in _replies(update)[0]
    assert _active(chat.telegram_id)[0].recurrence == "mon,tue,wed,thu,fri,sat,sun@10:00"


def test_first_reminder_asks_for_timezone_then_creates_it(db):
    from db.repositories.user import UserRepository
    from handlers.text import on_text

    telegram_id = random.randint(10**9, 10**12)
    UserRepository().get_or_create(telegram_id)
    context = MagicMock(user_data={}, chat_data={})

    update = _update(telegram_id, text="remind me tomorrow at 9 to call mom")
    asyncio.run(on_text(update, context))
    assert "Which timezone" in _replies(update)[0]

    update = _update(telegram_id, text="Lisbon")
    asyncio.run(on_text(update, context))
    assert _replies(update)[0].startswith("🌍 Timezone set to Europe/Lisbon")
    assert _replies(update)[1].startswith("⏰ Got it: call mom")


def test_quiet_hours_custom(chat):
    from db.repositories.settings import SettingsRepository
    from db.repositories.user import UserRepository
    from core.settings import QUIET_HOURS
    from handlers.settings import on_quiet_button

    chat(data="qhopt:custom", handler=on_quiet_button)
    chat("22 to 8")
    user = UserRepository().get_by_telegram_id(chat.telegram_id)
    assert SettingsRepository().get(user.id, QUIET_HOURS) == ["22:00", "08:00"]


def test_timezone_keyboard_offers_lisbon_first():
    from handlers.settings import build_timezone_keyboard

    assert build_timezone_keyboard().inline_keyboard[0][0].text == "Europe/Lisbon"


# --- failed messages ----------------------------------------------------------

def _failed(telegram_id):
    """This user's open failed messages, oldest first."""
    from db.repositories.failed_message import FailedMessageRepository
    from db.repositories.user import UserRepository

    user_id = UserRepository().get_by_telegram_id(telegram_id).id
    return [f for f in reversed(FailedMessageRepository().list_open(10_000)) if f.user_id == user_id]


def test_not_understood_is_saved(chat):
    from handlers.text import HELP_TEXT

    update = chat("hello there")
    assert _replies(update) == [HELP_TEXT]
    [entry] = _failed(chat.telegram_id)
    assert (entry.text, entry.reason, entry.source, entry.intent) == ("hello there", "not_understood", "typed", None)


def test_unparsed_reminder_is_saved(chat):
    chat("remind me every 5 minutes to call mom")
    [entry] = _failed(chat.telegram_id)
    assert entry.text == "every 5 minutes to call mom"
    assert entry.intent == "reminder.create"
    assert entry.bot_understood == {"error": "The shortest repeat is every 15 minutes."}


# --- asking for the missing half ------------------------------------------------

def _local_when(chat):
    from core.timezones import to_local
    [reminder] = _active(chat.telegram_id)
    return reminder.text, to_local(reminder.remind_at, "Europe/Lisbon")


@pytest.mark.parametrize("request_", ["remind me to call mom", "remind to call mom", "remind me someday to call mom"])
def test_a_reminder_without_a_time_asks_when(chat, request_):
    update = chat(request_)
    text = "someday to call mom" if "someday" in request_ else "call mom"
    assert _replies(update)[0].startswith(f"⏰ When should I remind you: “{text}”?")
    assert _active(chat.telegram_id) == [] and _failed(chat.telegram_id) == []

    update = chat("tomorrow at 9")
    assert _replies(update)[0].startswith(f"⏰ Got it: {text}")
    text_, when = _local_when(chat)
    assert (when.hour, when.minute) == (9, 0)
    assert _active(chat.telegram_id)[0].request == f"tomorrow at 9 to {text}"


def test_asking_when_again_if_the_answer_isnt_a_time(chat):
    chat("remind me to call mom")
    update = chat("whenever")
    assert _replies(update)[0].startswith("I couldn't understand when. ⏰ When should I remind you: “call mom”?")
    [entry] = _failed(chat.telegram_id)
    assert (entry.text, entry.intent) == ("whenever", "reminder.when")

    update = chat("in 2 hours")
    assert _replies(update)[0].startswith("⏰ Got it: call mom")


@pytest.mark.parametrize("request_", ["remind me tomorrow at 12", "tomorrow at 12", "Tomorrow at 12"])
def test_a_time_without_a_text_asks_what_for(chat, request_):
    update = chat(request_)
    assert _replies(update)[0] == f"⏰ {request_.removeprefix('remind me ')}: what should I remind you about?"
    assert _failed(chat.telegram_id) == []

    update = chat("call the bank")
    assert _replies(update)[0].startswith("⏰ Got it: call the bank")
    text, when = _local_when(chat)
    assert (when.hour, when.minute) == (12, 0)


def test_answer_with_its_own_to(chat):
    chat("tomorrow at 12")
    chat("to call the bank")
    assert _local_when(chat)[0] == "call the bank"


def test_a_repeat_without_a_text(chat):
    chat("remind me every day at 9")
    chat("take pills")
    [reminder] = _active(chat.telegram_id)
    assert (reminder.text, reminder.recurrence) == ("take pills", "mon,tue,wed,thu,fri,sat,sun@09:00")


def test_a_trigger_phrase_wins_over_the_question(chat):
    chat("remind me to call mom")
    chat("remind me in 1 hour to stretch")
    assert _local_when(chat)[0] == "stretch"
    # The question is over: a plain message isn't its answer any more.
    update = chat("tomorrow at 9")
    assert _replies(update)[0] == "⏰ tomorrow at 9: what should I remind you about?"


def test_thats_wrong_while_asking_saves_the_asked_message(chat):
    chat("remind me tomorrow at 9 to call mom")
    chat("remind me to stretch")
    update = chat("that's wrong")
    assert _replies(update)[0].startswith("👎 Saved as failed")
    [entry] = _failed(chat.telegram_id)
    assert (entry.text, entry.bot_understood) == ("to stretch", {"error": "asked for the missing time or text"})
    assert len(_active(chat.telegram_id)) == 1      # the earlier reminder is untouched
    # Asked about once: saying it again doesn't save it twice.
    assert _replies(chat("that's wrong"))[0] == "👎 That one is already saved as failed."


def test_a_failed_message_ends_the_question(chat):
    chat("remind me tomorrow at 9 to call mom")
    from handlers.reminders import on_new

    chat("tomorrow at 12")                      # the bot asks what for
    chat(data="rem:new", handler=on_new)        # ➕ New instead
    chat("every 5 minutes to stretch")          # fails: too short a repeat
    [entry] = _failed(chat.telegram_id)
    assert entry.text == "every 5 minutes to stretch"
    # "that's wrong" now means that failed message (already saved), not the old question.
    assert _replies(chat("that's wrong"))[0] == "👎 That one is already saved as failed."
    assert len(_failed(chat.telegram_id)) == 1


def test_a_button_ends_the_question(chat):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    reminder_id = _active(chat.telegram_id)[0].id
    chat("remind me to stretch")                # the bot asks when
    chat(data=f"rem:edit:{reminder_id}", handler=on_reminder_button)    # ✏️ Edit instead
    update = chat("that's wrong")               # about the reminder, not the question
    assert _replies(update)[0].startswith("👎 Deleted: call mom")
    assert [e.reason for e in _failed(chat.telegram_id)] == ["wrong_result"]


def test_settings_end_the_question(chat):
    from handlers.settings import on_timezone_settings

    chat("remind me tomorrow at 9 to call mom")
    chat("remind me to stretch")                # the bot asks when
    chat(data="settings:timezone", handler=on_timezone_settings)
    chat("Berlin")                              # answers the timezone question instead
    update = chat("that's wrong")               # about the reminder, not the question
    assert _replies(update)[0].startswith("👎 Deleted: call mom")
    assert [e.reason for e in _failed(chat.telegram_id)] == ["wrong_result"]


def test_an_abandoned_question_is_forgotten(chat):
    chat("remind me tomorrow at 9 to call mom")
    chat("remind me to stretch")
    chat("my reminders")                        # moves on without answering
    update = chat("that's wrong")               # about the reminder, not the question
    assert _replies(update)[0].startswith("👎 Deleted: call mom")
    [entry] = _failed(chat.telegram_id)
    assert entry.reason == "wrong_result"


def test_wrong_button_saves_then_deletes(chat):
    from handlers.reminders import on_reminder_button
    from handlers.ui import AWAITING

    chat("remind me on friday at 9 to call mom")
    reminder = _active(chat.telegram_id)[0]

    update = chat(data=f"rem:wrong:{reminder.id}", handler=on_reminder_button)
    # The confirmation is replaced (its buttons go away), nothing is asked
    assert update.callback_query.edit_message_text.call_args.args[0].startswith("👎 Deleted: call mom\n")
    update.callback_query.message.reply_text.assert_not_called()
    assert AWAITING not in chat.context.user_data
    assert _active(chat.telegram_id) == []

    [entry] = _failed(chat.telegram_id)
    assert (entry.text, entry.reason, entry.source) == ("on friday at 9 to call mom", "wrong_result", "typed")
    assert entry.reminder_id == reminder.id
    assert entry.bot_understood == {
        "text": "call mom", "remind_at": reminder.remind_at.isoformat(), "recurrence": None,
    }

    # Pressing it again doesn't save it twice
    update = chat(data=f"rem:wrong:{reminder.id}", handler=on_reminder_button)
    assert "had already finished" in update.callback_query.edit_message_text.call_args.args[0]
    assert len(_failed(chat.telegram_id)) == 1


def test_wrong_button_on_a_finished_reminder(chat):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    reminder_id = _active(chat.telegram_id)[0].id
    chat(data=f"rem:ok:{reminder_id}", handler=on_reminder_button)

    update = chat(data=f"rem:wrong:{reminder_id}", handler=on_reminder_button)
    assert "had already finished" in update.callback_query.edit_message_text.call_args.args[0]
    assert len(_failed(chat.telegram_id)) == 1


def test_wrong_button_on_a_firing_reminder_retires_its_message(chat):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    reminder_id = _active(chat.telegram_id)[0].id
    _fire(reminder_id)
    chat(data=f"rem:wrong:{reminder_id}", handler=on_reminder_button)
    assert chat.context.bot.edit_message_text.call_args.kwargs["text"] == "⏰ call mom\n\n↩️ Cancelled."


def test_thats_wrong_deletes_the_last_reminder(chat):
    chat("remind me tomorrow at 9 to call mom")
    chat("remind me tomorrow at 10 to pay rent")
    update = chat("that's wrong")
    assert _replies(update)[0].startswith("👎 Deleted: pay rent\n")
    assert [r.text for r in _active(chat.telegram_id)] == ["call mom"]
    [entry] = _failed(chat.telegram_id)
    assert entry.text == "tomorrow at 10 to pay rent"

    # Saying it again doesn't delete the one before
    update = chat("that's wrong")
    assert _replies(update) == ["👎 That one is already saved as failed."]
    assert [r.text for r in _active(chat.telegram_id)] == ["call mom"]


def test_thats_wrong_after_a_message_that_was_not_understood(chat):
    chat("blah blah")
    update = chat("save the last one as failed")
    assert "already saved" in _replies(update)[0]
    assert len(_failed(chat.telegram_id)) == 1


def test_save_the_last_one_after_a_restart(chat):
    chat("remind me tomorrow at 9 to call mom")
    chat.context.user_data.clear()      # a restart forgets user_data
    chat("Save the last one as failed")
    [entry] = _failed(chat.telegram_id)
    assert entry.text == "tomorrow at 9 to call mom"


def test_thats_wrong_without_reminders(chat):
    update = chat("that's wrong")
    assert _replies(update) == ["There's no reminder to save as failed yet."]


def test_failed_list_is_admin_only(chat, monkeypatch):
    import config
    from handlers.failed import on_failed_button, on_failed_cmd
    from handlers.reminders import on_reminder_button

    chat("remind me on friday at 9 to water the plants")
    reminder_id = _active(chat.telegram_id)[0].id
    chat(data=f"rem:wrong:{reminder_id}", handler=on_reminder_button)
    [entry] = _failed(chat.telegram_id)

    monkeypatch.setattr(config, "ADMIN_TELEGRAM_ID", None)
    assert _replies(chat("/failed", handler=on_failed_cmd)) == []
    monkeypatch.setattr(config, "ADMIN_TELEGRAM_ID", chat.telegram_id + 1)
    assert _replies(chat("/failed", handler=on_failed_cmd)) == []
    update = chat(data=f"failfix:{entry.id}", handler=on_failed_button)
    assert update.callback_query.answer.call_args.kwargs == {"show_alert": True}
    assert len(_failed(chat.telegram_id)) == 1

    monkeypatch.setattr(config, "ADMIN_TELEGRAM_ID", chat.telegram_id)
    text = _replies(chat("/failed", handler=on_failed_cmd))[0]
    assert "⌨️ “on friday at 9 to water the plants”" in text
    assert "👎 Wrong: Fri " in text and ", 09:00 · “water the plants”" in text

    update = chat(data=f"failfix:{entry.id}", handler=on_failed_button)
    assert _failed(chat.telegram_id) == []
    assert "water the plants" not in update.callback_query.edit_message_text.call_args.args[0]


def test_failed_list_ignore_button_and_fix_pr(chat, monkeypatch):
    import config
    from db.repositories.failed_message import FailedMessageRepository
    from handlers.failed import build_failed_keyboard, on_failed_button, on_failed_cmd

    monkeypatch.setattr(config, "ADMIN_TELEGRAM_ID", chat.telegram_id)
    chat("ignore me please, unique 7781")
    [entry] = _failed(chat.telegram_id)
    FailedMessageRepository().set_fix_pr(entry.id, 41)

    text = _replies(chat("/failed", handler=on_failed_cmd))[0]
    assert "🔧 Fix waiting in pull request #41" in text
    assert _buttons(build_failed_keyboard([entry])) == [
        [("✅ 1", f"failfix:{entry.id}")], [("🗑 1", f"failign:{entry.id}")],
    ]

    FailedMessageRepository().set_fix_pr(entry.id, None)
    FailedMessageRepository().set_waiting(entry.id, "asking when")
    assert "⏳ Waiting for: asking when" in _replies(chat("/failed", handler=on_failed_cmd))[0]

    update = chat(data=f"failign:{entry.id}", handler=on_failed_button)
    assert update.callback_query.answer.call_args.args == ("Ignored",)
    assert _failed(chat.telegram_id) == []
    closed = FailedMessageRepository().get(entry.id)
    assert (closed.status, closed.note) == ("ignored", "ignored with 🗑 on /failed")


# --- menus --------------------------------------------------------------------

def test_start_registers_and_shows_the_menu(chat):
    from db.repositories.user import UserRepository
    from handlers.commands import start

    new_id = chat.telegram_id + 1
    update = _update(new_id, text="/start")
    asyncio.run(start(update, chat.context))
    assert UserRepository().get_by_telegram_id(new_id) is not None
    text, keyboard = chat.screen()
    assert text.startswith("Hi!")
    assert _buttons(keyboard) == [[("⏰ Reminders", "menu:reminders")], [("⚙️ Settings", "menu:settings")]]


@pytest.mark.parametrize("handler, data, text, back", [
    ("on_reminders",  "menu:reminders", "Reminders:", ("↩️ Back", "menu:main")),
    ("on_settings",   "menu:settings",  "Settings:",  ("↩️ Back", "settings:back")),
    ("on_main_menu",  "menu:main",      "Menu:",      ("⚙️ Settings", "menu:settings")),
    ("on_main_menu",  "settings:back",  "Menu:",      ("⚙️ Settings", "menu:settings")),
])
def test_menu_screens(chat, handler, data, text, back):
    from handlers import menus

    chat(data=data, handler=getattr(menus, handler))
    screen_text, keyboard = chat.screen()
    assert screen_text.startswith(text)
    assert _buttons(keyboard)[-1] == [back]


def test_menu_command_and_my_id(chat):
    from handlers.commands import menu_cmd
    from handlers.menus import on_my_id

    chat("/menu", handler=menu_cmd)
    assert chat.screen()[0] == "Menu:"
    chat(data="settings:my_id", handler=on_my_id)
    assert chat.screen()[0] == f"Your ID: {chat.telegram_id}"


# --- settings screens ---------------------------------------------------------

def _setting(chat, setting):
    from db.repositories.settings import SettingsRepository
    from db.repositories.user import UserRepository

    return SettingsRepository().get(UserRepository().get_by_telegram_id(chat.telegram_id).id, setting)


def test_snooze_presets_default_and_custom(chat):
    from core.settings import SNOOZE_OPTIONS
    from enums import Awaiting
    from handlers.settings import on_snooze_button, on_snooze_settings
    from handlers.ui import AWAITING

    chat(data="settings:snooze", handler=on_snooze_settings)
    assert "Current: 10 min · 1 h" in chat.screen()[0]

    update = chat(data="snzopt:set:5,15,60", handler=on_snooze_button)
    assert update.callback_query.answer.call_args.args == ("Saved",)
    assert _setting(chat, SNOOZE_OPTIONS) == [5, 15, 60]
    assert _buttons(chat.screen()[1])[0] == [("✅ 5 min · 15 min · 1 h", "snzopt:set:5,15,60")]

    chat(data="snzopt:default", handler=on_snooze_button)
    assert _setting(chat, SNOOZE_OPTIONS) == [10, 60]

    chat(data="snzopt:custom", handler=on_snooze_button)
    assert chat.context.user_data[AWAITING] == Awaiting.SNOOZE_OPTIONS
    update = chat("soon")
    assert "Try again" in _replies(update)[0]
    assert chat.context.user_data[AWAITING] == Awaiting.SNOOZE_OPTIONS
    update = chat("10m, 1h, 3h")
    assert _replies(update) == ["💤 Snooze options set to 10 min · 1 h · 3 h."]
    assert _setting(chat, SNOOZE_OPTIONS) == [10, 60, 180]
    assert AWAITING not in chat.context.user_data


def test_snooze_button_with_invalid_data_is_refused(chat):
    from core.settings import SNOOZE_OPTIONS
    from handlers.settings import on_snooze_button

    # Callback data comes from the client, so it can be anything.
    update = chat(data="snzopt:set:0", handler=on_snooze_button)
    assert update.callback_query.answer.call_args.kwargs == {"show_alert": True}
    assert _setting(chat, SNOOZE_OPTIONS) == [10, 60]


def test_repeat_interval(chat):
    from core.settings import REPEAT_MINUTES
    from handlers.settings import on_repeat_button, on_repeat_settings

    chat(data="settings:repeat", handler=on_repeat_settings)
    assert "Current: every 5 min" in chat.screen()[0]

    chat(data="rptopt:set:15", handler=on_repeat_button)
    assert _setting(chat, REPEAT_MINUTES) == 15
    assert ("✅ 15 min", "rptopt:set:15") in _buttons(chat.screen()[1])[1]

    update = chat(data="rptopt:set:999", handler=on_repeat_button)
    assert update.callback_query.answer.call_args.kwargs == {"show_alert": True}
    assert _setting(chat, REPEAT_MINUTES) == 15


def test_quiet_hours_presets_off_default(chat):
    from core.settings import QUIET_HOURS
    from handlers.settings import on_quiet_button, on_quiet_settings

    chat(data="settings:quiet", handler=on_quiet_settings)
    assert "Current: 00:00–07:00" in chat.screen()[0]

    chat(data="qhopt:set:23:00-07:00", handler=on_quiet_button)
    assert _setting(chat, QUIET_HOURS) == ["23:00", "07:00"]

    chat(data="qhopt:off", handler=on_quiet_button)
    assert _setting(chat, QUIET_HOURS) == []
    assert ("✅ 🔔 Off", "qhopt:off") in _buttons(chat.screen()[1])[3]

    chat(data="qhopt:default", handler=on_quiet_button)
    assert _setting(chat, QUIET_HOURS) == ["00:00", "07:00"]


def test_quiet_hours_custom_invalid_asks_again(chat):
    from enums import Awaiting
    from handlers.settings import on_quiet_button
    from handlers.ui import AWAITING

    chat(data="qhopt:custom", handler=on_quiet_button)
    update = chat("whenever")
    assert "Try again" in _replies(update)[0]
    assert chat.context.user_data[AWAITING] == Awaiting.QUIET_HOURS


def test_timezone_settings(chat):
    from db.repositories.user import UserRepository
    from handlers.settings import on_timezone_button, on_timezone_settings

    update = chat(data="settings:timezone", handler=on_timezone_settings)
    assert _replies(update)[0].startswith("Current timezone: Europe/Lisbon. Which timezone")

    update = chat("Atlantis")
    assert _replies(update)[0].startswith("I don't know that timezone")
    update = chat("kyiv")
    assert _replies(update)[0].startswith("🌍 Timezone set to Europe/Kyiv")

    chat(data="tz:Europe/Berlin", handler=on_timezone_button)
    assert UserRepository().get_by_telegram_id(chat.telegram_id).timezone == "Europe/Berlin"


# --- reminders that are firing ------------------------------------------------

def _fire(reminder_id, message_id=555):
    """Mark a reminder as delivered and waiting for OK, like the delivery job does."""
    from datetime import timedelta

    from db.models.reminder import utcnow
    from db.repositories.reminder import ReminderRepository

    ReminderRepository().mark_fired(reminder_id, message_id, utcnow() + timedelta(minutes=5))


@pytest.mark.parametrize("action, note", [
    ("edit", "✏️ Edited, see the updated reminder below."),
    ("del",  "↩️ Cancelled."),
    ("undo", "↩️ Cancelled."),
])
def test_firing_reminder_loses_its_buttons_when_changed(chat, action, note):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    reminder_id = _active(chat.telegram_id)[0].id
    _fire(reminder_id)

    chat(data=f"rem:{action}:{reminder_id}", handler=on_reminder_button)
    if action == "edit":
        chat("tomorrow at 10 to call dad")
    kwargs = chat.context.bot.edit_message_text.call_args.kwargs
    assert (kwargs["message_id"], kwargs["text"]) == (555, f"⏰ call mom\n\n{note}")


def test_pending_reminder_has_no_message_to_retire(chat):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    reminder_id = _active(chat.telegram_id)[0].id
    chat(data=f"rem:del:{reminder_id}", handler=on_reminder_button)
    chat.context.bot.edit_message_text.assert_not_called()


# --- changing the timezone ----------------------------------------------------

def _local(when, tz_name):
    from zoneinfo import ZoneInfo
    return when.astimezone(ZoneInfo(tz_name))


def test_timezone_change_keeps_the_clock_time_of_daily_reminders(chat):
    from handlers.settings import on_timezone_button

    chat("remind me every day at 9 to take pills")
    chat("remind me on the 1st of every month at 10 to pay rent")
    chat(data="tz:Europe/Kyiv", handler=on_timezone_button)

    by_text = {r.text: r for r in _active(chat.telegram_id)}
    assert _local(by_text["take pills"].remind_at, "Europe/Kyiv").time().isoformat() == "09:00:00"
    assert _local(by_text["pay rent"].remind_at, "Europe/Kyiv").time().isoformat() == "10:00:00"
    assert by_text["take pills"].next_fire_at == by_text["take pills"].remind_at


def test_timezone_change_keeps_the_moment_of_one_offs_and_intervals(chat):
    from handlers.settings import on_timezone_button

    chat("remind me tomorrow at 9 to call mom")
    chat("remind me every 2 hours to drink water")
    before = {r.text: r.remind_at for r in _active(chat.telegram_id)}
    chat(data="tz:Europe/Kyiv", handler=on_timezone_button)
    assert {r.text: r.remind_at for r in _active(chat.telegram_id)} == before


def test_timezone_change_keeps_a_snooze(chat):
    from handlers.reminders import on_reminder_button
    from handlers.settings import on_timezone_button

    chat("remind me every day at 9 to take pills")
    reminder_id = _active(chat.telegram_id)[0].id
    _fire(reminder_id)
    chat(data=f"rem:snz:{reminder_id}:15", handler=on_reminder_button)
    snoozed_until = _active(chat.telegram_id)[0].remind_at

    chat(data="tz:Europe/Kyiv", handler=on_timezone_button)
    assert _active(chat.telegram_id)[0].remind_at == snoozed_until


# --- typos ----------------------------------------------------------------------

def test_typos_in_the_trigger_and_the_time(chat):
    update = chat("remid me on wensday at 18:00 to call mom")
    assert _replies(update)[0].startswith("⏰ Got it: call mom\n🗓 Wed ")
    reminder = _active(chat.telegram_id)[0]
    assert reminder.request == "on wensday at 18:00 to call mom"     # saved as typed


# --- plain-language commands ------------------------------------------------------

def _texts(chat):
    return sorted(r.text for r in _active(chat.telegram_id))


def test_cancel_by_name(chat):
    chat("remind me tomorrow at 9 to call the dentist")
    chat("remind me tomorrow at 10 to call mom")
    update = chat("cancel the dentist reminder")
    assert _replies(update) == ["↩️ Cancelled: call the dentist"]
    assert _texts(chat) == ["call mom"]


def test_cancel_asks_which_one(chat):
    chat("remind me tomorrow at 9 to call the dentist")
    chat("remind me tomorrow at 10 to call mom")
    update = chat("delete my reminder to call")
    assert _replies(update)[0].startswith("Which one? Your reminders (tap ❌ to cancel):")
    keyboard = update.effective_message.reply_text.call_args.kwargs["reply_markup"]
    assert len(_buttons(keyboard)) == 3            # two reminders, then ➕ New / ↩️ Back
    assert len(_texts(chat)) == 2


def test_cancel_without_a_match(chat):
    chat("remind me tomorrow at 9 to call mom")
    assert _replies(chat("cancel the gym reminder"))[0].startswith("No reminder matches “gym”.")
    assert _texts(chat) == ["call mom"]


def test_delete_as_the_answer_to_a_question_is_the_answer(chat):
    chat("tomorrow at 12")                         # the bot asks what for
    update = chat("delete old photos")
    assert _replies(update)[0].startswith("⏰ Got it: delete old photos")


def test_what_do_i_have_tomorrow(chat):
    chat("remind me tomorrow at 9 to call mom")
    chat("remind me every day at 8 to take pills")
    chat("remind me in 3 days to pay rent")
    update = chat("what do I have tomorrow?")
    text = _replies(update)[0]
    assert text.startswith("Your reminders on ")
    assert "call mom" in text and "take pills" in text and "pay rent" not in text


def test_nothing_on_that_day(chat):
    chat("remind me tomorrow at 9 to call mom")
    assert _replies(chat("my reminders on dec 25"))[0].startswith("Nothing on ")


def test_agenda_needs_a_day(chat):
    assert _replies(chat("what's on my mind"))[0].startswith("I can show one day")


def test_set_timezone_by_text(chat):
    from db.repositories.user import UserRepository

    update = chat("set my timezone to Berlin")
    assert _replies(update)[0].startswith("🌍 Timezone set to Europe/Berlin")
    assert UserRepository().get_by_telegram_id(chat.telegram_id).timezone == "Europe/Berlin"
    assert "I don't know that timezone" in _replies(chat("set my timezone to Atlantis"))[0]
    assert _replies(chat("change my timezone"))[0].startswith("Which timezone are you in?")
