"""Messages about the last thing, or one in the last list: "move it to 10", "cancel that", "the same next week".

For 10 minutes after the user's last message, "it" is the reminder or event
the bot last made or changed, and "the second one" is from the last
numbered list it showed (core/conversation.py; handlers/ui.py keeps it).
After that, the bot asks which one. A reminder is cancelled at once, with
↩️ Undo; an event is asked about first (its reminders and Google Calendar
go with it).
"""

from    datetime                    import datetime, timedelta

from    telegram                    import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext                import ContextTypes

from    core.conversation           import parse_follow_up
from    core.events                 import next_occurrence
from    core.parser                 import parse_move
from    core.timezones              import user_now
from    db.models.reminder          import utcnow
from    db.repositories.contact     import ContactRepository
from    db.repositories.event       import EventRepository
from    db.repositories.reminder    import ReminderRepository
from    db.repositories.user        import UserRepository
from    enums                       import (
    ACTIVE_STATUSES, ContactStatus, EventStatus, FollowUp, IntentName, ItemKind, ReminderAction, ReminderStatus,
)
from    handlers                    import events as ev
from    handlers                    import reminders as rh
from    handlers.failed             import record_not_understood
from    handlers.ui                 import LAST_EVENT_ID, LAST_REMINDER_ID, about, conversation, message_source, reminder_callback


users = UserRepository()
contacts = ContactRepository()
reminders = ReminderRepository()
events = EventRepository()

WHICH_ONE = (
    "Which one? Say its name, e.g. “cancel the dentist reminder” or “move padel to 20:00”, "
    "or reply to the reminder's message."
)
MOVE_HELP = "Try “move it to 10”, “to friday” or “to friday at 10”."

# "the same next week": a week after it, not a week from today
NEXT_WEEK = {"next week", "a week later", "the week after", "in a week"}


async def handle_follow_up(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Act on "move it to 10" / "cancel that" / "the same next week"; False if the message isn't one."""
    request = parse_follow_up(text)
    if request is None:
        return False
    current = conversation(context)
    picked = current.pick(request.target) if current is not None else None
    item = _load(update, picked) if picked is not None else None
    if item is None:
        await update.effective_message.reply_text(WHICH_ONE)
        return True
    kind, thing = item
    if request.action == FollowUp.MOVE:
        if kind == ItemKind.EVENT:
            user = users.get_or_create(update.effective_user.id)
            await ev.move(update, context, user, thing, request.when, text)
        else:
            await move_reminder(update, context, thing, request.when, text)
    elif request.action == FollowUp.CANCEL:
        if kind == ItemKind.EVENT:
            await ev.confirm_cancel(update, users.get_or_create(update.effective_user.id), thing)
        else:
            await cancel_reminder(update, context, thing)
    elif kind == ItemKind.EVENT:
        await copy_event(update, context, thing, request.when, text)
    else:
        await copy_reminder(update, context, thing, request.when, text)
    return True


def _load(update: Update, picked: tuple):
    """(kind, the reminder or event) if it's still there and the user's to change; else None."""
    kind, item_id = picked
    user = users.get_or_create(update.effective_user.id)
    if kind == ItemKind.EVENT:
        event = events.get(item_id)
        if event is None or event.user_id != user.id or event.status != EventStatus.ACTIVE:
            return None
        return kind, event
    reminder = reminders.get(item_id)
    if reminder is None or reminder.status not in ACTIVE_STATUSES \
            or user.id not in (reminder.creator_user_id, reminder.target_user_id):
        return None
    return kind, reminder


def _new_time(phrase: str, old: datetime, now: datetime):
    """(the time in "to 10" / "to friday" / "next week", whether a time of day was said), from `old`.

    What isn't said stays. (None, False) if it isn't understood.
    """
    if phrase.strip().lower() in NEXT_WEEK:
        return old + timedelta(days=7), False
    moved = parse_move(phrase, old, now)
    return (moved.when, moved.timed) if moved is not None else (None, False)


# --- reminders --------------------------------------------------------------

async def move_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, reminder, phrase: str, request: str):
    """ "move it to 10": the same day at 10; "to friday": the same time on Friday. A repeat moves just this time."""
    reply = update.effective_message.reply_text
    user = users.get_or_create(update.effective_user.id)
    if reminder.creator_user_id != user.id:
        await reply("Only whoever made this reminder can move it. You can snooze it when it goes off.")
        return
    tz_name = user.timezone or "UTC"
    now = user_now(tz_name)
    when, _ = _new_time(phrase, reminder.remind_at.astimezone(now.tzinfo), now)
    if when is None:
        record_not_understood(update, context, request, IntentName.REMINDER_EDIT, "couldn't read the new time")
        await reply(f"I couldn't understand the new time. {MOVE_HELP}")
        return
    if when <= now:
        await reply("That time has already passed.")
        return
    if reminder.recurrence:
        # A repeat: only this time moves; the repeat stays as it is.
        updated = reminders.snooze(reminder.id, when)
    else:
        updated = reminders.reschedule(reminder.id, reminder.text, when, None, reminder.request, reminder.source)
    if updated is None:
        await reply("That reminder has already finished.")
        return
    await rh.retire_fired_message(context, reminder, "🗓 Moved, see the reminder below.")
    about(context, ItemKind.REMINDER, updated.id)
    await reply(f"⏰ Moved: {updated.text}\n{rh.schedule_text(updated, tz_name)}",
                reply_markup=rh.build_created_keyboard(updated.id))


