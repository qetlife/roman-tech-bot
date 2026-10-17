"""⏰ Reminders: create, edit, list, and the buttons on reminder messages."""

from    datetime                        import datetime, timedelta
from    zoneinfo                        import ZoneInfo

from    telegram                        import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.error                  import TelegramError
from    telegram.ext                    import ContextTypes

from    core                            import recurrence as recurrences
from    core.parser                     import ParseError, parse_reminder
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
    ACTIVE_STATUSES, Awaiting, Callback, CallbackPrefix, FailureReason, IntentName, MessageSource,
    ReminderAction, ReminderStatus,
)
from    handlers.failed                 import record, record_not_understood
from    handlers.settings               import ask_timezone
from    handlers.ui                     import (
    AWAITING, EDIT_REMINDER_ID, LAST_REMINDER_ID, PENDING_REQUEST, message_source, reminder_callback, render_menu,
)


users = UserRepository()
reminders = ReminderRepository()
settings = SettingsRepository()
failed = FailedMessageRepository()

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


async def create_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str):
    """Intent action for "remind me ..." / "set a reminder ..."."""
    user = users.get_or_create(update.effective_user.id)

    if not user.timezone:
        context.user_data[PENDING_REQUEST] = request
        await ask_timezone(update, context, "First, one-time setup. ")
        return

    try:
        parsed = parse_reminder(request, user_now(user.timezone))
    except ParseError as e:
        record_not_understood(update, context, request, IntentName.REMINDER_CREATE, str(e))
        context.user_data[AWAITING] = Awaiting.REMINDER
        await update.effective_message.reply_text(f"{e} Send it again, e.g. “in 2 hours to call mom”.\n\n{EXAMPLES}")
        return

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

def reminders_list_text(user, items) -> str:
    if not items:
        return "You have no upcoming reminders."
    lines = ["Your reminders (tap ❌ to cancel):", ""]
    for n, r in enumerate(items, 1):
        schedule = schedule_text(r, user.timezone or "UTC").replace("\n", "\n    ")
        lines.append(f"{n}. {r.text}\n    {schedule}")
    return "\n".join(lines)


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = "", toast: str = None):
    """Intent action for "my reminders" and the 📋 menu button."""
    user = users.get_or_create(update.effective_user.id)
    items = reminders.list_active(user.id)
    text = reminders_list_text(user, items)
    keyboard = build_reminders_list_keyboard(items)

    if update.callback_query is not None:
        await update.callback_query.answer(toast)
        await render_menu(update, context, text, keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


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
        await query.answer("Saved as failed")
        await flag_wrong(update, context, reminder, query.message.reply_text)


async def start_edit(context: ContextTypes.DEFAULT_TYPE, reminder, reply, intro: str = ""):
    """Ask for the new time and text of a reminder (✏️ Edit)."""
    context.user_data[AWAITING] = Awaiting.EDIT
    context.user_data[EDIT_REMINDER_ID] = reminder.id
    await reply(f"{intro}Send the new time and text for “{reminder.text}”, e.g. “tomorrow at 10 to {reminder.text}”.")


# --- 👎 Wrong ----------------------------------------------------------------

def understood(reminder) -> dict:
    """What the bot made of the message: kept with the failed message, even after ✏️ Edit."""
    return {"text": reminder.text, "remind_at": reminder.remind_at.isoformat(), "recurrence": reminder.recurrence}


async def flag_wrong(update: Update, context: ContextTypes.DEFAULT_TYPE, reminder, reply):
    """Save a reminder the bot got wrong as a failed message, then ✏️ Edit it."""
    if failed.open_for_reminder(reminder.id) is None:
        record(
            update, FailureReason.WRONG_RESULT, reminder.request or reminder.text,
            source=reminder.source or MessageSource.TYPED, intent=IntentName.REMINDER_CREATE,
            bot_understood=understood(reminder), reminder_id=reminder.id,
        )
    if reminder.status not in ACTIVE_STATUSES:
        await reply("👎 Saved as failed, thanks. This reminder has already finished, so there's nothing to fix.")
        return
    await start_edit(context, reminder, reply, intro="👎 Saved as failed, thanks. Let's fix it now.\n")


async def flag_last_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "that's wrong" / "save the last one as failed"."""
    reply = update.effective_message.reply_text
    if LAST_REMINDER_ID in context.user_data and context.user_data[LAST_REMINDER_ID] is None:
        await reply("👎 That one is already saved as failed: I save everything I don't understand.")
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
    await flag_wrong(update, context, reminder, reply)
