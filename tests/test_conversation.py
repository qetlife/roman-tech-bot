"""Talking to the bot: asking back for what's missing, and "it" / "the second one" for 10 minutes."""

from datetime       import datetime, time, timedelta
from zoneinfo       import ZoneInfo

import pytest

from core.conversation  import (
    Conversation, clock_phrase, is_never_mind, needs_day, parse_follow_up, read_weekday, untimed, with_clock, with_day,
)
from core.parser        import parse_reminder
from enums              import FollowUp, ItemKind
from tests.test_handlers import _active, _buttons, _replies


TZ = ZoneInfo("Europe/Lisbon")
# A Sunday at noon
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=TZ)


# --- the parser: a time split around the text --------------------------------

@pytest.mark.parametrize("request_, when, text, recurrence", [
    ("friday dentist at 10", datetime(2026, 10, 30, 10, 0, tzinfo=TZ), "dentist", None),
    ("tomorrow call mom at 10", datetime(2026, 10, 26, 10, 0, tzinfo=TZ), "call mom", None),
    ("at 9 to call mom tomorrow", datetime(2026, 10, 26, 9, 0, tzinfo=TZ), "call mom", None),
    ("today dentist at 18", datetime(2026, 10, 25, 18, 0, tzinfo=TZ), "dentist", None),
    ("every monday to call mom at 10", datetime(2026, 10, 26, 10, 0, tzinfo=TZ), "call mom", "mon@10:00"),
    ("every day to take pills at 9:00", datetime(2026, 10, 26, 9, 0, tzinfo=TZ), "take pills",
     "mon,tue,wed,thu,fri,sat,sun@09:00"),
    ("at 9 to send the report for 24.12", datetime(2026, 12, 24, 9, 0, tzinfo=TZ), "send the report", None),
])
def test_a_time_split_around_the_text(request_, when, text, recurrence):
    parsed = parse_reminder(request_, NOW)
    assert (parsed.when, parsed.text, parsed.timed) == (when, text, True)
    assert (parsed.recurrence.serialize() if parsed.recurrence else None) == recurrence


@pytest.mark.parametrize("request_, text", [
    # The words are the text's: nothing to put together
    ("at 9 to tell anna about tomorrow", "tell anna about tomorrow"),
    ("at 9 to read chapter 2", "read chapter 2"),
    ("in 2 hours to call mom on friday", "call mom on friday"),
])
def test_text_that_only_looks_like_a_time_stays(request_, text):
    assert parse_reminder(request_, NOW).text == text


# --- asking back --------------------------------------------------------------

def test_untimed():
    assert untimed("friday dentist", NOW).text == "dentist"
    # The day's 09:00 has passed, the day hasn't
    assert untimed("today dentist", NOW).text == "dentist"
    assert untimed("friday dentist at 10", NOW) is None
    assert untimed("call mom", NOW) is None


@pytest.mark.parametrize("answer, phrase", [
    ("10", "at 10"), ("at 10", "at 10"), ("10:30", "at 10:30"), ("9pm", "at 9pm"),
    ("evening", "at 19:00"), ("in the morning", "at 09:00"), ("afternoon", "at 14:00"),
    ("in 2 hours", "in 2 hours"),
])
def test_clock_phrase(answer, phrase):
    assert clock_phrase(answer) == phrase


def test_with_clock_parses():
    parsed = parse_reminder(with_clock("friday dentist", "evening"), NOW)
    assert (parsed.when, parsed.text) == (datetime(2026, 10, 30, 19, 0, tzinfo=TZ), "dentist")


def test_which_day():
    assert needs_day("every week to water the plants")
    assert not needs_day("every week on monday to water the plants")
    assert not needs_day("every monday to water the plants")
    assert with_day("every week to water the plants", 0) == "every monday to water the plants"
    assert [read_weekday(a) for a in ("monday", "on fri", "Tuesday.", "tues", "soon", "mon and tue")] == \
        [0, 4, 1, 1, None, None]


