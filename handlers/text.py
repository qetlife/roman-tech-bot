"""Typed messages in private chats: trigger phrases, or the answer to a question."""

from    telegram                    import Update
from    telegram.ext                import ContextTypes

from    core.intents                import match_intent
from    enums                       import Awaiting
from    handlers                    import reminders as rh
from    handlers                    import settings as sh
from    handlers.intents            import INTENTS
from    handlers.ui                 import AWAITING, EDIT_REMINDER_ID


HELP_TEXT = (
    "I didn't get that. Try “remind me in 2 hours to call mom”, "
    "“my reminders”, or /menu."
)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plain text in a private chat: trigger phrases, or the answer to a question."""
    text = update.effective_message.text or ""
    match = match_intent(text, INTENTS)
    awaiting = context.user_data.get(AWAITING)

    # A trigger phrase always wins, so "remind me ..." works at any point.
    if match is not None:
        context.user_data.pop(AWAITING, None)
        await match.intent.action(update, context, match.rest)
        return

    if awaiting == Awaiting.REMINDER:
        await rh.create_reminder(update, context, text)
    elif awaiting == Awaiting.TIMEZONE:
        await sh.on_timezone_text(update, context, text)
    elif awaiting == Awaiting.SNOOZE_OPTIONS:
        await sh.on_snooze_text(update, context, text)
    elif awaiting == Awaiting.QUIET_HOURS:
        await sh.on_quiet_text(update, context, text)
    elif awaiting == Awaiting.EDIT:
        await rh.edit_reminder(update, context, context.user_data[EDIT_REMINDER_ID], text)
    else:
        await update.effective_message.reply_text(HELP_TEXT)
