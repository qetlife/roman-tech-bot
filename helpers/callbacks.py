"""Build, read and match callback data.

The values themselves are the Callback, CallbackPrefix, ReminderAction and
OptionAction enums in enums.py.
"""

import re

from enums  import Callback, CallbackPrefix, OptionAction, ReminderAction


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
