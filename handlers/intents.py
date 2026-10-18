"""Trigger phrases for free-text messages.

A message starting with one of an intent's phrases runs its action with the
rest of the message. Add new phrases or intents here.
"""

from core.intents       import Intent
from enums              import IntentName
from handlers.reminders import create_reminder, flag_last_reminder, list_reminders


INTENTS = [
    Intent(
        name=IntentName.REMINDER_CREATE,
        phrases=[
            "remind me", "remind", "set a reminder", "set reminder", "create a reminder",
            "add a reminder", "new reminder",
            "don't let me forget", "dont let me forget", "do not let me forget", "don't forget", "dont forget",
        ],
        action=create_reminder,
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
