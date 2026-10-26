"""Every button: its callback data pattern and its handler.

bot.py registers them with Telegram; the web app (handlers/webapp.py) uses
the same list for the same buttons in its chat.
"""

import re

from    enums                       import Callback, CallbackPrefix, ReminderAction
from    handlers                    import calendar, events, failed, people, reminders, settings
from    handlers.menus              import on_main_menu, on_my_id, on_reminders, on_settings
from    handlers.text               import on_answer
from    handlers.ui                 import exact, prefixed


# rem:<action>:<id>[:<minutes>]; "rem:new" etc. are separate buttons.
REMINDER_BUTTON = (
    "^" + re.escape(CallbackPrefix.REMINDER) + "(?:" + "|".join(ReminderAction) + r"):\d+"
)

BUTTONS = [
    # Main Menu
    (exact(Callback.MAIN_MENU, Callback.SETTINGS_BACK), on_main_menu),
    (exact(Callback.REMINDERS_MENU), on_reminders),
    (exact(Callback.SETTINGS_MENU), on_settings),

    # Settings
    (exact(Callback.MY_ID), on_my_id),
    (exact(Callback.TIMEZONE_SETTINGS), settings.on_timezone_settings),
    (prefixed(CallbackPrefix.TIMEZONE), settings.on_timezone_button),
    (exact(Callback.REMINDER_SETTINGS, Callback.REMINDER_SETTINGS_FROM_MENU, Callback.REMINDER_SETTINGS_RETURN),
     settings.on_reminder_settings),
    (exact(Callback.SNOOZE_SETTINGS), settings.on_snooze_settings),
    (prefixed(CallbackPrefix.SNOOZE_OPTION), settings.on_snooze_button),
    (exact(Callback.REPEAT_SETTINGS), settings.on_repeat_settings),
    (prefixed(CallbackPrefix.REPEAT_OPTION), settings.on_repeat_button),
    (exact(Callback.QUIET_SETTINGS), settings.on_quiet_settings),
    (prefixed(CallbackPrefix.QUIET_OPTION), settings.on_quiet_button),
    (exact(Callback.UPDATES_SETTINGS), settings.on_updates_settings),
    (prefixed(CallbackPrefix.UPDATES_OPTION), settings.on_updates_button),

    # Reminders
    (exact(Callback.NEW_REMINDER), reminders.on_new),
    (exact(Callback.LIST_REMINDERS), reminders.list_reminders),
    (REMINDER_BUTTON, reminders.on_reminder_button),

    # 📅 Events
    (exact(Callback.EVENTS_MENU), events.on_events_menu),
    (exact(Callback.NEW_EVENT), events.on_new),
    (prefixed(CallbackPrefix.EVENT), events.on_event_button),
    (prefixed(CallbackPrefix.ANSWER), on_answer),
    (exact(Callback.PICK_EVENT, Callback.PICK_REMINDER), events.on_pick),

    # 📅 Google Calendar
    (exact(Callback.CALENDAR_SETTINGS), calendar.on_calendar_settings),
    (prefixed(CallbackPrefix.CALENDAR), calendar.on_calendar_button),

    # 👥 People
    (exact(Callback.PEOPLE_MENU), people.on_people_menu),
    (exact(Callback.NEW_INVITE), people.on_new_invite),
    (prefixed(CallbackPrefix.PEOPLE), people.on_people_button),
    (prefixed(CallbackPrefix.INVITE), people.on_invite_button),

    # Failed messages (/failed list)
    (prefixed(CallbackPrefix.FAILED_FIXED), failed.on_failed_button),
    (prefixed(CallbackPrefix.FAILED_IGNORED), failed.on_failed_button),
]


def handler_for(data: str):
    """The handler of the button with this callback data, or None."""
    return next((handler for pattern, handler in BUTTONS if re.match(pattern, data)), None)
