"""Reminders for others: "remind anna …", delivery to her, updates back to the sender."""

import asyncio

from datetime       import datetime, timedelta
from unittest.mock  import AsyncMock, MagicMock
from zoneinfo       import ZoneInfo

import pytest

from tests.test_handlers import _replies


@pytest.fixture
def pair(person, monkeypatch):
    """Roman (Lisbon) and Anna (Kyiv), who allowed Roman to remind her."""
    from db.repositories.contact import ContactRepository
    from handlers import reminders, settings

    render = AsyncMock()
    for module in (reminders, settings):
        monkeypatch.setattr(module, "render_menu", render)

    roman, anna = person("Roman", "roman_i"), person("Anna", "anna")
    from db.repositories.user import UserRepository
    UserRepository().set_timezone(anna.telegram_id, "Europe/Kyiv")
    repo = ContactRepository()
    repo.use_invite(repo.create_invite(roman.user().id).token, anna.user())

    bot = roman.context.bot
    bot.send_message.return_value = MagicMock(message_id=777)
    bot.edit_message_text = AsyncMock()
    bot.delete_message = AsyncMock()
    roman.screen = anna.screen = lambda: render.call_args.args[2:4]
    return roman, anna


def _for(someone):
    """The active reminders waiting for this person."""
    from db.repositories.reminder import ReminderRepository
    return ReminderRepository().list_active(someone.user().id)


def _press(someone, data):
    from handlers.reminders import on_reminder_button
    return someone(data=data, handler=on_reminder_button)


def _alerts(update):
    return [c.args[0] for c in update.callback_query.answer.call_args_list if c.args]


def _deliver(reminder, now, monkeypatch):
    """Run the delivery loop at `now` with only this reminder due."""
    from jobs import delivery
    monkeypatch.setattr(delivery.reminders, "get_due", lambda _: [reminder])
    monkeypatch.setattr(delivery, "utcnow", lambda: now)
    context = MagicMock()
    context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=901))
    context.bot.edit_message_text = AsyncMock()
    context.bot.delete_message = AsyncMock()
    asyncio.run(delivery.deliver_due(context))
    return context.bot


def _sent(bot, someone):
    return [c.kwargs["text"] for c in bot.send_message.call_args_list if c.kwargs["chat_id"] == someone.telegram_id]


def _reload(reminder):
    from db.repositories.reminder import ReminderRepository
    return ReminderRepository().get(reminder.id)


# --- creating ---------------------------------------------------------------

def test_remind_a_contact(pair):
    roman, anna = pair
    update = roman("remind anna tomorrow at 9 to bring the keys")
    assert _replies(update)[0].startswith("⏰ Got it for Anna: bring the keys\n🗓 ")
    assert ", 09:00" in _replies(update)[0]

    [reminder] = _for(anna)
    assert reminder.creator_user_id == roman.user().id
    assert reminder.chat_id == anna.telegram_id     # delivered in her chat
    assert _for(roman) == []


