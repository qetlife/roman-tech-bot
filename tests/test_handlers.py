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
    """A new user with a timezone, and a function to send them messages/buttons."""
    from db.repositories.user import UserRepository
    from handlers import reminders, settings
    from handlers.text import on_text

    monkeypatch.setattr(reminders, "render_menu", AsyncMock())
    monkeypatch.setattr(settings, "render_menu", AsyncMock())

    telegram_id = random.randint(10**9, 10**12)
    UserRepository().get_or_create(telegram_id)
    UserRepository().set_timezone(telegram_id, "Europe/Lisbon")
    context = MagicMock(user_data={}, chat_data={})

    def send(text=None, data=None, handler=None):
        update = _update(telegram_id, data=data, text=text)
        asyncio.run((handler or on_text)(update, context))
        return update

    send.telegram_id = telegram_id
    send.context = context
    return send


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
    chat("remind me someday to call mom")
    [entry] = _failed(chat.telegram_id)
    assert entry.text == "someday to call mom"
    assert entry.intent == "reminder.create"
    assert entry.bot_understood == {"error": "I couldn't understand when."}


def test_wrong_button_saves_then_edits(chat):
    from enums import Awaiting
    from handlers.reminders import on_reminder_button
    from handlers.ui import AWAITING

    chat("remind me on friday at 9 to call mom")
    reminder = _active(chat.telegram_id)[0]

    update = chat(data=f"rem:wrong:{reminder.id}", handler=on_reminder_button)
    assert "Saved as failed" in update.callback_query.message.reply_text.call_args.args[0]
    assert chat.context.user_data[AWAITING] == Awaiting.EDIT

    [entry] = _failed(chat.telegram_id)
    assert (entry.text, entry.reason, entry.source) == ("on friday at 9 to call mom", "wrong_result", "typed")
    assert entry.reminder_id == reminder.id
    assert entry.bot_understood == {
        "text": "call mom", "remind_at": reminder.remind_at.isoformat(), "recurrence": None,
    }

    # Fixing it with ✏️ Edit keeps what the bot got wrong
    chat("tomorrow at 10 to call dad")
    assert _active(chat.telegram_id)[0].text == "call dad"
    assert _failed(chat.telegram_id)[0].bot_understood["text"] == "call mom"

    # Pressing it again doesn't save it twice
    chat(data=f"rem:wrong:{reminder.id}", handler=on_reminder_button)
    assert len(_failed(chat.telegram_id)) == 1


def test_wrong_button_on_a_finished_reminder(chat):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    reminder_id = _active(chat.telegram_id)[0].id
    chat(data=f"rem:ok:{reminder_id}", handler=on_reminder_button)

    update = chat(data=f"rem:wrong:{reminder_id}", handler=on_reminder_button)
    assert "already finished" in update.callback_query.message.reply_text.call_args.args[0]
    assert len(_failed(chat.telegram_id)) == 1


def test_thats_wrong_flags_the_last_reminder(chat):
    from enums import Awaiting
    from handlers.ui import AWAITING

    chat("remind me tomorrow at 9 to call mom")
    chat("remind me tomorrow at 10 to pay rent")
    update = chat("that's wrong")
    assert _replies(update)[0].startswith("👎 Saved as failed")
    assert chat.context.user_data[AWAITING] == Awaiting.EDIT
    [entry] = _failed(chat.telegram_id)
    assert entry.text == "tomorrow at 10 to pay rent"


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
