"""Callback data must never change: buttons already sent to users still carry it."""

import re

import pytest

from enums import Callback, CallbackPrefix, OptionAction, ReminderAction
from helpers.callbacks import exact, option_callback, prefixed, reminder_callback, split_option


def test_fixed_values_are_stable():
    assert {c.name: c.value for c in Callback} == {
        "MAIN_MENU": "menu:main",
        "REMINDERS_MENU": "menu:reminders",
        "SETTINGS_MENU": "menu:settings",
        "MY_ID": "settings:my_id",
        "SETTINGS_BACK": "settings:back",
        "TIMEZONE_SETTINGS": "settings:timezone",
        "REMINDER_SETTINGS": "settings:reminders",
        "SNOOZE_SETTINGS": "settings:snooze",
        "REPEAT_SETTINGS": "settings:repeat",
        "QUIET_SETTINGS": "settings:quiet",
        "NEW_REMINDER": "rem:new",
        "LIST_REMINDERS": "rem:list",
        "REMINDER_SETTINGS_FROM_MENU": "rem:settings",
        "REMINDER_SETTINGS_RETURN": "rset:show",
    }


@pytest.mark.parametrize("built, expected", [
    (reminder_callback(ReminderAction.OK, 5),               "rem:ok:5"),
    (reminder_callback(ReminderAction.SNOOZE, 5, 10),       "rem:snz:5:10"),
    (reminder_callback(ReminderAction.UNDO, 5),             "rem:undo:5"),
    (reminder_callback(ReminderAction.EDIT, 5),             "rem:edit:5"),
    (reminder_callback(ReminderAction.DELETE, 5),           "rem:del:5"),
    (option_callback(CallbackPrefix.SNOOZE_OPTION, OptionAction.SET, "10,60"),     "snzopt:set:10,60"),
    (option_callback(CallbackPrefix.SNOOZE_OPTION, OptionAction.CUSTOM),           "snzopt:custom"),
    (option_callback(CallbackPrefix.REPEAT_OPTION, OptionAction.SET, 5),           "rptopt:set:5"),
    (option_callback(CallbackPrefix.QUIET_OPTION, OptionAction.SET, "00:00-07:00"), "qhopt:set:00:00-07:00"),
    (option_callback(CallbackPrefix.QUIET_OPTION, OptionAction.OFF),               "qhopt:off"),
    (f"{CallbackPrefix.TIMEZONE}Europe/Kyiv",               "tz:Europe/Kyiv"),
])
def test_built_values_are_stable(built, expected):
    assert built == expected


def test_split_option():
    assert split_option("qhopt:set:00:00-07:00", CallbackPrefix.QUIET_OPTION) == (OptionAction.SET, "00:00-07:00")
    assert split_option("snzopt:default", CallbackPrefix.SNOOZE_OPTION) == (OptionAction.DEFAULT, "")


def test_patterns():
    assert re.match(exact(Callback.MAIN_MENU), "menu:main")
    assert not re.match(exact(Callback.MAIN_MENU), "menu:main2")
    assert re.match(prefixed(CallbackPrefix.QUIET_OPTION), "qhopt:off")


def test_reminder_button_pattern_skips_menu_buttons(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite://")
    import bot

    assert re.match(bot.REMINDER_BUTTON, "rem:snz:5:10")
    for data in ("rem:new", "rem:list", "rem:settings"):
        assert not re.match(bot.REMINDER_BUTTON, data)