def test_the_time_is_the_senders(pair):
    roman, anna = pair
    roman("remind Anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)
    local = reminder.remind_at.astimezone(ZoneInfo("Europe/Lisbon"))
    assert (local.hour, local.minute) == (9, 0)

    # Anna sees it in her own time (Kyiv is 2 hours ahead of Lisbon)
    update = anna("my reminders")
    text = _replies(update)[0]
    assert "1. bring the keys\n    📨 from Roman (@roman_i)\n    🗓 " in text
    assert ", 11:00" in text


@pytest.mark.parametrize("request_", [
    "remind anna to bring the keys tomorrow at 9",
    "remind anna, bring the keys tomorrow at 9",
    "remind @anna tomorrow at 9 to bring the keys",
    "please remind ANNA tomorrow at 9 to bring the keys",
])
def test_ways_to_name_a_contact(pair, request_):
    roman, anna = pair
    roman(request_)
    assert [r.text for r in _for(anna)] == ["bring the keys"]


def test_a_renamed_contact(pair):
    from db.repositories.contact import ContactRepository
    roman, anna = pair
    contacts = ContactRepository()
    [(contact, _)] = contacts.people_of(roman.user().id)
    contacts.rename(contact.id, roman.user().id, "Little Sis")

    update = roman("remind little sis tomorrow at 9 to bring the keys")
    assert _replies(update)[0].startswith("⏰ Got it for Little Sis: bring the keys")


def test_someone_who_isnt_a_contact(pair):
    roman, _ = pair
    update = roman("remind bob tomorrow at 9 to bring the keys")
    assert _replies(update)[0].startswith("Who's “bob”? To remind someone, invite them in 👥 People first.")
    assert update.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data \
        == "menu:people"
    assert _for(roman) == []


@pytest.mark.parametrize("request_, text", [
    ("remind me tomorrow at 9 to call mom", "call mom"),
    ("remind to call mom tomorrow at 9", "call mom"),
    ("remind tomorrow at 9 to call mom", "call mom"),
    ("remind call mom tomorrow at 9", "call mom"),
])
def test_own_reminders_still_work(pair, request_, text):
    roman, _ = pair
    roman(request_)
    assert [r.text for r in _for(roman)] == [text]


def test_a_contact_who_hasnt_answered_yet(person):
    from db.repositories.contact import ContactRepository
    roman, ben = person("Roman", "roman_i"), person("Ben", "ben")
    ContactRepository().request(roman.user().id, ben.user())

    update = roman("remind ben tomorrow at 9 to call")
    assert _replies(update) == ["⏳ Ben hasn't allowed reminders from you yet."]
    assert _for(ben) == []


def test_asking_when_for_a_contact(pair):
    roman, anna = pair
    update = roman("remind anna to bring the keys")
    assert _replies(update)[0].startswith("⏰ When should I remind Anna: “bring the keys”?")
    update = roman("tomorrow at 9")
    assert _replies(update)[0].startswith("⏰ Got it for Anna: bring the keys")
    assert [r.text for r in _for(anna)] == ["bring the keys"]


def test_asking_what_for_a_contact(pair):
    roman, anna = pair
    update = roman("remind anna tomorrow at 9")
    assert _replies(update) == ["⏰ tomorrow at 9: what should I remind Anna about?"]
    roman("bring the keys")
    assert [r.text for r in _for(anna)] == ["bring the keys"]


def test_a_contact_removed_while_the_bot_asks(pair):
    from db.repositories.contact import ContactRepository
    roman, anna = pair
    roman("remind anna to bring the keys")
    contacts = ContactRepository()
    [(contact, _)] = contacts.people_of(roman.user().id)
    contacts.remove(contact.id, anna.user().id)

    update = roman("tomorrow at 9")
    assert _replies(update) == ["That person isn't in your 👥 People any more."]
    assert _for(anna) == [] and _for(roman) == []


def test_a_new_reminder_after_one_for_a_contact_is_your_own(pair):
    roman, anna = pair
    roman("remind anna to bring the keys")
    roman("remind me tomorrow at 9 to call mom")
    assert [r.text for r in _for(roman)] == ["call mom"]
    assert _for(anna) == []


# --- buttons ----------------------------------------------------------------

def test_only_the_target_answers_and_only_the_creator_changes(pair):
    roman, anna = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)

    for data in (f"rem:ok:{reminder.id}", f"rem:snz:{reminder.id}:10"):
        assert _alerts(_press(roman, data)) == ["This reminder isn't yours."]
    for data in (f"rem:undo:{reminder.id}", f"rem:edit:{reminder.id}", f"rem:wrong:{reminder.id}"):
        assert _alerts(_press(anna, data)) == ["This reminder isn't yours."]
    assert _reload(reminder).status == "pending"

    _press(roman, f"rem:undo:{reminder.id}")
    assert _reload(reminder).status == "cancelled"


def test_the_creator_edits_it(pair):
    roman, anna = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)
    _press(roman, f"rem:edit:{reminder.id}")
    update = roman("tomorrow at 10 to bring the keys and the ball")
    assert _replies(update)[0].startswith("✏️ Updated for Anna: bring the keys and the ball\n🗓 ")
    assert ", 10:00" in _replies(update)[0]
    assert _reload(reminder).target_user_id == anna.user().id


def test_ok_tells_the_sender(pair):
    roman, anna = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)
    _press(anna, f"rem:ok:{reminder.id}")
    assert _reload(reminder).status == "done"
    assert roman.told() == ["✅ Anna did it: bring the keys"]

    # A second tap on the same message isn't news.
    _press(anna, f"rem:ok:{reminder.id}")
    assert roman.told() == ["✅ Anna did it: bring the keys"]


def test_updates_can_be_turned_off(pair):
    from handlers.settings import on_updates_button
    roman, anna = pair
    roman(data="updopt:off", handler=on_updates_button)
    text, _ = roman.screen()
    assert "Current: Off" in text

    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)
    _press(anna, f"rem:ok:{reminder.id}")
    assert roman.told() == []


def test_the_target_cancels_it_and_the_sender_is_told(pair):
    roman, anna = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)
    _press(anna, f"rem:del:{reminder.id}")
    assert _reload(reminder).status == "cancelled"
    assert roman.told() == ["🗑 Anna cancelled your reminder: bring the keys"]


def test_the_sender_cancels_it_from_their_list(pair):
    roman, anna = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)
    _press(roman, f"rem:del:{reminder.id}")
    assert _reload(reminder).status == "cancelled"
    assert anna.told() == [] and roman.told() == []


def test_the_senders_list_has_for_others(pair):
    roman, anna = pair
    roman("remind me tomorrow at 8 to call mom")
    roman("remind anna tomorrow at 9 to bring the keys")
    text = _replies(roman("my reminders"))[0]
    assert "1. call mom\n    🗓 " in text
    assert "\n\nFor others:\n2. Anna: bring the keys\n    🗓 " in text

    update = roman("cancel the keys reminder")
    assert _replies(update)[0].startswith("Cancel “bring the keys”?")


