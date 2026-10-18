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


# During a question, these intents count only if the message has the word:
# "cancel the dentist reminder" does, "delete old photos" (an answer) doesn't.
NEEDS_KEYWORD = {
    IntentName.REMINDER_CANCEL: "reminder",
    IntentName.REMINDER_LIST: "reminder",
    IntentName.TIMEZONE_SET: "timezone",
}

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

    if match is not None and awaiting is not None and match.intent.name in NEEDS_KEYWORD \
            and NEEDS_KEYWORD[match.intent.name] not in text.lower():
        # While the bot asks something, "delete old photos" or "what's on the
        # agenda" is an answer, not a command.
        match = None

    # A trigger phrase always wins, so "remind me ..." works at any point.
    if match is not None:
        context.user_data.pop(AWAITING, None)
        asked = context.user_data.pop(ASKED_REQUEST, None)
        context.user_data.pop(PENDING_PART, None)
        if match.intent.name == IntentName.FLAG_FAILED and asked is not None \
                and awaiting in (Awaiting.REMINDER_TEXT, Awaiting.REMINDER_TIME):
            # "that's wrong" while the bot asks for a time or a text: asking was the mistake.
            await rh.flag_question(update, context, asked)
            return
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
