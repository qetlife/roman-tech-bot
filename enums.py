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


class ReplyCommand(StrEnum):
    """What a reply to a reminder message asks for (core/replies.py)."""

    DONE = "done"           # "done", "ok": like ✅ OK
    SNOOZE = "snooze"       # "snooze 20 min", "later"
    MOVE = "move"           # "move it to 10", "change to tomorrow at 9"
    CANCEL = "cancel"       # "cancel", "delete it"


# --- contacts ---------------------------------------------------------------

class ContactStatus(StrEnum):
    """Stored in contacts.status."""

    PENDING = "pending"     # asked by @username, not answered yet
    ACCEPTED = "accepted"   # the contact allowed it: reminders can be sent
    DECLINED = "declined"   # said ❌ No to a request: not asked again for a while (REQUEST_COOLDOWN)


class RequestResult(StrEnum):
    """What asking someone by @username did (ContactRepository.request)."""

    ASKED = "asked"
    EXISTS = "exists"       # already a contact, or asked and not answered
    DECLINED = "declined"   # they said no recently
    RECENT = "recent"       # asked them in the last day already (then cancelled)
    TOO_MANY = "too_many"   # REQUESTS_PER_DAY reached


class InviteResult(StrEnum):
    """What opening an invite link did (ContactRepository.use_invite)."""

    ACCEPTED = "accepted"   # now a contact of the inviter
    ALREADY = "already"     # was one already
    OWN = "own"             # the inviter opened their own link
    USED = "used"           # someone already used it
    EXPIRED = "expired"
    UNKNOWN = "unknown"     # no such invite


# --- failed messages --------------------------------------------------------

class MessageSource(StrEnum):
    """How a message reached the bot. Stored in reminders.source and failed_messages.source."""

    TYPED = "typed"
    VOICE = "voice"     # transcribed by the speech-service


class FailureReason(StrEnum):
    """Stored in failed_messages.reason."""

    NOT_UNDERSTOOD = "not_understood"   # the bot replied that it didn't understand
    WRONG_RESULT = "wrong_result"       # the user flagged what the bot made of it (👎 Wrong)


class FailureStatus(StrEnum):
    """Stored in failed_messages.status."""

    OPEN = "open"           # waiting for the parser to learn it
    FIXED = "fixed"
    IGNORED = "ignored"     # can't or shouldn't be learned (e.g. a garbled transcript); `note` says why


# --- conversation -----------------------------------------------------------

class IntentName(StrEnum):
    """Free-text intents (handlers/intents.py); also stored in failed_messages.intent."""

    REMINDER_CREATE = "reminder.create"
    REMINDER_EDIT = "reminder.edit"     # the answer to ✏️ Edit, not a trigger phrase
    REMINDER_WHEN = "reminder.when"     # the answer to "when should I remind you?", not a trigger phrase
    REMINDER_LIST = "reminder.list"     # also "my reminders on friday"
    REMINDER_AGENDA = "reminder.agenda" # "what do I have tomorrow?"
    REMINDER_CANCEL = "reminder.cancel" # "cancel the dentist reminder"
    TIMEZONE_SET = "settings.timezone"  # "set my timezone to Lisbon"
    FLAG_FAILED = "failed.flag"         # "that's wrong", "save the last one as failed"



class Awaiting(StrEnum):
    """What the user's next plain message answers (context.user_data["awaiting"])."""

    REMINDER = "reminder"               # ➕ New: time and text of a new reminder
    REMINDER_TEXT = "reminder_text"     # what to remind about, for a time already given
    REMINDER_TIME = "reminder_time"     # when to remind, for a text already given
    EDIT = "edit"                       # ✏️ Edit: new time and text
    TIMEZONE = "timezone"               # a city or offset
    SNOOZE_OPTIONS = "snooze_options"   # custom snooze options
    QUIET_HOURS = "quiet_hours"         # custom quiet hours
    CONTACT_USERNAME = "contact_username"   # 👥 ➕ Invite: the @username of someone already using the bot
    CONTACT_NAME = "contact_name"       # 👥 ✏️ Rename: a contact's new name


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
    PEOPLE_MENU = "menu:people"

    # 👥 People
    NEW_INVITE = "people:invite"

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
    FAILED_FIXED = "failfix:"   # failfix:<failed message id>, on the /failed list
    FAILED_IGNORED = "failign:" # failign:<failed message id>, on the /failed list
    PEOPLE = "ppl:"             # ppl:<PeopleAction>:<contact id>
    INVITE = "inv:"             # inv:<PeopleAction.ALLOW|DECLINE>:<invite token>


class ReminderAction(StrEnum):
    """Buttons on a reminder message."""

    OK = "ok"
    SNOOZE = "snz"
    UNDO = "undo"
    EDIT = "edit"
    DELETE = "del"
    WRONG = "wrong"     # 👎 Wrong: save as a failed message and delete the reminder


class PeopleAction(StrEnum):
    """Buttons in 👥 People, and on an invite or a request."""

    OPEN = "open"           # a contact's screen (someone you can remind)
    SENDER = "sender"       # a sender's screen (someone who can remind you)
    RENAME = "ren"
    REMOVE = "del"          # the owner removes a contact (or cancels a request)
    STOP = "stop"           # the contact stops a sender
    ALLOW = "yes"           # answer to an invite or a request
    DECLINE = "no"


class OptionAction(StrEnum):
    """Buttons on a setting screen."""

    SET = "set"
    CUSTOM = "custom"
    DEFAULT = "default"
    OFF = "off"