def test_only_others(pair):
    roman, _ = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    text = _replies(roman("my reminders"))[0]
    assert text.startswith("Your reminders (tap ❌ to cancel):\n\nFor others:\n1. Anna: bring the keys")


def test_a_reply_by_the_target(pair):
    roman, anna = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)
    from db.repositories.reminder import ReminderRepository
    ReminderRepository().mark_fired(reminder.id, 555, reminder.remind_at + timedelta(minutes=5))

    from handlers.text import on_text
    from tests.test_handlers import _update
    update = _update(anna.telegram_id, text="cancel", reply_to=555)
    asyncio.run(on_text(update, anna.context))
    assert _reload(reminder).status == "cancelled"
    assert roman.told() == ["🗑 Anna cancelled your reminder: bring the keys"]


# --- delivery ---------------------------------------------------------------

def test_delivered_to_the_target_from_the_sender(pair, monkeypatch):
    roman, anna = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)

    bot = _deliver(reminder, reminder.remind_at + timedelta(seconds=5), monkeypatch)
    assert _sent(bot, anna) == ["⏰ bring the keys\n📨 from Roman (@roman_i)"]
    assert _sent(bot, roman) == []


def test_missed_tells_the_sender(pair, monkeypatch):
    roman, anna = pair
    roman("remind anna tomorrow at 9 to bring the keys")
    [reminder] = _for(anna)
    _deliver(reminder, reminder.remind_at + timedelta(seconds=5), monkeypatch)

    bot = _deliver(_reload(reminder), reminder.remind_at + timedelta(hours=24, minutes=1), monkeypatch)
    assert _reload(reminder).status == "missed"
    assert _sent(bot, roman) == ["❌ Anna missed it: bring the keys"]


def test_a_repeat_keeps_the_senders_clock(pair, monkeypatch):
    roman, anna = pair
    roman("remind anna every day at 9 to take pills")
    [reminder] = _for(anna)
    lisbon = ZoneInfo("Europe/Lisbon")
    assert reminder.remind_at.astimezone(lisbon).hour == 9

    _deliver(reminder, reminder.remind_at + timedelta(seconds=5), monkeypatch)
    _press(anna, f"rem:ok:{reminder.id}")
    after = _reload(reminder)
    assert after.remind_at.astimezone(lisbon).hour == 9
    assert after.remind_at.astimezone(lisbon).date() == reminder.remind_at.astimezone(lisbon).date() + timedelta(days=1)
    assert roman.told() == ["✅ Anna did it: take pills"]

    # Anna sees whose 9 o'clock it is.
    text = _replies(anna("my reminders"))[0]
    assert "🔁 every day at 09:00 (Roman's time)" in text


def test_timezone_changes_move_only_what_you_made(pair):
    from handlers.settings import apply_timezone
    from tests.test_handlers import _update
    roman, anna = pair
    roman("remind anna every day at 9 to take pills")
    [reminder] = _for(anna)

    asyncio.run(apply_timezone(_update(anna.telegram_id), anna.context, "America/New_York"))
    assert _reload(reminder).remind_at == reminder.remind_at

    asyncio.run(apply_timezone(_update(roman.telegram_id), roman.context, "Europe/Kyiv"))
    assert _reload(reminder).remind_at.astimezone(ZoneInfo("Europe/Kyiv")).hour == 9


def test_agenda_of_the_target(pair):
    roman, anna = pair
    roman("remind anna every day at 9 to take pills")
    text = _replies(anna("what do I have tomorrow?"))[0]
    assert "take pills" in text


def test_time_zone_of_a_repeat_for_the_agenda():
    from core.commands import occurs_on
    # Daily 23:30 in Lisbon is 01:30 the next day in Kyiv.
    lisbon, kyiv = ZoneInfo("Europe/Lisbon"), ZoneInfo("Europe/Kyiv")
    made = datetime(2026, 10, 1, 12, tzinfo=lisbon)
    first = datetime(2026, 10, 1, 23, 30, tzinfo=lisbon)
    day = datetime(2026, 10, 10).date()
    assert occurs_on(first, "mon,tue,wed,thu,fri,sat,sun@23:30", day, kyiv, made, lisbon)


def test_timezone_first_then_the_reminder_for_the_contact(pair):
    from db.models.user import User
    from db.session import SessionLocal
    from handlers.settings import on_timezone_button
    roman, anna = pair
    with SessionLocal() as session:
        session.get(User, roman.user().id).timezone = None
        session.commit()

    update = roman("remind anna tomorrow at 9 to bring the keys")
    assert _replies(update)[0].startswith("First, one-time setup.")
    roman(data="tz:Europe/Lisbon", handler=on_timezone_button)
    assert [r.text for r in _for(anna)] == ["bring the keys"]
