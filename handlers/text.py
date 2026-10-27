"""Typed (and transcribed) messages in private chats: trigger phrases, or the answer to a question."""

from    telegram                    import Update
from    telegram.ext                import ContextTypes

from    core.conversation           import is_never_mind, parse_follow_up
from    core.intents                import match_intent
from    enums                       import AnswerKind, Awaiting, CallbackPrefix, FollowUp, IntentName
from    handlers.failed             import record_not_understood
from    handlers                    import calendar
from    handlers.conversation       import handle_follow_up, is_time
from    handlers                    import events as ev
from    handlers                    import reminders as rh
from    handlers.replies            import handle_reply
from    handlers                    import people
from    handlers                    import settings as sh
from    handlers.intents            import INTENTS
from    handlers.ui                 import (
    ASKED_ABOUT, ASKED_MESSAGE_ID, ASKED_REQUEST, AWAITING, EDIT_EVENT_ID, EDIT_REMINDER_ID, PENDING_CONTACT_ID, PENDING_PART,
    conversation,
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

# Trigger phrases a follow-up wins over: "cancel it" and "move it to 10" are about "it".
FOLLOW_UP_INTENTS = (IntentName.REMINDER_CANCEL, IntentName.EVENT_CANCEL, IntentName.EVENT_MOVE)

# Questions whose answer is only a time or a day: "what do I have tomorrow?" is never one.
TIME_ONLY = (Awaiting.REMINDER_CLOCK, Awaiting.REMINDER_DAY, Awaiting.EVENT_DAY)

# Questions whose answer is a time, a day, or a date: "no" or "stop" can't be one, so they mean "never mind"
NOT_TEXT = (*TIME_ONLY, Awaiting.REMINDER_TIME, Awaiting.EVENT_TIME)
# Questions "never mind" drops: about a reminder or an event. Settings and 👥 People keep their own answers.
NEVER_MIND_QUESTIONS = (*NOT_TEXT, Awaiting.REMINDER, Awaiting.REMINDER_TEXT, Awaiting.EDIT, Awaiting.EVENT,
                        Awaiting.EVENT_TITLE, Awaiting.EVENT_EDIT)

# A question about a reminder or an event's missing half: "that's wrong" then means the asking.
QUESTIONS = {
    Awaiting.REMINDER_TEXT: IntentName.REMINDER_CREATE,
    Awaiting.REMINDER_TIME: IntentName.REMINDER_CREATE,
    Awaiting.EVENT_TITLE: IntentName.EVENT_CREATE,
    Awaiting.EVENT_TIME: IntentName.EVENT_CREATE,
    Awaiting.REMINDER_CLOCK: IntentName.REMINDER_CREATE,
    Awaiting.REMINDER_DAY: IntentName.REMINDER_CREATE,
    Awaiting.EVENT_DAY: IntentName.EVENT_CREATE,
}

# A new reminder or event instead of answering the question about one replaces it: no “Dropped: …” then.
REPLACES = {
    IntentName.REMINDER_CREATE: {Awaiting.REMINDER, Awaiting.REMINDER_TEXT, Awaiting.REMINDER_TIME,
                                 Awaiting.REMINDER_CLOCK, Awaiting.REMINDER_DAY},
    IntentName.EVENT_CREATE: {Awaiting.EVENT, Awaiting.EVENT_TITLE, Awaiting.EVENT_TIME, Awaiting.EVENT_DAY},
}

HELP_TEXT = "I didn't get that."


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plain text in a private chat."""
    await handle_text(update, context, update.effective_message.text or "")


def drop_question(context: ContextTypes.DEFAULT_TYPE):
    """Forget the question the bot is asking. What it was about ("the reminder “dentist”"), if it was asked with ask()."""
    awaiting = context.user_data.pop(AWAITING, None)
    asked = context.user_data.pop(ASKED_ABOUT, None)
    for key in (ASKED_REQUEST, ASKED_MESSAGE_ID, PENDING_PART, PENDING_CONTACT_ID):
        context.user_data.pop(key, None)
    if awaiting is None or asked is None or asked[0] != awaiting:
        return None
    return asked[1]


async def say_dropped(update: Update, about: str):
    if about:
        await update.effective_message.reply_text(f"Dropped: {about}.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Trigger phrases, or the answer to a question. Also used for transcribed voice messages."""
    # Anything may be about reminders or events: bring in Google Calendar's changes first (every 5 minutes at most)
    await calendar.maybe_sync(context.bot, update.effective_user.id)
    # Within 10 minutes of the last message, "it" is still what we talked about
    conversation(context, touch=True)
    # "done", "snooze 20 min" … as a reply to a reminder message
    if await handle_reply(update, context, text):
        return
    awaiting = context.user_data.get(AWAITING)
    if awaiting in NEVER_MIND_QUESTIONS and is_never_mind(text, loose=awaiting in NOT_TEXT):
        # "never mind", "cancel" while the bot asks about a reminder or an event (settings take "no" as an answer)
        about = drop_question(context)
        await update.effective_message.reply_text(f"OK, dropped {about}." if about else "OK.")
        return
    match = match_intent(text, INTENTS)
    follow_up = parse_follow_up(text)
    if follow_up is not None and (match is None or match.intent.name in FOLLOW_UP_INTENTS) \
            and (awaiting is None or follow_up.action == FollowUp.CANCEL) \
            and (follow_up.action != FollowUp.COPY or is_time(update, follow_up.when)):
        # "move it to 10", "cancel the second one": a command of its own. Not over a trigger
        # phrase ("also remind me …"), and while the bot asks, "make it work" may be the answer.
        # A copy needs a time: "also buy milk" is no "also on thursday".
        if awaiting is not None:
            await say_dropped(update, drop_question(context))
        await handle_follow_up(update, context, text)
        return

    if match is not None and awaiting not in (None, *TIME_ONLY) and match.intent.name in NEEDS_KEYWORD \
            and not any(word in text.lower() for word in NEEDS_KEYWORD[match.intent.name]):
        # While the bot asks something, "delete old photos" or "what's on the
        # agenda" is an answer, not a command.
        match = None
    if match is not None and awaiting not in (None, *TIME_ONLY) and match.intent.name == IntentName.EVENT_MOVE \
            and not ev.names_event(update, match.rest):
        # "move the car" as the answer to "what should I remind you about?"
        match = None

    # A trigger phrase always wins, so "remind me ..." works at any point.
    if match is not None:
        asked = context.user_data.get(ASKED_REQUEST)
        about = drop_question(context)
        if match.intent.name == IntentName.FLAG_FAILED and asked is not None and awaiting in QUESTIONS:
            # "that's wrong" while the bot asks for a time or a text: asking was the mistake.
            await rh.flag_question(update, context, asked, QUESTIONS[awaiting])
            return
        if awaiting not in REPLACES.get(match.intent.name, ()):
            # "what do I have tomorrow?" instead of answering: done, and the question is dropped
            await say_dropped(update, about)
        await match.intent.action(update, context, match.rest)
        return

    if awaiting == Awaiting.REMINDER:
        await rh.answer_reminder(update, context, text)
    elif awaiting == Awaiting.REMINDER_TEXT:
        await rh.answer_what(update, context, text)
    elif awaiting == Awaiting.REMINDER_TIME:
        await rh.answer_when(update, context, text)
    elif awaiting == Awaiting.REMINDER_CLOCK:
        await rh.answer_clock(update, context, text)
    elif awaiting == Awaiting.REMINDER_DAY:
        await rh.answer_day(update, context, text)
    elif awaiting == Awaiting.EVENT_DAY:
        await ev.answer_day(update, context, text)
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


# What each answer button answers
ANSWERS = {
    AnswerKind.CLOCK: {Awaiting.REMINDER_CLOCK: rh.answer_clock},
    AnswerKind.DAY: {Awaiting.REMINDER_DAY: rh.answer_day, Awaiting.EVENT_DAY: ev.answer_day},
}
DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🌅 Morning / Mon … under the bot's question: the same as typing the answer."""
    query = update.callback_query
    kind, _, value = query.data.removeprefix(CallbackPrefix.ANSWER).partition(":")
    answer = ANSWERS.get(kind, {}).get(context.user_data.get(AWAITING))
    if answer is None or not value.isdigit() or query.message.message_id != context.user_data.get(ASKED_MESSAGE_ID):
        # Not the question being asked (or buttons from an older one)
        await query.answer("That question has expired. Send it again.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None)
        return
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    if kind == AnswerKind.CLOCK:
        text = f"{value[:2]}:{value[2:]}"
    else:
        text = DAY_NAMES[min(int(value), 6)]
    conversation(context, touch=True)
    await answer(update, context, text)
