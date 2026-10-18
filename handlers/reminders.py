"""⏰ Reminders: create, edit, list, and the buttons on reminder messages."""

from    datetime                        import datetime, timedelta
from    zoneinfo                        import ZoneInfo

from    telegram                        import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.error                  import TelegramError
from    telegram.ext                    import ContextTypes

from    core                            import recurrence as recurrences
from    core.commands                   import matches, occurs_on, parse_day, search_words
from    core.parser                     import MissingText, MissingTime, ParseError, parse_reminder
from    core.quiet                      import skip_quiet
from    core.settings                   import (
    QUIET_HOURS, SNOOZE_MAX_MINUTES, SNOOZE_MIN_MINUTES, format_minutes, quiet_window,
)
from    core.timezones                  import format_when, user_now
from    db.models.reminder              import utcnow
from    db.repositories.reminder        import ReminderRepository
from    db.repositories.settings        import SettingsRepository
from    db.repositories.user            import UserRepository
from    db.repositories.failed_message  import FailedMessageRepository
from    enums                           import (
    Awaiting, Callback, CallbackPrefix, FailureReason, IntentName, MessageSource,
    ReminderAction, ReminderStatus,
)
from    handlers.failed                 import record, record_not_understood
from    handlers.settings               import ask_timezone
from    handlers.ui                     import (
    ASKED_REQUEST, AWAITING, EDIT_REMINDER_ID, LAST_REMINDER_ID, PENDING_PART, PENDING_REQUEST, message_source,
    reminder_callback, render_menu,
)


users = UserRepository()
reminders = ReminderRepository()
settings = SettingsRepository()
failed = FailedMessageRepository()

# bot_understood["error"] of a message flagged with "that's wrong" while the bot asked about it.
ASKED_ERROR = "asked for the missing time or text"

EXAMPLES = (
    "Examples:\n"
    "• in 2 hours to call mom\n"
    "• tomorrow at 9 to pay rent\n"
    "• to stretch at 18:30\n"
    "• friday 10am: dentist\n"
    "• every day at 9 to take pills\n"
    "• on weekdays at 8:30: standup\n"
    "• every 2 hours to drink water\n"
    "• on the 1st of every month to pay rent"
)

# --- keyboards --------------------------------------------------------------

def build_fire_keyboard(reminder_id: int, snooze_minutes):
    """✅ OK plus one 💤 button per snooze option (the user's setting)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ OK", callback_data=reminder_callback(ReminderAction.OK, reminder_id)),
        *[
            InlineKeyboardButton(f"💤 {format_minutes(m)}", callback_data=reminder_callback(ReminderAction.SNOOZE, reminder_id, m))
            for m in snooze_minutes
        ],
    ]])


def build_created_keyboard(reminder_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ Undo", callback_data=reminder_callback(ReminderAction.UNDO, reminder_id)),
        InlineKeyboardButton("✏️ Edit", callback_data=reminder_callback(ReminderAction.EDIT, reminder_id)),
        InlineKeyboardButton("👎 Wrong", callback_data=reminder_callback(ReminderAction.WRONG, reminder_id)),
    ]])


def build_reminders_list_keyboard(items):
    rows = [
        [InlineKeyboardButton(f"❌ {shorten(r.text, 28)}", callback_data=reminder_callback(ReminderAction.DELETE, r.id))]
        for r in items
    ]
    rows.append([
        InlineKeyboardButton("➕ New", callback_data=Callback.NEW_REMINDER),
        InlineKeyboardButton("↩️ Back", callback_data=Callback.REMINDERS_MENU),
    ])
    return InlineKeyboardMarkup(rows)


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


async def retire_fired_message(context: ContextTypes.DEFAULT_TYPE, reminder, note: str):
    """Remove OK/snooze from a reminder's last delivered message.

    Used when a reminder that is currently firing is edited or cancelled from
    somewhere else, so the old buttons can't act on it any more.
    """
    if reminder.status != ReminderStatus.FIRING or reminder.last_message_id is None:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=reminder.chat_id,
            message_id=reminder.last_message_id,
            text=f"⏰ {reminder.text}\n\n{note}",
        )
    except TelegramError:
        # Message already deleted or too old to edit.
        pass


def schedule_text(reminder, tz_name: str) -> str:
    """"🗓 Tomorrow, 09:00 (in 9 h)" plus "🔁 every day at 09:00" if recurring."""
    text = f"🗓 {format_when(reminder.remind_at, tz_name, utcnow())}"
    if reminder.recurrence:
        text += f"\n🔁 {recurrences.parse(reminder.recurrence).describe(ZoneInfo(tz_name))}"
    return text


# --- creating ---------------------------------------------------------------

def outside_quiet_hours(user, recurrence, when: datetime) -> datetime:
    """Move an "every 2 hours" occurrence past the user's quiet hours."""
    if recurrence is None:
        return when
    quiet = quiet_window(settings.get(user.id, QUIET_HOURS))
    return skip_quiet(recurrence, when, quiet, ZoneInfo(user.timezone or "UTC"))


