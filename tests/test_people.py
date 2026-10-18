"""👥 People: invites, requests by @username, renaming and removing (handlers/people.py)."""

import asyncio
import random

from datetime       import timedelta
from unittest.mock  import AsyncMock, MagicMock

import pytest

from tests.test_handlers import _buttons, _replies, _update


@pytest.fixture
def person(db, monkeypatch):
    """make(first name, @username): someone who uses the bot, and a function to send as them."""
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


def _invite(roman):
    """Roman taps 👥 → ➕ Invite: the token in the link."""
    from handlers.people import on_new_invite
    roman(data="people:invite", handler=on_new_invite)
    text, _ = roman.screen()
    link = next(w for w in text.split() if w.startswith("https://t.me/testbot?start=inv_"))
    return link.removeprefix("https://t.me/testbot?start=inv_")


def _open_invite(anna, token):
    from handlers.commands import start
    update = anna("/start", handler=start, args=[f"inv_{token}"])
    return _replies(update)[0], update.effective_message.reply_text.call_args.kwargs.get("reply_markup")


def _tap(someone, data):
    from handlers.people import on_invite_button, on_people_button
    handler = on_invite_button if data.startswith("inv:") else on_people_button
    update = someone(data=data, handler=handler)
    edited = update.callback_query.edit_message_text.call_args
    return edited.args[0] if edited else None


def _people(owner):
    from db.repositories.contact import ContactRepository
    return [(c.name, c.status) for c, _ in ContactRepository().people_of(owner.user().id)]


def _senders(contact):
    from db.repositories.contact import ContactRepository
    return [u.first_name for _, u in ContactRepository().senders_of(contact.user().id)]


# --- invite links ---------------------------------------------------------------

def test_invite_link_allow(person):
    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    token = _invite(roman)

    text, keyboard = _open_invite(anna, token)
    assert text.startswith("👥 Roman (@roman_i) wants to send you reminders.")
    assert _buttons(keyboard) == [[("✅ Allow", f"inv:yes:{token}"), ("❌ No", f"inv:no:{token}")]]
    assert _people(roman) == []                     # nothing until she says yes

    assert _tap(anna, f"inv:yes:{token}").startswith("✅ Roman (@roman_i) can now send you reminders.")
    assert _people(roman) == [("Anna", "accepted")]
    assert _senders(anna) == ["Roman"]
    assert roman.told() == ["✅ Anna (@anna) accepted your invite. They're in 👥 People as “Anna”."]


def test_invite_link_works_once(person):
    roman, anna, ben = person("Roman", "roman_i"), person("Anna", "anna"), person("Ben", None)
    token = _invite(roman)
    _tap(anna, f"inv:yes:{token}")
    assert _open_invite(ben, token)[0].startswith("This invite link has already been used")
    assert _tap(ben, f"inv:yes:{token}").startswith("This invite link has already been used")
    assert _people(roman) == [("Anna", "accepted")]


def test_own_invite_link(person):
    roman = person("Roman", "roman_i")
    token = _invite(roman)
    assert _open_invite(roman, token)[0].startswith("That's your own invite link")


def test_expired_invite_link(person):
    from db.models.contact import Invite
    from db.models.reminder import utcnow
    from db.session import SessionLocal

    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    token = _invite(roman)
    with SessionLocal() as session:
        session.get(Invite, token).expires_at = utcnow() - timedelta(minutes=1)
        session.commit()
    assert _tap(anna, f"inv:yes:{token}") == "This invite link has expired. Ask for a new one."
    assert _people(roman) == []


def test_declined_invite_link_is_dead(person):
    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    token = _invite(roman)
    assert _tap(anna, f"inv:no:{token}").startswith("OK, not connected.")
    assert roman.told() == ["Anna (@anna) declined your invite."]
    assert _tap(anna, f"inv:yes:{token}").startswith("This invite link has already been used")
    assert _people(roman) == []


def test_two_contacts_with_the_same_name(person):
    roman, anna1, anna2 = person("Roman", "roman_i"), person("Anna", "anna"), person("Anna", "anna_b")
    _tap(anna1, f"inv:yes:{_invite(roman)}")
    _tap(anna2, f"inv:yes:{_invite(roman)}")
    assert _people(roman) == [("Anna", "accepted"), ("Anna 2", "accepted")]


# --- requests by @username -------------------------------------------------------

def test_request_by_username(person):
    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    _invite(roman)                                  # ➕ Invite also asks for an @username
    assert _replies(roman("@Anna"))[0] == "📨 Asked @anna. I'll tell you when they answer."
    assert _people(roman) == [("Anna", "pending")]

    [request] = anna.messages()
    [[allow, _]] = _buttons(request.kwargs["reply_markup"])
    assert _tap(anna, allow[1]).startswith("✅ Roman (@roman_i) can now send you reminders.")
    assert _people(roman) == [("Anna", "accepted")]
    assert roman.told() == ["✅ Anna (@anna) accepted. They're in 👥 People as “Anna”."]


def test_request_declined(person):
    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    _invite(roman)
    roman("anna")
    [request] = anna.messages()
    [[_, decline]] = _buttons(request.kwargs["reply_markup"])
    _tap(anna, decline[1])
    assert _people(roman) == []
    assert roman.told() == ["Anna (@anna) declined your request."]


