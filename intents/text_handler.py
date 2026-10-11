from    telegram                    import Update
from    telegram.ext                import ContextTypes

from    intents.registry            import INTENTS
from    intents.router              import match_intent
from    reminders                   import handlers as rh
from    settings                    import handlers as sh


HELP_TEXT = (
    "I didn't get that. Try “remind me in 2 hours to call mom”, "
    "“my reminders”, or /menu."
)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plain text in a private chat: trigger phrases, or the answer to a question."""
    text = update.effective_message.text or ""
    match = match_intent(text, INTENTS)
    awaiting = context.user_data.get("awaiting")

    # A trigger phrase always wins, so "remind me ..." works at any point.
    if match is not None:
        context.user_data.pop("awaiting", None)
        await match.intent.action(update, context, match.rest)
        return

    if awaiting == rh.AWAIT_REMINDER:
        await rh.create_reminder(update, context, text)
    elif awaiting == rh.AWAIT_TIMEZONE:
        await rh.on_timezone_text(update, context, text)
    elif awaiting == sh.AWAIT_SNOOZE_OPTIONS:
        await sh.on_snooze_text(update, context, text)
    elif awaiting and awaiting.startswith(rh.AWAIT_EDIT):
        await rh.edit_reminder(update, context, int(awaiting[len(rh.AWAIT_EDIT):]), text)
    else:
        await update.effective_message.reply_text(HELP_TEXT)