def keep_clock_times(user_id, old_tz: str, new_tz: str):
    """After a timezone change, daily/weekly/monthly reminders keep their local clock time.

    Later occurrences are computed in the new timezone anyway; this moves the
    next one, which was computed in the old one. One-offs and intervals keep
    their moment in time, and a snoozed or firing reminder is left alone.
    """
    now = utcnow()
    for reminder in reminders.list_active(user_id):
        if reminder.status != ReminderStatus.PENDING or reminder.recurrence is None:
            continue
        recurrence = recurrences.parse(reminder.recurrence)
        if isinstance(recurrence, recurrences.Interval):
            continue
        # Snoozed: remind_at isn't one of its occurrences any more.
        if recurrence.next_after(reminder.remind_at - timedelta(seconds=1), ZoneInfo(old_tz)) != reminder.remind_at:
            continue
        reminders.advance(reminder.id, recurrence.next_after(now, ZoneInfo(new_tz)))


async def create_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str):
    """Intent action for "remind me ..." / "set a reminder ..."."""
    user = users.get_or_create(update.effective_user.id)

    if not user.timezone:
        context.user_data[PENDING_REQUEST] = request
        await ask_timezone(update, context, "First, one-time setup. ")
        return

    try:
        parsed = parse_reminder(request, user_now(user.timezone))
    except MissingText:
        await ask_what(update, context, request)
        return
    except MissingTime as e:
        if e.text:
            await ask_when(update, context, e.text, request=request)
            return
        await not_understood(update, context, request, e)
        return
    except ParseError as e:
        await not_understood(update, context, request, e)
        return

    await save_reminder(update, context, user, parsed, request)


async def not_understood(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str, error: ParseError):
    record_not_understood(update, context, request, IntentName.REMINDER_CREATE, str(error))
    context.user_data[AWAITING] = Awaiting.REMINDER
    await update.effective_message.reply_text(f"{error} Send it again, e.g. “in 2 hours to call mom”.\n\n{EXAMPLES}")


def is_bare_time(update: Update, text: str) -> bool:
    """Whether `text` is only a time ("tomorrow at 12"), with no trigger phrase or text."""
    user = users.get_or_create(update.effective_user.id)
    try:
        parse_reminder(text, user_now(user.timezone or "UTC"))
    except MissingText:
        return True
    except ParseError:
        pass
    return False


# --- asking for the missing half --------------------------------------------
# "tomorrow at 12" has no text, "remind me to call mom" no time: instead of
# failing, the bot asks for the other half and puts the two together.

async def ask_what(update: Update, context: ContextTypes.DEFAULT_TYPE, when: str):
    context.user_data[AWAITING] = Awaiting.REMINDER_TEXT
    context.user_data[PENDING_PART] = when
    context.user_data[ASKED_REQUEST] = when
    await update.effective_message.reply_text(f"⏰ {when}: what should I remind you about?")


async def ask_when(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, prefix: str = "",
                   request: str = None):
    context.user_data[AWAITING] = Awaiting.REMINDER_TIME
    context.user_data[PENDING_PART] = text
    if request is not None:
        context.user_data[ASKED_REQUEST] = request
    await update.effective_message.reply_text(
        f"{prefix}⏰ When should I remind you: “{text}”?\n"
        "e.g. “tomorrow at 9”, “in 2 hours”, “every Monday at 8”"
    )


