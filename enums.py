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


# --- events -----------------------------------------------------------------

class EventStatus(StrEnum):
    """Stored in events.status."""

    ACTIVE = "active"
    CANCELLED = "cancelled"


class ExternalSource(StrEnum):
    """Where an event is synced with (events.external_source); None for the bot's own. For #22."""

    GOOGLE = "google"


class GoogleStatus(StrEnum):
    """Stored in google_accounts.status."""

    LINKED = "linked"
    EXPIRED = "expired"     # Google refused the login (expired after 7 days in testing, or revoked): link again


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
    GOOGLE = "google"   # events.source: imported from Google Calendar, not made from a message


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
    EVENT_CREATE = "event.create"       # "event padel on thursday at 21:00", "put … in my calendar"
    EVENT_EDIT = "event.edit"           # the answer to ✏️ Edit on an event, not a trigger phrase
    EVENT_WHEN = "event.when"           # the answer to "when is it?", not a trigger phrase
    EVENT_LIST = "event.list"           # "my events", "what's on my calendar"
    EVENT_MOVE = "event.move"           # "move padel to 20:00", "padel is at 20:00 now"
    EVENT_CANCEL = "event.cancel"       # "cancel event padel" (plain "cancel padel" too)
    SKILLS = "skills"                   # "what can you do?"


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
    EVENT = "event"                     # 📅 ➕ New: time and title of a new event
    EVENT_TITLE = "event_title"         # what the event is, for a time already given
    EVENT_TIME = "event_time"           # when the event is, for a title already given
    EVENT_EDIT = "event_edit"           # ✏️ Edit on an event: new time and title
    REMINDER_CLOCK = "reminder_clock"   # what time, for a reminder with only a day ("friday dentist")
    REMINDER_DAY = "reminder_day"       # which day, for "every week" without one
    EVENT_DAY = "event_day"             # which day, for an event "every week" without one


class ItemKind(StrEnum):
    """What "it" / "the second one" is in a conversation (core/conversation.py)."""

    REMINDER = "reminder"
    EVENT = "event"


class Skill(StrEnum):
    """What the assistant can do (core/skills.py): the web app's home and "what can you do?"."""

    REMINDERS = "reminders"
    EVENTS = "events"
    PEOPLE = "people"
    CALENDAR = "calendar"       # Google Calendar sync, only where it's set up


class Block(StrEnum):
    """A part of the web app's briefing (handlers/webapp.py, /api/briefing)."""

    TODAY = "today"             # what's left today, and how tomorrow starts


class CardKind(StrEnum):
    """The result card of a reply in the web app (handlers/report.py)."""

    REMINDER = "reminder"
    EVENT = "event"


class FollowUp(StrEnum):
    """What a message about the last thing (or a listed one) asks: "move it to 10", "cancel that"."""

    MOVE = "move"       # "move it to 10", "make it 9:30", "change the second one to friday"
    CANCEL = "cancel"   # "cancel that", "delete it", "remove the first one"
    COPY = "copy"       # "and the same next week", "also on thursday"


class AnswerKind(StrEnum):
    """Buttons that answer the bot's question (ans:<kind>:<value>)."""

    CLOCK = "clock"     # ans:clock:<HHMM>: what time
    DAY = "day"         # ans:day:<0-6, Monday = 0>: which day of the week


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
    EVENTS_MENU = "menu:events"         # 📅 Events: the list

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
    UPDATES_SETTINGS = "settings:updates"               # 📣 Updates from people
    CALENDAR_SETTINGS = "settings:calendar"             # 📅 Google Calendar

    # ⏰ Reminders
    NEW_REMINDER = "rem:new"
    LIST_REMINDERS = "rem:list"
    REMINDER_SETTINGS_FROM_MENU = "rem:settings"        # from the ⏰ Reminders menu
    REMINDER_SETTINGS_RETURN = "rset:show"              # back from a reminder setting

    # 📅 Events
    NEW_EVENT = "event:new"
    PICK_EVENT = "pick:event"           # "padel on thursday at 21:00" without a keyword: an event…
    PICK_REMINDER = "pick:reminder"     # … or a reminder


class CallbackPrefix(StrEnum):
    """Buttons whose callback data carries a value after the prefix."""

    REMINDER = "rem:"           # rem:<ReminderAction>:<reminder id>[:<snooze minutes>]
    TIMEZONE = "tz:"            # tz:<IANA name>
    SNOOZE_OPTION = "snzopt:"   # snzopt:<OptionAction>[:<minutes,minutes>]
    REPEAT_OPTION = "rptopt:"   # rptopt:set:<minutes>
    QUIET_OPTION = "qhopt:"     # qhopt:<OptionAction>[:<HH:MM-HH:MM>]
    UPDATES_OPTION = "updopt:"  # updopt:<OptionAction.ON|OFF>
    FAILED_FIXED = "failfix:"   # failfix:<failed message id>, on the /failed list
    FAILED_IGNORED = "failign:" # failign:<failed message id>, on the /failed list
    PEOPLE = "ppl:"             # ppl:<PeopleAction>:<contact id>
    INVITE = "inv:"             # inv:<PeopleAction.ALLOW|DECLINE>:<invite token>
    EVENT = "evt:"              # evt:<EventAction>:<event id>[:<value>]
    CALENDAR = "gcal:"          # gcal:<CalendarAction>[:<google_calendars id, or "all">]
    ANSWER = "ans:"             # ans:<AnswerKind>:<value>: an answer to the bot's question


class ReminderAction(StrEnum):
    """Buttons on a reminder message."""

    OK = "ok"
    SNOOZE = "snz"
    UNDO = "undo"
    EDIT = "edit"
    DELETE = "del"
    WRONG = "wrong"     # 👎 Wrong: save as a failed message and delete the reminder
    RESTORE = "back"    # ↩️ Undo after “cancel it”: the reminder is back


class EventAction(StrEnum):
    """Buttons on an event (evt:<action>:<event id>[:<value>])."""

    OPEN = "open"       # its screen in 📅 Events
    REMIND = "rem"      # evt:rem:<id>:<minutes, negative = before>: add a reminder
    ONCE = "once"       # a reminder on a repeating event: just the next one…
    EVERY = "every"     # … or every time
    UNDO = "undo"
    EDIT = "edit"
    WRONG = "wrong"     # 👎 Wrong: save as a failed message and cancel the event
    SKIP = "skip"       # evt:skip:<id>:<occurrence, YYYYMMDDTHHMMZ>: one occurrence of a repeating event doesn't happen
    CANCEL = "del"      # cancel the event (every occurrence) and its reminders


class CalendarAction(StrEnum):
    """Buttons on ⚙️ Settings → 📅 Calendar (gcal:<action>[:<value>])."""

    TOGGLE = "tgl"      # gcal:tgl:<id>: sync this calendar or stop
    DEFAULT = "def"     # new events go to the next synced calendar
    SYNC = "sync"       # 🔄 Sync now
    UNLINK = "unl"      # 🔓 Unlink: asks what to do with the imported events
    KEEP = "keep"       # gcal:keep:<id|all>: stop syncing, keep its events in the bot
    REMOVE = "rm"       # gcal:rm:<id|all>: stop syncing, remove its events from the bot


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
    ON = "on"
