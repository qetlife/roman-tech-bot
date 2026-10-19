"""👥 People: invites, requests by @username, renaming and removing (handlers/people.py)."""

from datetime       import timedelta

import pytest

from tests.test_handlers import _buttons, _replies


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

def test_a_stale_button_cant_undo_a_decline(person):
    from db.repositories.contact import ContactRepository

    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    _invite(roman)
    roman("@anna")
    [request] = anna.messages()
    [[_, decline]] = _buttons(request.kwargs["reply_markup"])
    contact_id = int(decline[1].rsplit(":", 1)[1])
    _tap(anna, decline[1])
    # Roman still has the "🗑 Cancel request" button open
    _tap(roman, f"ppl:del:{contact_id}")
    _tap(roman, f"ppl:open:{contact_id}")
    assert ContactRepository().get(contact_id).status == "declined"
    _invite(roman)
    assert _replies(roman("@anna"))[0].startswith("@anna said no recently.")


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
    # Not asked again for a while
    _invite(roman)
    assert _replies(roman("@anna"))[0].startswith("@anna said no recently.")
    assert len(anna.messages()) == 1
    # An invite link still works, if she changes her mind
    _tap(anna, f"inv:yes:{_invite(roman)}")
    assert _people(roman) == [("Anna", "accepted")]


def test_an_invite_after_a_no_gets_a_free_name(person):
    roman, anna, anna_b = person("Roman", "roman_i"), person("Anna", "anna"), person("Anna", "anna_b")
    _invite(roman)
    roman("@anna")
    [request] = anna.messages()
    _tap(anna, _buttons(request.kwargs["reply_markup"])[0][1][1])     # ❌ No
    _tap(anna_b, f"inv:yes:{_invite(roman)}")                         # another Anna takes "Anna"
    _tap(anna, f"inv:yes:{_invite(roman)}")                           # the first changes her mind
    assert _people(roman) == [("Anna", "accepted"), ("Anna 2", "accepted")]


def test_requests_per_day(person):
    from db.repositories.contact import REQUESTS_PER_DAY

    roman = person("Roman", "roman_i")
    others = [person(f"P{n}", f"p{n}_x") for n in range(REQUESTS_PER_DAY + 1)]
    for other in others[:-1]:
        _invite(roman)
        assert _replies(roman(f"@{other.user().username}"))[0].startswith("📨 Asked")
    _invite(roman)
    assert _replies(roman(f"@{others[-1].user().username}"))[0].startswith(f"That's {REQUESTS_PER_DAY} requests today.")


def test_cancel_and_ask_again_still_counts(person):
    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    _invite(roman)
    roman("@anna")
    from db.repositories.contact import ContactRepository
    [(contact, _)] = ContactRepository().people_of(roman.user().id)
    _tap(roman, f"ppl:del:{contact.id}")             # 🗑 Cancel request
    _invite(roman)
    assert _replies(roman("@anna"))[0].startswith("You asked @anna today already.")
    assert len(anna.messages()) == 1                # asked once


def test_a_stale_username_belongs_to_whoever_has_it_now(person):
    from db.repositories.user import UserRepository

    anna = person("Anna", "anna")
    ben = person("Ben", "ben")
    # Ben takes @anna (Anna changed hers, but hasn't written to the bot since)
    UserRepository().remember_profile(ben.telegram_id, "Ben", "anna")
    assert anna.user().username is None
    assert UserRepository().get_by_username("anna").telegram_id == ben.telegram_id


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


def test_rename_after_the_contact_is_gone(person):
    roman, anna, contact = _connected(person)
    _tap(roman, f"ppl:ren:{contact.id}")
    _tap(anna, f"ppl:stop:{contact.id}")             # meanwhile, Anna stops it
    assert _replies(roman("Mom"))[0] == "That person is no longer in your 👥 People."
    assert "awaiting" not in roman.context.user_data
    # The next message is a normal message again
    from handlers.text import HELP_TEXT
    assert _replies(roman("hello there"))[0] == HELP_TEXT


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

    reminder = ReminderRepository().create(
        owner.user(), contact_person.telegram_id, "bring the ball", utcnow() + timedelta(hours=1), None, "…",
        MessageSource.TYPED, target=contact_person.user(),
    )
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
    assert roman.told()[-1] == "🚫 Anna stopped your reminders. Your 1 reminder for them is cancelled."


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