async def answer_what(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """The answer to ask_what: the text for the time given before."""
    when = context.user_data.pop(PENDING_PART, "")
    joiner = " " if text.lower().startswith(("to ", "about ", "that ")) else " to "
    await create_reminder(update, context, f"{when}{joiner}{text}")


async def answer_when(update: Update, context: ContextTypes.DEFAULT_TYPE, when: str):
    """The answer to ask_when: the time for the text given before. Asks again if it isn't one."""
    user = users.get_or_create(update.effective_user.id)
    text = context.user_data.get(PENDING_PART, "")
    request = f"{when} to {text}"
    try:
        parsed = parse_reminder(request, user_now(user.timezone))
    except ParseError as e:
        # The text is known, so whatever failed is the time.
        record_not_understood(update, context, when, IntentName.REMINDER_WHEN, str(e))
        await ask_when(update, context, text, prefix=f"{e} ")
        return
    context.user_data.pop(PENDING_PART, None)
    await save_reminder(update, context, user, parsed, request)


async def save_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, user, parsed, request: str):
    context.user_data.pop(AWAITING, None)
    recurrence = parsed.recurrence.serialize() if parsed.recurrence else None
    when = outside_quiet_hours(user, parsed.recurrence, parsed.when)
    reminder = reminders.create(
        user, update.effective_chat.id, parsed.text, when, recurrence, request, message_source(update),
    )
    context.user_data[LAST_REMINDER_ID] = reminder.id
    await update.effective_message.reply_text(
        f"⏰ Got it: {reminder.text}\n{schedule_text(reminder, user.timezone)}",
        reply_markup=build_created_keyboard(reminder.id),
    )


async def edit_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, reminder_id: int, request: str):
    user = users.get_or_create(update.effective_user.id)
    reminder = reminders.get_for_user(reminder_id, update.effective_user.id)
    if reminder is None:
        context.user_data.pop(AWAITING, None)
        await update.effective_message.reply_text("That reminder no longer exists.")
        return

    try:
        parsed = parse_reminder(request, user_now(user.timezone))
    except ParseError as e:
        record_not_understood(update, context, request, IntentName.REMINDER_EDIT, str(e))
        await update.effective_message.reply_text(f"{e} Try again, e.g. “tomorrow at 10 to call mom”.")
        return

    context.user_data.pop(AWAITING, None)
    recurrence = parsed.recurrence.serialize() if parsed.recurrence else None
    when = outside_quiet_hours(user, parsed.recurrence, parsed.when)
    updated = reminders.reschedule(reminder.id, parsed.text, when, recurrence, request, message_source(update))
    if updated is None:
        await update.effective_message.reply_text("That reminder has already finished.")
        return
    context.user_data[LAST_REMINDER_ID] = updated.id
    await retire_fired_message(context, reminder, "✏️ Edited, see the updated reminder below.")
    await update.effective_message.reply_text(
        f"✏️ Updated: {updated.text}\n{schedule_text(updated, user.timezone)}",
        reply_markup=build_created_keyboard(updated.id),
    )


