"""Trigger phrases for free-text messages.

A message starting with one of an intent's phrases runs its action with the
rest of the message. Add new phrases or intents here.
"""

from core.intents       import Intent
from enums              import IntentName
from handlers.events    import agenda, cancel, cancel_event, create_event, list_events, move_event, put_in_calendar
from handlers.reminders import create_reminder, flag_last_reminder, list_reminders, remind_someone
from handlers.settings  import set_timezone


INTENTS = [
    Intent(
        name=IntentName.REMINDER_CREATE,
        phrases=[
            "remind me", "set a reminder", "set reminder", "create a reminder",
            "add a reminder", "new reminder",
            "don't let me forget", "dont let me forget", "do not let me forget", "don't forget", "dont forget",
        ],
        action=create_reminder,
    ),
    Intent(
        # "remind anna …" (a contact in 👥 People), or "remind to …" for yourself
        name=IntentName.REMINDER_CREATE,
        phrases=["remind"],
        action=remind_someone,
    ),
    Intent(
        name=IntentName.REMINDER_LIST,
        phrases=[
            "my reminders", "show my reminders", "show reminders", "list reminders",
            "list my reminders", "reminders",
        ],
        action=list_reminders,
    ),
    Intent(
        name=IntentName.REMINDER_AGENDA,
        phrases=[
            "what do i have", "what have i got", "what's on", "whats on", "what is on",
            "do i have anything", "anything on",
        ],
        action=agenda,
    ),
    Intent(
        name=IntentName.REMINDER_CANCEL,
        # "cancel the dentist reminder", or "cancel padel" (an event, if one is
        # called that); handlers/text.py only takes these during a question if
        # "reminder" is in the message.
        phrases=["cancel", "delete", "remove"],
        action=cancel,
    ),
    Intent(
        name=IntentName.EVENT_CREATE,
        phrases=[
            "event", "new event", "add event", "add an event", "add a new event", "create event",
            "create an event", "make an event",
        ],
        action=create_event,
    ),
    Intent(
        # "put padel on thursday at 21:00 in my calendar", "add to my calendar …"
        name=IntentName.EVENT_CREATE,
        phrases=["put", "add"],
        action=put_in_calendar,
    ),
    Intent(
        name=IntentName.EVENT_LIST,
        phrases=[
            "my events", "show my events", "show events", "list events", "list my events", "events",
            "upcoming events", "my calendar", "show my calendar", "what's on my calendar", "whats on my calendar",
            "what is on my calendar", "what's in my calendar", "whats in my calendar",
        ],
        action=list_events,
    ),
    Intent(
        name=IntentName.EVENT_MOVE,
        # "move padel to 20:00"; handlers/text.py only takes it during a
        # question if an event's name follows.
        phrases=["move", "reschedule"],
        action=move_event,
        typos=False,
    ),
    Intent(
        name=IntentName.EVENT_CANCEL,
        phrases=[
            "cancel event", "cancel the event", "delete event", "delete the event", "remove event",
            "remove the event", "cancel my event", "delete my event",
        ],
        action=cancel_event,
    ),
    Intent(
        name=IntentName.TIMEZONE_SET,
        phrases=[
            "set my timezone to", "set timezone to", "change my timezone to", "change timezone to",
            "my timezone is", "set my timezone", "change my timezone",
        ],
        action=set_timezone,
    ),
    Intent(
        name=IntentName.FLAG_FAILED,
        phrases=[
            "save the last one as failed", "save last one as failed", "save that as failed",
            "save it as failed", "save as failed",
            "mark the last one as failed", "mark last one as failed", "mark that as failed",
            "mark it as failed", "mark as failed",
            "that's wrong", "thats wrong", "that is wrong", "that was wrong", "that's not right",
            "you got that wrong", "you got it wrong", "wrong reminder",
        ],
        action=flag_last_reminder,
    ),
]