async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, reminder):
    """ "cancel that": cancelled at once, with ↩️ Undo."""
    user = users.get_or_create(update.effective_user.id)
    if reminders.cancel(reminder.id) is None:
        await update.effective_message.reply_text("That reminder has already finished.")
        return
    await rh.retire_fired_message(context, reminder, "↩️ Cancelled.")
    if user.id == reminder.target_user_id:
        await rh.tell_creator(context.bot, reminder, ReminderStatus.CANCELLED)
    await update.effective_message.reply_text(
        f"🗑 Cancelled: {reminder.text}\n{rh.schedule_text(reminder, user.timezone or 'UTC')}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
            "↩️ Undo", callback_data=reminder_callback(ReminderAction.RESTORE, reminder.id),
        )]]),
    )


async def copy_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, reminder, phrase: str, request: str):
    """ "and the same next week": a new reminder like it, at the new time (for the same person)."""
    reply = update.effective_message.reply_text
    user = users.get_or_create(update.effective_user.id)
    if reminder.creator_user_id != user.id:
        await reply("That reminder is from someone else. To make your own, say “remind me …”.")
        return
    if reminder.recurrence:
        await reply("It already repeats. To change how, use ✏️ Edit on it.")
        return
    tz_name = user.timezone or "UTC"
    now = user_now(tz_name)
    when, _ = _new_time(phrase, reminder.remind_at.astimezone(now.tzinfo), now)
    if when is None:
        record_not_understood(update, context, request, IntentName.REMINDER_CREATE, "couldn't read the new time")
        await reply("I couldn't understand when. Try “the same next week” or “also on friday at 10”.")
        return
    if when <= now:
        await reply("That time has already passed.")
        return
    target, for_whom = None, ""
    if reminder.target_user_id != user.id:
        target = users.get_by_id(reminder.target_user_id)
        contact = contacts.find(user.id, reminder.target_user_id) if target is not None else None
        if contact is None or contact.status != ContactStatus.ACCEPTED:
            await reply("That person isn't in your 👥 People any more.")
            return
        for_whom = f" for {contact.name}"
    when = rh.outside_quiet_hours(target or user, None, when)
    copy = reminders.create(
        user, target.telegram_id if target else update.effective_chat.id, reminder.text, when, None,
        request, message_source(update), target=target,
    )
    context.user_data[LAST_REMINDER_ID] = copy.id
    context.user_data.pop(LAST_EVENT_ID, None)
    about(context, ItemKind.REMINDER, copy.id)
    await reply(f"⏰ Got it{for_whom}: {copy.text}\n{rh.schedule_text(copy, tz_name)}",
                reply_markup=rh.build_created_keyboard(copy.id))


# --- events -----------------------------------------------------------------

async def copy_event(update: Update, context: ContextTypes.DEFAULT_TYPE, event, phrase: str, request: str):
    """ "and the same next week": a new event like it (same length), at the new time."""
    reply = update.effective_message.reply_text
    user = users.get_or_create(update.effective_user.id)
    if event.recurrence:
        await reply("It already repeats. To change how, use ✏️ Edit on it in 📅 Events.")
        return
    now = user_now(event.timezone)
    old = (next_occurrence(event, utcnow()) or event.starts_at).astimezone(now.tzinfo)
    when, timed = _new_time(phrase, old, now)
    if when is None:
        record_not_understood(update, context, request, IntentName.EVENT_CREATE, "couldn't read the new time")
        await reply("I couldn't understand when. Try “the same next week” or “also on friday at 20:00”.")
        return
    all_day = event.all_day and not timed
    if when.date() < now.date() if all_day else when <= now:
        await reply("That time has already passed.")
        return
    copy = events.create(user.id, event.title, when, event.timezone, None, all_day, request, message_source(update))
    if event.ends_at is not None and all_day == event.all_day:
        copy = events.update(copy.id, ends_at=when + (event.ends_at - event.starts_at)) or copy
    context.user_data[LAST_EVENT_ID] = copy.id
    about(context, ItemKind.EVENT, copy.id)
    await reply(f"📅 Added: {copy.title}\n{ev.when_text(copy, user.timezone)}\n\nA reminder before it?",
                reply_markup=ev.build_created_keyboard(copy))
    await ev.to_google(context, copy)
