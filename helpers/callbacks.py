"""Callback data of every inline button, in one place.

The values are what Telegram sends back when a button is pressed. Don't
change them: buttons on messages already in users' chats still carry the
old value.
"""

import re

from enum   import StrEnum


class Callback(StrEnum):
    """Buttons whose callback data is fixed."""

    # Main menu
    MAIN_MENU = "menu:main"
    REMINDERS_MENU = "menu:reminders"
    SETTINGS_MENU = "menu:settings"

    # ⚙️ Settings
    MY_ID = "settings:my_id"
    SETTINGS_BACK = "settings:back"
    TIMEZONE_SETTINGS = "settings:timezone"
    REMINDER_SETTINGS = "settings:reminders"            # from ⚙️ Settings
    SNOOZE_SETTINGS = "settings:snooze"
    REPEAT_SETTINGS = "settings:repeat"
    QUIET_SETTINGS = "settings:quiet"

    # ⏰ Reminders
    NEW_REMINDER = "rem:new"
    LIST_REMINDERS = "rem:list"
    REMINDER_SETTINGS_FROM_MENU = "rem:settings"        # from the ⏰ Reminders menu
    REMINDER_SETTINGS_RETURN = "rset:show"              # back from a reminder setting


class CallbackPrefix(StrEnum):
    """Buttons whose callback data carries a value after the prefix."""

    REMINDER = "rem:"           # rem:<ReminderAction>:<reminder id>[:<snooze minutes>]
    TIMEZONE = "tz:"            # tz:<IANA name>
    SNOOZE_OPTION = "snzopt:"   # snzopt:<OptionAction>[:<minutes,minutes>]
    REPEAT_OPTION = "rptopt:"   # rptopt:set:<minutes>
    QUIET_OPTION = "qhopt:"     # qhopt:<OptionAction>[:<HH:MM-HH:MM>]


class ReminderAction(StrEnum):
    """Buttons on a reminder message."""

    OK = "ok"
    SNOOZE = "snz"
    UNDO = "undo"
    EDIT = "edit"
    DELETE = "del"


class OptionAction(StrEnum):
    """Buttons on a setting screen."""

    SET = "set"
    CUSTOM = "custom"
    DEFAULT = "default"
    OFF = "off"


def reminder_callback(action: ReminderAction, reminder_id: int, *args) -> str:
    return ":".join([f"{CallbackPrefix.REMINDER}{action}", str(reminder_id), *map(str, args)])


def option_callback(prefix: CallbackPrefix, action: OptionAction, value: str = None) -> str:
    return f"{prefix}{action}" + (f":{value}" if value is not None else "")


def split_option(data: str, prefix: CallbackPrefix):
    """"snzopt:set:10,60" -> (OptionAction.SET, "10,60")."""
    action, _, value = data.removeprefix(prefix).partition(":")
    return OptionAction(action), value


def exact(*callbacks: Callback) -> str:
    """Handler pattern matching exactly these callbacks."""
    return "^(?:" + "|".join(re.escape(c) for c in callbacks) + ")$"


def prefixed(prefix: CallbackPrefix) -> str:
    """Handler pattern matching every callback with this prefix."""
    return "^" + re.escape(prefix)