@pytest.mark.parametrize("text, expected", [
    ("move it to 10", (FollowUp.MOVE, None, "10")),
    ("make it 9:30", (FollowUp.MOVE, None, "9:30")),
    ("change that to tomorrow", (FollowUp.MOVE, None, "tomorrow")),
    ("ok, push it to friday at 10 please", (FollowUp.MOVE, None, "friday at 10")),
    ("move the second one to 11", (FollowUp.MOVE, 2, "11")),
    ("cancel that", (FollowUp.CANCEL, None, None)),
    ("Delete it.", (FollowUp.CANCEL, None, None)),
    ("remove the first one", (FollowUp.CANCEL, 1, None)),
    ("cancel number 3", (FollowUp.CANCEL, 3, None)),
    ("cancel the last one", (FollowUp.CANCEL, -1, None)),
    ("and the same next week", (FollowUp.COPY, None, "next week")),
    ("also on thursday", (FollowUp.COPY, None, "on thursday")),
    ("same time tomorrow", (FollowUp.COPY, None, "tomorrow")),
])
def test_follow_ups(text, expected):
    request = parse_follow_up(text)
    assert (request.action, request.target, request.when) == expected


@pytest.mark.parametrize("text", ["cancel the dentist reminder", "move padel to 20:00", "remind me to call it", "it"])
def test_not_follow_ups(text):
    assert parse_follow_up(text) is None


def test_never_mind():
    assert all(is_never_mind(t) for t in ("never mind", "Nevermind.", "cancel", "forget it"))
    assert not is_never_mind("cancel the dentist reminder")
    # Only where they can't be the answer
    assert not is_never_mind("no") and not is_never_mind("stop")
    assert is_never_mind("no", loose=True) and is_never_mind("Stop.", loose=True)


def test_the_conversation_lasts_10_minutes():
    talk = Conversation(NOW, subject=(ItemKind.REMINDER, 1), listed=[(ItemKind.EVENT, 7), (ItemKind.EVENT, 8)])
    assert talk.fresh(NOW + timedelta(minutes=10)) and not talk.fresh(NOW + timedelta(minutes=11))
    assert talk.pick(None) == (ItemKind.REMINDER, 1)
    assert talk.pick(2) == (ItemKind.EVENT, 8) and talk.pick(-1) == (ItemKind.EVENT, 8)
    assert talk.pick(3) is None
    assert Conversation(NOW, subject=(ItemKind.REMINDER, 1)).pick(-1) == (ItemKind.REMINDER, 1)


# --- in the chat ----------------------------------------------------------------

def _local(reminder):
    return reminder.remind_at.astimezone(TZ)


def test_a_day_without_a_time_asks_what_time(chat):
    update = chat("remind me next friday dentist")
    assert _replies(update)[0].startswith("⏰ What time should I remind you: “dentist”?")
    keyboard = update.effective_message.reply_text.call_args.kwargs["reply_markup"]
    assert _buttons(keyboard) == [[("🌅 Morning 09:00", "ans:clock:0900"), ("☀️ Afternoon 14:00", "ans:clock:1400"),
                                   ("🌙 Evening 19:00", "ans:clock:1900")]]
    assert _active(chat.telegram_id) == []

    update = chat("10:30")
    assert _replies(update)[0].startswith("⏰ Got it: dentist\n")
    [reminder] = _active(chat.telegram_id)
    assert (_local(reminder).weekday(), _local(reminder).time()) == (4, time(10, 30))


def _asked(chat):
    """The id of the message asking the question (whose buttons answer it)."""
    from handlers.ui import ASKED_MESSAGE_ID
    return chat.context.user_data[ASKED_MESSAGE_ID]


def test_the_time_by_button(chat):
    from handlers.text import on_answer

    chat("remind me next friday to call the bank")
    update = chat(data="ans:clock:1900", handler=on_answer, message_id=_asked(chat))
    update.callback_query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
    [reminder] = _active(chat.telegram_id)
    assert (reminder.text, _local(reminder).time()) == ("call the bank", time(19, 0))

    # Pressed again later: the question is over
    update = chat(data="ans:clock:0900", handler=on_answer, message_id=_asked(chat))
    assert update.callback_query.answer.call_args.args[0] == "That question has expired. Send it again."


def test_what_time_asks_again_if_it_isnt_one(chat):
    chat("remind me next friday dentist")
    assert _replies(chat("whenever"))[0].startswith("I couldn't understand the time. ⏰ What time")
    # A whole new time works too
    assert _replies(chat("tomorrow at 10"))[0].startswith("⏰ Got it: dentist\n")


def test_a_repeat_without_a_time_asks(chat):
    chat("remind me every monday to call mom")
    update = chat("evening")
    assert "every Mon at 19:00" in _replies(update)[0]


