"""Trigger phrases for free-text messages.

A message starting with one of an intent's phrases runs its action with the
rest of the message. Add new phrases or intents here.
"""

from core.intents       import Intent
from handlers.reminders import create_reminder, list_reminders


INTENTS = [
    Intent(
        name="reminder.create",
        phrases=[
            "remind me", "set a reminder", "set reminder", "create a reminder",
            "add a reminder", "new reminder",
        ],
        action=create_reminder,
    ),
    Intent(
        name="reminder.list",
        phrases=[
            "my reminders", "show my reminders", "show reminders", "list reminders",
            "list my reminders", "reminders",
        ],
        action=list_reminders,
    ),
]
