"""Callback data must never change: buttons already sent to users still carry it."""

import re

import pytest

from enums import AnswerKind, Callback, CalendarAction, CallbackPrefix, EventAction, OptionAction, PeopleAction, ReminderAction
from handlers.calendar import calendar_callback
from handlers.people import people_callback
from handlers.ui import event_callback, exact, option_callback, prefixed, reminder_callback, split_option


def test_fixed_values_are_stable():
    assert {c.name: c.value for c in Callback} == {
        "MAIN_MENU": "menu:main",
        "REMINDERS_MENU": "menu:reminders",
        "SETTINGS_MENU": "menu:settings",
        "PEOPLE_MENU": "menu:people",
        "EVENTS_MENU": "menu:events",
        "NEW_INVITE": "people:invite",
        "MY_ID": "settings:my_id",
        "SETTINGS_BACK": "settings:back",
        "TIMEZONE_SETTINGS": "settings:timezone",
        "REMINDER_SETTINGS": "settings:reminders",
        "SNOOZE_SETTINGS": "settings:snooze",
        "REPEAT_SETTINGS": "settings:repeat",
        "QUIET_SETTINGS": "settings:quiet",
        "UPDATES_SETTINGS": "settings:updates",
        "CALENDAR_SETTINGS": "settings:calendar",
        "NEW_REMINDER": "rem:new",
        "LIST_REMINDERS": "rem:list",
        "REMINDER_SETTINGS_FROM_MENU": "rem:settings",
        "REMINDER_SETTINGS_RETURN": "rset:show",
        "NEW_EVENT": "event:new",
        "PICK_EVENT": "pick:event",
        "PICK_REMINDER": "pick:reminder",
    }


@pytest.mark.parametrize("built, expected", [
    (reminder_callback(ReminderAction.OK, 5),               "rem:ok:5"),
    (reminder_callback(ReminderAction.SNOOZE, 5, 10),       "rem:snz:5:10"),
    (reminder_callback(ReminderAction.UNDO, 5),             "rem:undo:5"),
    (reminder_callback(ReminderAction.EDIT, 5),             "rem:edit:5"),
    (reminder_callback(ReminderAction.DELETE, 5),           "rem:del:5"),
    (reminder_callback(ReminderAction.WRONG, 5),            "rem:wrong:5"),
    (reminder_callback(ReminderAction.RESTORE, 5),          "rem:back:5"),
    (f"{CallbackPrefix.ANSWER}{AnswerKind.CLOCK}:0900",     "ans:clock:0900"),
    (f"{CallbackPrefix.ANSWER}{AnswerKind.DAY}:0",          "ans:day:0"),
    (f"{CallbackPrefix.FAILED_FIXED}7",                     "failfix:7"),
    (option_callback(CallbackPrefix.SNOOZE_OPTION, OptionAction.SET, "10,60"),     "snzopt:set:10,60"),
    (option_callback(CallbackPrefix.SNOOZE_OPTION, OptionAction.CUSTOM),           "snzopt:custom"),
    (option_callback(CallbackPrefix.REPEAT_OPTION, OptionAction.SET, 5),           "rptopt:set:5"),
    (option_callback(CallbackPrefix.QUIET_OPTION, OptionAction.SET, "00:00-07:00"), "qhopt:set:00:00-07:00"),
    (option_callback(CallbackPrefix.QUIET_OPTION, OptionAction.OFF),               "qhopt:off"),
    (option_callback(CallbackPrefix.UPDATES_OPTION, OptionAction.ON),              "updopt:on"),
    (option_callback(CallbackPrefix.UPDATES_OPTION, OptionAction.OFF),             "updopt:off"),
    (f"{CallbackPrefix.TIMEZONE}Europe/Kyiv",               "tz:Europe/Kyiv"),
    (people_callback(PeopleAction.OPEN, 3),                 "ppl:open:3"),
    (people_callback(PeopleAction.SENDER, 3),               "ppl:sender:3"),
    (people_callback(PeopleAction.RENAME, 3),               "ppl:ren:3"),
    (people_callback(PeopleAction.REMOVE, 3),               "ppl:del:3"),
    (people_callback(PeopleAction.STOP, 3),                 "ppl:stop:3"),
    (people_callback(PeopleAction.ALLOW, 3),                "ppl:yes:3"),
    (people_callback(PeopleAction.DECLINE, 3),              "ppl:no:3"),
    (f"{CallbackPrefix.INVITE}{PeopleAction.ALLOW}:abc",    "inv:yes:abc"),
    (event_callback(EventAction.OPEN, 4),                   "evt:open:4"),
    (event_callback(EventAction.REMIND, 4, -30),            "evt:rem:4:-30"),
    (event_callback(EventAction.ONCE, 4),                   "evt:once:4"),
    (event_callback(EventAction.EVERY, 4),                  "evt:every:4"),
    (event_callback(EventAction.UNDO, 4),                   "evt:undo:4"),
    (event_callback(EventAction.EDIT, 4),                   "evt:edit:4"),
    (event_callback(EventAction.WRONG, 4),                  "evt:wrong:4"),
    (event_callback(EventAction.SKIP, 4, "20261029T2000Z"), "evt:skip:4:20261029T2000Z"),
    (event_callback(EventAction.CANCEL, 4),                 "evt:del:4"),
    (calendar_callback(CalendarAction.TOGGLE, 6),           "gcal:tgl:6"),
    (calendar_callback(CalendarAction.DEFAULT),             "gcal:def"),
    (calendar_callback(CalendarAction.SYNC),                "gcal:sync"),
    (calendar_callback(CalendarAction.UNLINK),              "gcal:unl"),
    (calendar_callback(CalendarAction.KEEP, "all"),         "gcal:keep:all"),
    (calendar_callback(CalendarAction.REMOVE, 6),           "gcal:rm:6"),
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