async def on_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu button: ➕ New reminder."""
    await update.callback_query.answer()
    context.user_data[AWAITING] = Awaiting.REMINDER
    await update.effective_message.reply_text(f"What should I remind you about, and when?\n\n{EXAMPLES}")


# --- listing ----------------------------------------------------------------

def reminders_list_text(user, items, title: str = "Your reminders", empty: str = "You have no upcoming reminders.") -> str:
    if not items:
        return empty
    lines = [f"{title} (tap ❌ to cancel):", ""]
    for n, r in enumerate(items, 1):
        schedule = schedule_text(r, user.timezone or "UTC").replace("\n", "\n    ")
        lines.append(f"{n}. {r.text}\n    {schedule}")
    return "\n".join(lines)


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = "", toast: str = None):
    """Intent action for "my reminders" / "what do I have tomorrow?", and the 📋 menu button."""
    user = users.get_or_create(update.effective_user.id)
    items = reminders.list_active(user.id)
    text = None
    if request.strip():
        tz_name = user.timezone or "UTC"
        day = parse_day(request, user_now(tz_name))
        if day is None:
            await update.effective_message.reply_text(
                "I can show one day, e.g. “what do I have tomorrow?” or “my reminders on friday”."
            )
            return
        items = [r for r in items if occurs_on(r.remind_at, r.recurrence, day, ZoneInfo(tz_name), r.created_at)]
        title = f"{day:%a %d %b}"
        text = reminders_list_text(user, items, f"Your reminders on {title}", f"Nothing on {title}. 🎉")
    text = text or reminders_list_text(user, items)
    keyboard = build_reminders_list_keyboard(items)

    if update.callback_query is not None:
        await update.callback_query.answer(toast)
        await render_menu(update, context, text, keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "cancel the dentist reminder": cancels the one that matches, or asks which."""
    user = users.get_or_create(update.effective_user.id)
    items = reminders.list_active(user.id)
    words = search_words(request)
    found = [r for r in items if matches(r.text, words)] if words else items
    reply = update.effective_message.reply_text

    if words and len(found) == 1:
        [reminder] = found
        reminders.cancel(reminder.id)
        await retire_fired_message(context, reminder, "↩️ Cancelled.")
        await reply(f"↩️ Cancelled: {reminder.text}")
        return
    if words and not found:
        await reply(reminders_list_text(user, items, f"No reminder matches “{' '.join(words)}”. Yours",
                                        f"No reminder matches “{' '.join(words)}”."),
                    reply_markup=build_reminders_list_keyboard(items))
        return
    await reply(reminders_list_text(user, found, "Which one? Your reminders"),
                reply_markup=build_reminders_list_keyboard(found))


# --- buttons ----------------------------------------------------------------

async def _own_reminder(update: Update, reminder_id: int):
    """The reminder if it belongs to whoever pressed the button."""
    reminder = reminders.get_for_user(reminder_id, update.effective_user.id)
    if reminder is None:
        await update.callback_query.answer("This reminder isn't yours.", show_alert=True)
    return reminder


async def on_reminder_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, reminder_id, *args = query.data.removeprefix(CallbackPrefix.REMINDER).split(":")
    action, reminder_id = ReminderAction(action), int(reminder_id)

    reminder = await _own_reminder(update, reminder_id)
    if reminder is None:
        return

    if action == ReminderAction.OK and reminder.recurrence:
        if reminder.status != ReminderStatus.FIRING:
            # A stale message; the reminder has already moved on.
            await query.answer("Already done.")
            await query.edit_message_reply_markup(reply_markup=None)
            return
        user = users.get_or_create(update.effective_user.id)
        tz_name = user.timezone or "UTC"
        recurrence = recurrences.parse(reminder.recurrence)
        next_at = recurrence.next_after(max(utcnow(), reminder.remind_at), ZoneInfo(tz_name))
        next_at = outside_quiet_hours(user, recurrence, next_at)
        updated = reminders.advance(reminder_id, next_at)
        await query.answer("Done!")
        if updated is None:
            await query.edit_message_text(f"✅ {reminder.text}")
            return
        await query.edit_message_text(f"✅ {reminder.text}\n\nNext: {format_when(next_at, tz_name, utcnow())}")

    elif action == ReminderAction.OK:
        reminders.acknowledge(reminder_id)
        await query.answer("Done!")
        await query.edit_message_text(f"✅ {reminder.text}")

    elif action == ReminderAction.SNOOZE:
        user = users.get_or_create(update.effective_user.id)
        # Callback data comes from the client: keep it within the allowed range.
        minutes = min(max(int(args[0]), SNOOZE_MIN_MINUTES), SNOOZE_MAX_MINUTES)
        until = utcnow() + timedelta(minutes=minutes)
        if reminders.snooze(reminder_id, until) is None:
            await query.answer("This reminder has already finished.")
            await query.edit_message_reply_markup(reply_markup=None)
            return
        await query.answer("Snoozed")
        await query.edit_message_text(
            f"💤 {reminder.text}\nSnoozed until {format_when(until, user.timezone or 'UTC', utcnow())}"
        )

    elif action == ReminderAction.UNDO:
        if reminders.cancel(reminder_id) is None:
            await query.answer("This reminder has already finished.")
            return
        await query.answer("Cancelled")
        await query.edit_message_text(f"↩️ Cancelled: {reminder.text}")
        await retire_fired_message(context, reminder, "↩️ Cancelled.")

    elif action == ReminderAction.EDIT:
        await query.answer()
        await start_edit(context, reminder, query.message.reply_text)

    elif action == ReminderAction.DELETE:
        if reminders.cancel(reminder_id) is not None:
            await retire_fired_message(context, reminder, "↩️ Cancelled.")
        await list_reminders(update, context, toast="Cancelled")

    elif action == ReminderAction.WRONG:
        await query.answer("Deleted and saved as failed")
        # Shown on the confirmation itself, like ↩️ Undo, so its buttons go away.
        await query.edit_message_text(await flag_wrong(update, context, reminder))


