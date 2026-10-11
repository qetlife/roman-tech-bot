"""What the user's next plain message answers.

Stored in context.user_data["awaiting"] after the bot asks a question.
"""

from enum   import StrEnum


AWAITING = "awaiting"
# For Awaiting.EDIT: the id of the reminder being edited.
EDIT_REMINDER_ID = "edit_reminder_id"


class Awaiting(StrEnum):
    REMINDER = "reminder"               # ➕ New: time and text of a new reminder
    EDIT = "edit"                       # ✏️ Edit: new time and text
    TIMEZONE = "timezone"               # a city or offset
    SNOOZE_OPTIONS = "snooze_options"   # custom snooze options
    QUIET_HOURS = "quiet_hours"         # custom quiet hours