@pytest.mark.parametrize("text, reply", [
    ("@nobody_here", "I don't know @nobody_here: they haven't used this bot yet."),
    ("@roman_i", "That's you."),
])
def test_request_by_unknown_or_own_username(person, text, reply):
    roman = person("Roman", "roman_i")
    _invite(roman)
    assert _replies(roman(text))[0].startswith(reply)


def test_request_twice(person):
    roman, _ = person("Roman", "roman_i"), person("Anna", "anna")
    _invite(roman)
    roman("@anna")
    _invite(roman)
    assert "already in your 👥 People" in _replies(roman("@anna"))[0]


# --- the 👥 People screen, renaming, removing ------------------------------------------

def _connected(person):
    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    _tap(anna, f"inv:yes:{_invite(roman)}")
    from db.repositories.contact import ContactRepository
    [(contact, _)] = ContactRepository().people_of(roman.user().id)
    return roman, anna, contact


def test_people_screen(person):
    from handlers.people import on_people_menu

    roman, anna, contact = _connected(person)
    roman(data="menu:people", handler=on_people_menu)
    text, keyboard = roman.screen()
    assert text == "👥 People\n\nYou can remind:\n• Anna (@anna)"
    assert _buttons(keyboard)[0] == [("👤 Anna", f"ppl:open:{contact.id}")]

    anna(data="menu:people", handler=on_people_menu)
    text, keyboard = anna.screen()
    assert text.endswith("Can remind you:\n• Roman (@roman_i)")
    assert ("📨 Roman (@roman_i)", f"ppl:sender:{contact.id}") in [b for row in _buttons(keyboard) for b in row]


def test_rename(person):
    roman, anna, contact = _connected(person)
    _tap(roman, f"ppl:ren:{contact.id}")
    assert _replies(roman("Mom"))[0] == "✏️ Renamed to Mom."
    assert _people(roman) == [("Mom", "accepted")]


@pytest.mark.parametrize("name, reply", [("me", "Use a name"), ("9lives", "Use a name")])
def test_rename_invalid(person, name, reply):
    roman, anna, contact = _connected(person)
    _tap(roman, f"ppl:ren:{contact.id}")
    assert _replies(roman(name))[0].startswith(reply)
    assert _people(roman) == [("Anna", "accepted")]


def test_rename_to_a_taken_name(person):
    roman, anna, contact = _connected(person)
    ben = person("Ben", "ben")
    _tap(ben, f"inv:yes:{_invite(roman)}")
    _tap(roman, f"ppl:ren:{contact.id}")
    assert _replies(roman("ben"))[0] == "You already have someone called “ben”. Pick another name."


def _reminder_for(owner, contact_person):
    from db.models.reminder import utcnow
    from db.repositories.reminder import ReminderRepository
    from enums import MessageSource

    repo = ReminderRepository()
    reminder = repo.create(owner.user(), contact_person.telegram_id, "bring the ball",
                           utcnow() + timedelta(hours=1), None, "…", MessageSource.TYPED)
    # Reminders for others come in the next step; for now set the target by hand.
    from db.models.reminder import Reminder
    from db.session import SessionLocal
    with SessionLocal() as session:
        session.get(Reminder, reminder.id).target_user_id = contact_person.user().id
        session.commit()
    return reminder.id


def _status(reminder_id):
    from db.models.reminder import Reminder
    from db.session import SessionLocal
    with SessionLocal() as session:
        return session.get(Reminder, reminder_id).status


def test_owner_removes_a_contact(person):
    roman, anna, contact = _connected(person)
    reminder_id = _reminder_for(roman, anna)
    _tap(roman, f"ppl:del:{contact.id}")
    assert _people(roman) == [] and _senders(anna) == []
    assert _status(reminder_id) == "cancelled"
    assert anna.told() == []                        # not told


def test_contact_stops_a_sender(person):
    roman, anna, contact = _connected(person)
    reminder_id = _reminder_for(roman, anna)
    _tap(anna, f"ppl:stop:{contact.id}")
    assert _people(roman) == []
    assert _status(reminder_id) == "cancelled"
    assert roman.told()[-1] == "🚫 Anna stopped your reminders. Ones you'd set for them are cancelled."


def test_someone_else_cant_touch_a_contact(person):
    from handlers.people import on_people_button

    roman, anna, contact = _connected(person)
    eve = person("Eve", "eve")
    update = eve(data=f"ppl:del:{contact.id}", handler=on_people_button)
    assert update.callback_query.answer.call_args.args == ("That's gone.",)
    assert _people(roman) == [("Anna", "accepted")]
    # The contact can't rename or remove from the owner's side either
    _tap(anna, f"ppl:del:{contact.id}")
    assert _people(roman) == [("Anna", "accepted")]


def test_profile_is_remembered(person):
    from db.repositories.user import UserRepository

    roman = person("Roman", "Roman_I")
    assert (roman.user().first_name, roman.user().username) == ("Roman", "roman_i")
    UserRepository().remember_profile(roman.telegram_id, "Ro", None)
    assert (roman.user().first_name, roman.user().username) == ("Ro", None)