async def start_edit(context: ContextTypes.DEFAULT_TYPE, reminder, reply, intro: str = ""):
    """Ask for the new time and text of a reminder (✏️ Edit)."""
    context.user_data[AWAITING] = Awaiting.EDIT
    context.user_data[EDIT_REMINDER_ID] = reminder.id
    await reply(f"{intro}Send the new time and text for “{reminder.text}”, e.g. “tomorrow at 10 to {reminder.text}”.")


# --- 👎 Wrong ----------------------------------------------------------------

def understood(reminder) -> dict:
    """What the bot made of the message, kept with the failed message."""
    return {"text": reminder.text, "remind_at": reminder.remind_at.isoformat(), "recurrence": reminder.recurrence}


async def flag_wrong(update: Update, context: ContextTypes.DEFAULT_TYPE, reminder) -> str:
    """Save a reminder the bot got wrong as a failed message and delete it.

    Returns what to tell the user. The user sends it again if it's still needed.
    """
    if failed.open_for_reminder(reminder.id) is None:
        record(
            update, FailureReason.WRONG_RESULT, reminder.request or reminder.text,
            source=reminder.source or MessageSource.TYPED, intent=IntentName.REMINDER_CREATE,
            bot_understood=understood(reminder), reminder_id=reminder.id,
        )
    # "that's wrong" again now means this one, which is already saved.
    context.user_data[LAST_REMINDER_ID] = None
    if reminders.cancel(reminder.id) is None:
        return f"👎 Saved as failed, so I can learn it. “{reminder.text}” had already finished."
    await retire_fired_message(context, reminder, "↩️ Cancelled.")
    return (
        f"👎 Deleted: {reminder.text}\n"
        "Saved as failed, so I can learn it. Send it again if you still need it."
    )


async def flag_question(update: Update, context: ContextTypes.DEFAULT_TYPE, asked: str):
    """"that's wrong" while the bot asks for a missing time or text: save the message it asked about.

    Called by handlers/text.py, which knows the question is still open.
    """
    record_not_understood(update, context, asked, IntentName.REMINDER_CREATE, ASKED_ERROR)
    await update.effective_message.reply_text("👎 Saved as failed, so I can learn it. Send it again if you still need it.")


async def flag_last_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "that's wrong" / "save the last one as failed"."""
    reply = update.effective_message.reply_text
    if LAST_REMINDER_ID in context.user_data and context.user_data[LAST_REMINDER_ID] is None:
        await reply("👎 That one is already saved as failed.")
        return

    # After a restart user_data is empty: fall back to the newest reminder.
    reminder_id = context.user_data.get(LAST_REMINDER_ID)
    if reminder_id is not None:
        reminder = reminders.get_for_user(reminder_id, update.effective_user.id)
    else:
        reminder = reminders.latest_for_user(update.effective_user.id)
    if reminder is None:
        await reply("There's no reminder to save as failed yet.")
        return
    await reply(await flag_wrong(update, context, reminder))
