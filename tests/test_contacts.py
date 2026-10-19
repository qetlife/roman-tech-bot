"""Contact names (core/contacts.py)."""

from datetime      import datetime
from zoneinfo      import ZoneInfo

import pytest

from core.contacts import clean_name, default_name, split_name, unique_name, unknown_name


@pytest.mark.parametrize("text, name", [
    ("  Aunt  Mary ",   "Aunt Mary"),
    ("@anna",           "anna"),
    ("Anna-Lisa",       "Anna-Lisa"),
    ("O'Brien",         "O'Brien"),
    ("Олена",           "Олена"),
    ("me",              None),      # means yourself
    ("Me",              None),
    ("9lives",          None),      # must start with a letter
    ("x" * 33,          None),      # too long
    ("",                None),
    ("anna!",           None),
])
def test_clean_name(text, name):
    assert clean_name(text) == name


def test_unique_name():
    assert unique_name("Anna", []) == "Anna"
    assert unique_name("Anna", ["anna"]) == "Anna 2"
    assert unique_name("Anna", ["Anna", "anna 2"]) == "Anna 3"


@pytest.mark.parametrize("first_name, username, name", [
    ("Anna", "anna_b", "Anna"),
    (None, "anna_b", "anna_b"),
    ("🙂", None, "Contact"),
    (None, None, "Contact"),
])
def test_default_name(first_name, username, name):
    assert default_name(first_name, username) == name


# --- "remind anna …" -----------------------------------------------------------

@pytest.mark.parametrize("text, found", [
    ("anna tomorrow at 9 to call", ("anna", "tomorrow at 9 to call")),
    ("Anna, call mom", ("anna", "call mom")),
    ("aunt mary: call", ("Aunt Mary", "call")),
    ("anna 2 to call", ("anna 2", "to call")),       # the longest name wins
    ("annabel to call", None),
    ("anna's birthday tomorrow", None),
    ("to call anna", None),
])
def test_split_name(text, found):
    assert split_name(text, ["anna", "anna 2", "Aunt Mary"]) == found


@pytest.mark.parametrize("text, name", [
    ("bob to bring the keys", "bob"),
    ("bob tomorrow at 9 to bring the keys", "bob"),
    ("bob, bring the keys at 5", "bob"),
    ("@bob tomorrow at 9 to call", "@bob"),
    ("call mom tomorrow at 9", None),       # a reminder as it is
    ("to call mom at 5", None),
    ("tomorrow to pay rent", None),
    ("tomorow to pay rent", None),          # a typo of a time word
    ("friday to call", None),
    ("in 2 hours to stretch", None),
    ("every day at 9 to take pills", None),
    ("me to call", None),
    ("bob", None),
])
def test_unknown_name(text, name):
    now = datetime(2026, 10, 19, 12, tzinfo=ZoneInfo("Europe/Lisbon"))
    assert unknown_name(text, now) == name
