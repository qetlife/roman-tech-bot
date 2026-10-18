"""Contact names (core/contacts.py)."""

import pytest

from core.contacts import clean_name, default_name, unique_name


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
