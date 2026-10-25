"""Typed (and transcribed) messages in private chats: trigger phrases, or the answer to a question."""

from    telegram                    import Update
from    telegram.ext                import ContextTypes

from    core.intents                import match_intent
from    enums                       import Awaiting, IntentName
from    handlers.failed             import record_not_understood
from    handlers                    import calendar
from    handlers                    import events as ev
from    handlers                    import reminders as rh
from    handlers.replies            import handle_reply
from    handlers                    import people
from    handlers                    import settings as sh
from    handlers.intents            import INTENTS
from    handlers.ui                 import (
    ASKED_REQUEST, AWAITING, EDIT_EVENT_ID, EDIT_REMINDER_ID, PENDING_CONTACT_ID, PENDING_PART,
)


# During a question, these intents count only if the message has one of the
# words: "cancel the dentist reminder" does, "delete old photos" (an answer)
# doesn't. "move" counts only if an event's name follows (events.names_event).
NEEDS_KEYWORD = {
    IntentName.REMINDER_CANCEL: ("reminder",),
    IntentName.REMINDER_LIST: ("reminder",),
    IntentName.REMINDER_AGENDA: ("reminder",),
    IntentName.TIMEZONE_SET: ("timezone",),
    IntentName.EVENT_CREATE: ("event", "calendar"),
    IntentName.EVENT_LIST: ("event", "calendar"),
}

# A question about a reminder or an event's missing half: "that's wrong" then means the asking.
QUESTIONS = {
    Awaiting.REMINDER_TEXT: IntentName.REMINDER_CREATE,
    Awaiting.REMINDER_TIME: IntentName.REMINDER_CREATE,
    Awaiting.EVENT_TITLE: IntentName.EVENT_CREATE,
    Awaiting.EVENT_TIME: IntentName.EVENT_CREATE,
}

HELP_TEXT = (
    "I didn't get that. Try “remind me in 2 hours to call mom”, "
    "“event padel on thursday at 21:00”, “my reminders”, or /menu."
)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plain text in a private chat."""
    await handle_text(update, context, update.effective_message.text or "")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Trigger phrases, or the answer to a question. Also used for transcribed voice messages."""
    # Anything may be about reminders or events: bring in Google Calendar's changes first (every 5 minutes at most)
    await calendar.maybe_sync(context.bot, update.effective_user.id)
    # "done", "snooze 20 min" … as a reply to a reminder message
    if await handle_reply(update, context, text):
        return
    match = match_intent(text, INTENTS)
    awaiting = context.user_data.get(AWAITING)

    if match is not None and awaiting is not None and match.intent.name in NEEDS_KEYWORD \
            and not any(word in text.lower() for word in NEEDS_KEYWORD[match.intent.name]):
        # While the bot asks something, "delete old photos" or "what's on the
        # agenda" is an answer, not a command.
        match = None
    if match is not None and awaiting is not None and match.intent.name == IntentName.EVENT_MOVE \
            and not ev.names_event(update, match.rest):
        # "move the car" as the answer to "what should I remind you about?"
        match = None

    # A trigger phrase always wins, so "remind me ..." works at any point.
    if match is not None:
        context.user_data.pop(AWAITING, None)
        asked = context.user_data.pop(ASKED_REQUEST, None)
        context.user_data.pop(PENDING_PART, None)
        context.user_data.pop(PENDING_CONTACT_ID, None)
        if match.intent.name == IntentName.FLAG_FAILED and asked is not None and awaiting in QUESTIONS:
            # "that's wrong" while the bot asks for a time or a text: asking was the mistake.
            await rh.flag_question(update, context, asked, QUESTIONS[awaiting])
            return
        await match.intent.action(update, context, match.rest)
        return

    if awaiting == Awaiting.REMINDER:
        await rh.answer_reminder(update, context, text)
    elif awaiting == Awaiting.REMINDER_TEXT:
        await rh.answer_what(update, context, text)
    elif awaiting == Awaiting.REMINDER_TIME:
        await rh.answer_when(update, context, text)
    elif awaiting == Awaiting.CONTACT_USERNAME:
        await people.on_contact_username_text(update, context, text)
    elif awaiting == Awaiting.CONTACT_NAME:
        await people.on_contact_name_text(update, context, text)
    elif awaiting == Awaiting.TIMEZONE:
        await sh.on_timezone_text(update, context, text)
    elif awaiting == Awaiting.SNOOZE_OPTIONS:
        await sh.on_snooze_text(update, context, text)
    elif awaiting == Awaiting.QUIET_HOURS:
        await sh.on_quiet_text(update, context, text)
    elif awaiting == Awaiting.EDIT:
        await rh.edit_reminder(update, context, context.user_data[EDIT_REMINDER_ID], text)
    elif awaiting == Awaiting.EVENT:
        await ev.answer_event(update, context, text)
    elif awaiting == Awaiting.EVENT_TITLE:
        await ev.answer_title(update, context, text)
    elif awaiting == Awaiting.EVENT_TIME:
        await ev.answer_time(update, context, text)
    elif awaiting == Awaiting.EVENT_EDIT:
        await ev.edit_event(update, context, context.user_data[EDIT_EVENT_ID], text)
    elif rh.is_bare_time(update, text):
        # "tomorrow at 12" on its own: a reminder without its text yet.
        await rh.create_reminder(update, context, text)
    elif await ev.handle_untriggered(update, context, text):
        # "padel is at 20:00 now", or "padel on thursday at 21:00": event or reminder?
        pass
    else:
        record_not_understood(update, context, text)
        await update.effective_message.reply_text(HELP_TEXT)
