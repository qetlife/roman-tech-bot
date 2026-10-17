"""Typo tolerance: core/typos.py, and its use in the parser and intent matching."""

from datetime   import datetime
from zoneinfo   import ZoneInfo

import pytest

from core.intents import Intent, match_intent
from core.parser import ParseError, TIME_VOCABULARY, parse_reminder
from core.typos import Vocabulary, distance

TZ = ZoneInfo("Europe/Kyiv")
# Saturday 10 Oct 2026, 14:00
NOW = datetime(2026, 10, 10, 14, 0, tzinfo=TZ)


def dt(day, hour, minute=0, month=10, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


# --- distance and vocabulary ----------------------------------------------------

@pytest.mark.parametrize("a, b, expected", [
    ("tomorrow", "tomorrow", 0),
    ("tomorow", "tomorrow", 1),     # missing letter
    ("tomorrrow", "tomorrow", 1),   # extra letter
    ("tomurrow", "tomorrow", 1),    # wrong letter
    ("teusday", "tuesday", 1),      # swapped neighbours
    ("wensday", "wednesday", 2),
    ("", "abc", 3),
])
def test_distance(a, b, expected):
    assert distance(a, b) == expected


@pytest.mark.parametrize("word, expected", [
    ("tomorow", "tomorrow"),
    ("Tomorow", "tomorrow"),
    ("wensday", "wednesday"),
    ("thurday", "thursday"),
    ("saterday", "saturday"),
    ("febuary", "february"),
    ("evry", "every"),
    ("tonite", "tonight"),      # shorthand
    ("tmrw", "tomorrow"),
    ("tomorrow", None),         # already right
    ("mondays", None),          # a known word is never "corrected" to another
    ("mon", None),
    ("tue", None),              # too short to guess
    ("9am", None),              # numbers and times are left alone
    ("call", None),             # not close to any known word
])
def test_time_vocabulary(word, expected):
    assert TIME_VOCABULARY.correct(word) == expected


def test_a_tie_with_the_same_meaning_is_fine():
    # "minuts" is as close to "minute" as to "minutes": both are the unit.
    assert TIME_VOCABULARY.correct("minuts") in ("minute", "minutes")


def test_a_tie_between_two_meanings_is_not_guessed():
    vocabulary = Vocabulary({"monday": "day:0", "sunday": "day:6"})
    assert vocabulary.correct("munday") is None


def test_fix_keeps_punctuation():
    assert TIME_VOCABULARY.fix("tomorow,") == "tomorrow,"
    assert TIME_VOCABULARY.fix_all(["(wensday)", "21.20", "mom"]) == ["(wednesday)", "21.20", "mom"]


# --- parser ---------------------------------------------------------------------

@pytest.mark.parametrize("request_, when, text", [
    ("tomorow at 9 to call mom",            dt(11, 9),      "call mom"),
    ("tommorow morning to run",             dt(11, 9),      "run"),
    ("on wensday to pay rent",              dt(14, 9),      "pay rent"),
    ("on teusday to call",                  dt(13, 9),      "call"),
    ("for thurday 18:00: dentist",          dt(15, 18),     "dentist"),
    ("saterday at 10 to clean",             dt(17, 10),     "clean"),
    ("febuary 3 to renew",                  dt(3, 9, month=2, year=2027), "renew"),
    ("tonite to stretch",                   dt(10, 20),     "stretch"),
    ("in 10 minuts to check the oven",      dt(10, 14, 10), "check the oven"),
    ("in 2 ours to rest",                   dt(10, 16),     "rest"),
    ("in fourty minutes to go",             dt(10, 14, 40), "go"),
    # The text keeps the words as written, typos and all
    ("to call Mondy tomorow",               dt(11, 9),      "call Mondy"),
])
def test_parse_reminder_fixes_typos_in_the_time(request_, when, text):
    parsed = parse_reminder(request_, NOW)
    assert (parsed.when, parsed.text) == (when, text)


def test_typos_in_repeats():
    parsed = parse_reminder("evry wensday at 7 to swim", NOW)
    assert (parsed.when, parsed.text) == (dt(14, 7), "swim")
    assert parsed.recurrence.describe(TZ) == "every Wed at 07:00"


def test_words_understood_as_written_are_not_corrected():
    # "sundae" is one typo from "sunday", but the message makes sense as written.
    parsed = parse_reminder("to eat a sundae at 9", NOW)
    assert (parsed.when, parsed.text) == (dt(10, 21), "eat a sundae")


def test_a_misspelled_time_is_not_the_text():
    with pytest.raises(ParseError, match="What should I remind you about?"):
        parse_reminder("tomorow at 9", NOW)


# --- intents --------------------------------------------------------------------

async def noop(update, context, rest):
    pass


CREATE = Intent("reminder.create", ["remind me", "set a reminder", "new reminder"], noop)
LIST = Intent("reminder.list", ["my reminders", "reminders"], noop)
FLAG = Intent("failed.flag", ["that's wrong", "thats wrong", "save the last one as failed"], noop)
INTENTS = [CREATE, LIST, FLAG]


@pytest.mark.parametrize("text, intent, rest", [
    ("remid me tomorrow at 9 to call Mom",  CREATE, "tomorrow at 9 to call Mom"),
    ("Remnd me, in 2 hours to go",          CREATE, "in 2 hours to go"),
    ("please remidn me at 9",               CREATE, "at 9"),
    ("set a remider for friday: dentist",   CREATE, "for friday: dentist"),
    ("my remiders",                         LIST,   ""),
    ("thats wrng",                          FLAG,   ""),
    ("save the last one as faild",          FLAG,   ""),
])
def test_match_with_typos(text, intent, rest):
    m = match_intent(text, INTENTS)
    assert (m.intent, m.rest) == (intent, rest)


@pytest.mark.parametrize("text", [
    "set a reminders",   # "reminders" is a known word: not a typo of "reminder"
    "remindme now",
    "remind",
    "hello there",
    "reminding me",
    "save the lst one as failed",   # "lst": under 4 letters, too short to guess
])
def test_no_match_with_typos(text):
    assert match_intent(text, INTENTS) is None
