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