def test_every_week_asks_which_day_then_the_time(chat):
    from handlers.text import on_answer

    update = chat("remind me every week to water the plants")
    assert _replies(update)[0] == "⏰ Every week: which day should I remind you?"
    assert _buttons(update.effective_message.reply_text.call_args.kwargs["reply_markup"])[0][0] == ("Mon", "ans:day:0")
    assert _replies(chat("someday"))[0].startswith("That isn't a day of the week.")
    update = chat(data="ans:day:2", handler=on_answer, message_id=_asked(chat))
    # One question at a time
    assert _replies(update)[0].startswith("⏰ What time should I remind you: “water the plants”?")
    update = chat("8")
    assert "every Wed at 08:00" in _replies(update)[0]


def test_an_event_every_week_asks_which_day(chat):
    chat("event yoga every week at 19:00")
    update = chat("thursday")
    assert _replies(update)[0].startswith("📅 Added: yoga")
    assert "🔁 every Thu at 19:00" in _replies(update)[0]


def test_never_mind_drops_the_question(chat):
    chat("remind me next friday dentist")
    assert _replies(chat("never mind"))[0] == "OK, dropped the reminder “dentist”."
    # It's over: "at 10" is not an answer any more
    assert _replies(chat("at 10"))[0].startswith("⏰ at 10: what should I remind you about?")


def test_a_command_instead_of_the_answer_drops_the_question(chat):
    chat("remind me next friday dentist")
    replies = _replies(chat("what do I have tomorrow?"))
    assert replies[0] == "Dropped: the reminder “dentist”."
    assert replies[1].startswith("Nothing on ")
    # A new reminder replaces the question without a note
    chat("remind me next friday dentist")
    assert _replies(chat("remind me tomorrow at 9 to call mom"))[0].startswith("⏰ Got it: call mom")


def test_move_it(chat):
    chat("remind me next friday at 9 to call mom")
    update = chat("move it to 10")
    assert _replies(update)[0].startswith("⏰ Moved: call mom\n")
    [reminder] = _active(chat.telegram_id)
    assert (_local(reminder).weekday(), _local(reminder).time()) == (4, time(10, 0))
    chat("make it tomorrow")
    [reminder] = _active(chat.telegram_id)
    assert _local(reminder).time() == time(10, 0)
    assert _local(reminder).date() == (datetime.now(TZ) + timedelta(days=1)).date()


def test_cancel_it_with_undo(chat):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    [reminder] = _active(chat.telegram_id)
    update = chat("cancel that")
    assert _replies(update)[0].startswith("🗑 Cancelled: call mom")
    assert _buttons(update.effective_message.reply_text.call_args.kwargs["reply_markup"]) == \
        [[("↩️ Undo", f"rem:back:{reminder.id}")]]
    assert _active(chat.telegram_id) == []

    update = chat(data=f"rem:back:{reminder.id}", handler=on_reminder_button)
    assert update.callback_query.edit_message_text.call_args.args[0].startswith("↩️ Back: call mom")
    assert [r.id for r in _active(chat.telegram_id)] == [reminder.id]
    # Twice does nothing
    update = chat(data=f"rem:back:{reminder.id}", handler=on_reminder_button)
    assert update.callback_query.answer.call_args.args[0] == "It's no longer cancelled."


def test_cancel_an_event_asks_first(chat):
    from tests.test_events import _events

    chat("event padel next friday at 21:00")
    update = chat("cancel it")
    assert _replies(update)[0].startswith("Cancel “padel”?")
    assert len(_events(chat.telegram_id)) == 1


def test_the_same_next_week(chat):
    chat("remind me next friday at 9 to call mom")
    [first] = _active(chat.telegram_id)
    update = chat("and the same next week")
    assert _replies(update)[0].startswith("⏰ Got it: call mom\n")
    second = [r for r in _active(chat.telegram_id) if r.id != first.id][0]
    assert second.remind_at - first.remind_at == timedelta(days=7)
    # "it" is now the copy
    chat("also on saturday")
    assert len(_active(chat.telegram_id)) == 3


def test_the_same_for_an_event(chat):
    from tests.test_events import _events

    chat("event padel next friday at 21:00")
    update = chat("same next week")
    assert _replies(update)[0].startswith("📅 Added: padel")
    starts = sorted(e.starts_at for e in _events(chat.telegram_id))
    assert starts[1] - starts[0] == timedelta(days=7)


def test_the_second_one_in_a_list(chat):
    chat("remind me tomorrow at 9 to call mom")
    chat("remind me tomorrow at 10 to pay rent")
    chat("remind me tomorrow at 11 to water plants")
    chat("my reminders")
    update = chat("cancel the second one")
    assert _replies(update)[0].startswith("🗑 Cancelled: pay rent")
    assert sorted(r.text for r in _active(chat.telegram_id)) == ["call mom", "water plants"]


