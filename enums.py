"""Every enum in the bot, in one place.

StrEnum members compare equal to their string values, so stored data and
callback data stay plain strings. Weekdays use the standard library's
calendar.Day.
"""

from enum   import Enum, StrEnum


# --- reminders --------------------------------------------------------------

class ReminderStatus(StrEnum):
    """Stored in reminders.status (as the value)."""

    PENDING = "pending"     # waiting for remind_at
    FIRING = "firing"       # sent, re-sent every few minutes until acknowledged
    DONE = "done"           # user pressed OK
    CANCELLED = "cancelled"
    MISSED = "missed"       # no OK within the give-up window
    FAILED = "failed"       # could not be delivered (e.g. the user blocked the bot)


# Reminders the delivery loop still works on.
ACTIVE_STATUSES = (ReminderStatus.PENDING, ReminderStatus.FIRING)


class RepeatKind(Enum):
    """The kind of repeat the parser found."""

    WEEKLY = "weekly"       # on weekdays: "every day", "mondays"
    MONTHLY = "monthly"     # on a day of the month: "every 15th"
    INTERVAL = "interval"   # every N minutes/hours/days: "every 2 hours"


# --- conversation -----------------------------------------------------------

class Awaiting(StrEnum):
    """What the user's next plain message answers (context.user_data["awaiting"])."""

    REMINDER = "reminder"               # ➕ New: time and text of a new reminder
    EDIT = "edit"                       # ✏️ Edit: new time and text
    TIMEZONE = "timezone"               # a city or offset
    SNOOZE_OPTIONS = "snooze_options"   # custom snooze options
    QUIET_HOURS = "quiet_hours"         # custom quiet hours


# --- buttons ----------------------------------------------------------------
# Callback data is what Telegram sends back when a button is pressed. Don't
# change existing values: buttons on messages already in users' chats still
# carry them (tests/test_callbacks.py pins them). Helpers to build and match
# them are in helpers/callbacks.py.

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
