import os
import tempfile

# Tests always use a throwaway SQLite database, never the one in .env or the
# environment. Must run before anything imports db.session.
_tmpdir = tempfile.mkdtemp(prefix="roman-tech-bot-tests-")
os.environ["DB_CONNECTION"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def db():
    """Database with all migrations applied."""
    from db.session import init_db
    init_db()


@pytest.fixture
def user(db):
    """A fresh user for each test."""
    import random

    from db.repositories.user import UserRepository
    return UserRepository().get_or_create(random.randint(10**9, 10**12))


@pytest.fixture
def person(db, monkeypatch):
    """make(first name, @username): someone who uses the bot, and a function to send as them.

    Everyone shares one bot; `told()` is what it sent to that person from elsewhere.
    """
    import asyncio
    import random

    from unittest.mock import AsyncMock, MagicMock

    from db.repositories.user import UserRepository
    from handlers import commands, people

    from sqlalchemy import update as sql_update
    from db.models.user import User
    from db.session import SessionLocal

    render = AsyncMock()
    for module in (commands, people):
        monkeypatch.setattr(module, "render_menu", render)
    # One bot for everyone, as in real life: messages to others go through it.
    bot = MagicMock(username="testbot")
    bot.send_message = AsyncMock()

    def make(first_name, username):
        telegram_id = random.randint(10**9, 10**12)
        users = UserRepository()
        if username:
            # The tests share one database: this test's @username is this person's.
            with SessionLocal() as session:
                session.execute(sql_update(User).where(User.username == username.lower()).values(username=None))
                session.commit()
        users.get_or_create(telegram_id)
        users.remember_profile(telegram_id, first_name, username)
        users.set_timezone(telegram_id, "Europe/Lisbon")
        context = MagicMock(user_data={}, chat_data={}, args=[], bot=bot)

        def send(text=None, data=None, handler=None, args=None):
            from handlers.text import on_text
            from tests.test_handlers import _update
            update = _update(telegram_id, data=data, text=text)
            update.effective_user.first_name, update.effective_user.username = first_name, username
            context.args = args or []
            asyncio.run((handler or on_text)(update, context))
            return update

        send.telegram_id, send.context = telegram_id, context
        send.user = lambda: users.get_by_telegram_id(telegram_id)
        # What the bot sent to this person from elsewhere
        send.told = lambda: [c.kwargs["text"] for c in bot.send_message.call_args_list
                             if c.kwargs["chat_id"] == telegram_id]
        send.messages = lambda: [c for c in bot.send_message.call_args_list if c.kwargs["chat_id"] == telegram_id]
        send.screen = lambda: render.call_args.args[2:4]
        return send

    return make


@pytest.fixture
def chat(db, monkeypatch):
    """A new user with a timezone, and a function to send them messages/buttons.

    Menu screens aren't sent; `chat.screen()` is the last one rendered: (text, keyboard).
    """
    import asyncio
    import random

    from unittest.mock import AsyncMock, MagicMock

    from db.repositories.user import UserRepository
    from handlers import calendar, commands, events, menus, reminders, settings
    from handlers.text import on_text
    from tests.test_handlers import _update

    render = AsyncMock()
    for module in (calendar, commands, events, menus, reminders, settings):
        monkeypatch.setattr(module, "render_menu", render)

    telegram_id = random.randint(10**9, 10**12)
    UserRepository().get_or_create(telegram_id)
    UserRepository().set_timezone(telegram_id, "Europe/Lisbon")
    context = MagicMock(user_data={}, chat_data={}, args=[])
    context.bot.edit_message_text = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.username = "testbot"

    def send(text=None, data=None, handler=None, reply_to=None, message_id=None):
        update = _update(telegram_id, data=data, text=text, reply_to=reply_to)
        if message_id is not None:
            # The bot's message whose button was pressed
            update.callback_query.message.message_id = message_id
        asyncio.run((handler or on_text)(update, context))
        return update

    send.telegram_id = telegram_id
    send.context = context
    send.screen = lambda: render.call_args.args[2:4]
    return send