def test_after_10_minutes_it_asks_which_one(chat):
    from handlers.ui import CONVERSATION

    chat("remind me tomorrow at 9 to call mom")
    chat.context.user_data[CONVERSATION].last -= timedelta(minutes=11)
    assert _replies(chat("cancel it"))[0].startswith("Which one?")
    assert len(_active(chat.telegram_id)) == 1


def test_it_without_anything_before(chat):
    assert _replies(chat("move it to 10"))[0].startswith("Which one?")


def test_edit_with_only_a_day_asks_for_the_time(chat):
    from handlers.reminders import on_reminder_button

    chat("remind me tomorrow at 9 to call mom")
    [reminder] = _active(chat.telegram_id)
    chat(data=f"rem:edit:{reminder.id}", handler=on_reminder_button)
    assert _replies(chat("next friday to call dad"))[0].startswith("At what time?")
    # Still editing: the answer with a time does it
    assert _replies(chat("next friday at 10 to call dad"))[0].startswith("✏️ Updated: call dad")


def test_also_remind_me_is_a_new_reminder(chat):
    chat("remind me tomorrow at 8 to call mom")
    update = chat("also remind me tomorrow at 9 to pay rent")
    assert _replies(update)[0].startswith("⏰ Got it: pay rent\n")
    assert sorted(r.text for r in _active(chat.telegram_id)) == ["call mom", "pay rent"]
    assert _replies(chat("and remind me tomorrow at 10 to water plants"))[0].startswith("⏰ Got it: water plants")


@pytest.mark.parametrize("answer", ["make it work", "push it to prod", "also buy milk"])
def test_a_follow_up_phrase_can_be_the_answer(chat, answer):
    chat("remind me tomorrow at 9 to call mom")
    update = chat("remind me tomorrow at 12")
    assert _replies(update)[0] == "⏰ tomorrow at 12: what should I remind you about?"
    update = chat(answer)
    assert _replies(update)[0].startswith(f"⏰ Got it: {answer}\n")
    assert len(_active(chat.telegram_id)) == 2


def test_cancel_the_second_one_during_a_question(chat):
    chat("remind me tomorrow at 9 to call mom")
    chat("remind me tomorrow at 10 to pay rent")
    chat("my reminders")
    chat("remind me tomorrow at 12")
    replies = _replies(chat("cancel the second one"))
    assert replies[0] == "Dropped: the reminder for tomorrow at 12."
    assert replies[1].startswith("🗑 Cancelled: pay rent")


def test_a_day_as_the_answer_to_when_asks_what_time(chat):
    chat("remind me to call mom")
    update = chat("next friday")
    assert _replies(update)[0].startswith("⏰ What time should I remind you: “call mom”?")
    assert _active(chat.telegram_id) == []
    assert _replies(chat("18:00"))[0].startswith("⏰ Got it: call mom\n")
    [reminder] = _active(chat.telegram_id)
    assert (_local(reminder).weekday(), _local(reminder).time()) == (4, time(18, 0))


def test_buttons_of_an_older_question_dont_answer_a_new_one(chat):
    from handlers.text import on_answer

    chat("remind me next friday dentist")
    first = _asked(chat)
    chat("remind me next saturday gym")
    assert _asked(chat) != first
    update = chat(data="ans:clock:0900", handler=on_answer, message_id=first)
    assert update.callback_query.answer.call_args.args[0] == "That question has expired. Send it again."
    assert _active(chat.telegram_id) == []
    # The new question's buttons do
    chat(data="ans:clock:0900", handler=on_answer, message_id=_asked(chat))
    assert [r.text for r in _active(chat.telegram_id)] == ["gym"]


def test_no_and_stop_are_answers_where_they_can_be(chat):
    from handlers.settings import on_quiet_button

    # "stop" is a reminder's text
    chat("remind me tomorrow at 12")
    assert _replies(chat("stop"))[0].startswith("⏰ Got it: stop\n")
    # …but drops "What time?"
    chat("remind me next friday dentist")
    assert _replies(chat("no"))[0] == "OK, dropped the reminder “dentist”."
    # "no" switches quiet hours off
    chat(data="qhopt:custom", handler=on_quiet_button)
    assert _replies(chat("no"))[0].startswith("🌙 Quiet hours set to ")
