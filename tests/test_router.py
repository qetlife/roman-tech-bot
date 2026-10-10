import pytest

from intents.router import Intent, match_intent


async def noop(update, context, rest):
    pass


CREATE = Intent("reminder.create", ["remind me", "set a reminder", "set reminder"], noop)
LIST = Intent("reminder.list", ["my reminders", "show my reminders", "reminders"], noop)
INTENTS = [CREATE, LIST]


@pytest.mark.parametrize("text, intent, rest", [
    ("remind me in 2 hours to call Mom",        CREATE, "in 2 hours to call Mom"),
    ("Remind me tomorrow",                      CREATE, "tomorrow"),
    ("set a reminder for friday: Dentist",      CREATE, "for friday: Dentist"),
    ("please remind me at 9 to stretch",        CREATE, "at 9 to stretch"),
    ("Hey, can you remind me in 5 min to go",   CREATE, "in 5 min to go"),
    ("show my reminders",                       LIST,   ""),
    ("my reminders",                            LIST,   ""),
    ("reminders",                               LIST,   ""),
])
def test_match(text, intent, rest):
    m = match_intent(text, INTENTS)
    assert m.intent is intent
    assert m.rest == rest


@pytest.mark.parametrize("text", [
    "hello", "remind", "reminder", "don't remind me", "remindme now", "set a reminders",
])
def test_no_match(text):
    assert match_intent(text, INTENTS) is None
