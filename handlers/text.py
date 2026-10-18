"""Typed (and transcribed) messages in private chats: trigger phrases, or the answer to a question."""

from    telegram                    import Update
from    telegram.ext                import ContextTypes

from    core.intents                import match_intent
from    enums                       import Awaiting, IntentName
from    handlers.failed             import record_not_understood
from    handlers                    import reminders as rh
from    handlers                    import settings as sh
from    handlers.intents            import INTENTS
from    handlers.ui                 import ASKED_REQUEST, AWAITING, EDIT_REMINDER_ID, PENDING_PART


HELP_TEXT = (
    "I didn't get that. Try “remind me in 2 hours to call mom”, "
    "“my reminders”, or /menu."
)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plain text in a private chat."""
    await handle_text(update, context, update.effective_message.text or "")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Trigger phrases, or the answer to a question. Also used for transcribed voice messages."""
    match = match_intent(text, INTENTS)
    awaiting = context.user_data.get(AWAITING)

    # A trigger phrase always wins, so "remind me ..." works at any point.
    if match is not None:
        context.user_data.pop(AWAITING, None)
        # A question for a missing time or text is dropped, unless this says
        # "that's wrong" about it.
        if match.intent.name != IntentName.FLAG_FAILED:
            context.user_data.pop(ASKED_REQUEST, None)
            context.user_data.pop(PENDING_PART, None)
        await match.intent.action(update, context, match.rest)
        return

    if awaiting == Awaiting.REMINDER:
        await rh.create_reminder(update, context, text)
    elif awaiting == Awaiting.REMINDER_TEXT:
        await rh.answer_what(update, context, text)
    elif awaiting == Awaiting.REMINDER_TIME:
        await rh.answer_when(update, context, text)
    elif awaiting == Awaiting.TIMEZONE:
        await sh.on_timezone_text(update, context, text)
    elif awaiting == Awaiting.SNOOZE_OPTIONS:
        await sh.on_snooze_text(update, context, text)
    elif awaiting == Awaiting.QUIET_HOURS:
        await sh.on_quiet_text(update, context, text)
    elif awaiting == Awaiting.EDIT:
        await rh.edit_reminder(update, context, context.user_data[EDIT_REMINDER_ID], text)
    elif rh.is_bare_time(update, text):
        # "tomorrow at 12" on its own: a reminder without its text yet.
        await rh.create_reminder(update, context, text)
    else:
        record_not_understood(update, context, text)
        await update.effective_message.reply_text(HELP_TEXT)
