"""Background loop that sends due reminders and repeats them until OK."""

import logging

from    datetime                    import timedelta
from    zoneinfo                    import ZoneInfo

from    telegram.error              import Forbidden, TelegramError
from    telegram.ext                import ContextTypes

from    core                        import recurrence as recurrences
from    core.quiet                  import is_quiet, quiet_end, skip_quiet
from    core.settings               import QUIET_HOURS, REPEAT_MINUTES, SNOOZE_OPTIONS, quiet_window
from    db.models.reminder          import utcnow
from    db.repositories.reminder    import ReminderRepository
from    db.repositories.settings    import SettingsRepository
from    db.repositories.user        import UserRepository
from    enums                       import ReminderStatus
from    handlers.reminders          import build_fire_keyboard


logger = logging.getLogger(__name__)

reminders = ReminderRepository()
settings = SettingsRepository()
users = UserRepository()

POLL_INTERVAL = timedelta(seconds=20)
GIVE_UP_AFTER = timedelta(hours=24)


async def _delete(bot, chat_id, message_id):
    if message_id is None:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError:
        # Already deleted, or older than 48 h (Telegram won't delete those).
        pass


async def deliver_due(context: ContextTypes.DEFAULT_TYPE):
    """Job: send every reminder whose next_fire_at has passed."""
    bot = context.bot
    now = utcnow()

    due = reminders.get_due(now)
    user_ids = {r.target_user_id for r in due}
    snooze_options = settings.get_for_users(user_ids, SNOOZE_OPTIONS)
    repeat_minutes = settings.get_for_users(user_ids, REPEAT_MINUTES)
    quiet_hours = settings.get_for_users(user_ids, QUIET_HOURS)
    timezones = users.get_timezones(user_ids)

    for reminder in due:
        try:
            await _deliver(
                bot, reminder, now,
                snooze_options[reminder.target_user_id],
                timedelta(minutes=repeat_minutes[reminder.target_user_id]),
                ZoneInfo(timezones.get(reminder.target_user_id) or "UTC"),
                quiet_window(quiet_hours[reminder.target_user_id]),
            )
        except Exception:
            # One broken reminder must not stop the others; it is retried next poll.
            logger.exception("Failed to deliver reminder %s", reminder.id)


async def _mark_message_missed(bot, reminder, reason):
    if reminder.last_message_id is None:
        return
    try:
        await bot.edit_message_text(
            chat_id=reminder.chat_id,
            message_id=reminder.last_message_id,
            text=f"⏰ {reminder.text}\n\n❌ Missed: {reason}.",
        )
    except TelegramError:
        pass


def _catch_up(recurrence, reminder, now, tz):
    """(latest occurrence after remind_at that is already due or None, the one after it)."""
    latest = None
    upcoming = recurrence.next_after(reminder.remind_at, tz)
    while upcoming <= now:
        latest, upcoming = upcoming, recurrence.next_after(upcoming, tz)
    return latest, upcoming


async def _deliver(bot, reminder, now, snooze_minutes, repeat_every, tz, quiet=None):
    firing = reminder.status == ReminderStatus.FIRING
    gave_up = firing and now - reminder.remind_at >= GIVE_UP_AFTER

    recurrence = recurrences.parse(reminder.recurrence) if reminder.recurrence else None
    if recurrence is not None:
        latest, upcoming = _catch_up(recurrence, reminder, now, tz)
        if latest is not None or gave_up:
            # This occurrence is over: move on. A due one is sent on the next poll.
            if firing:
                await _mark_message_missed(bot, reminder, "the next one is due" if latest else "no response for 24 h")
            reminders.advance(reminder.id, latest or upcoming)
            return

    elif gave_up:
        reminders.mark_missed(reminder.id)
        await _mark_message_missed(bot, reminder, "no response for 24 h")
        return

    if is_quiet(now, quiet, tz):
        if firing:
            # Don't nag at night: the next repeat waits until quiet hours end.
            reminders.postpone(reminder.id, quiet_end(now, quiet, tz))
            return
        if recurrence is not None and (later := skip_quiet(recurrence, reminder.remind_at, quiet, tz)) != reminder.remind_at:
            # "every 2 hours" occurrence at night: skip to the first one after.
            reminders.advance(reminder.id, later)
            return

    text = f"⏰ {reminder.text}"
    if reminder.fire_count > 0:
        text += "\n\n🔁 Still waiting for your OK."

    try:
        message = await bot.send_message(
            chat_id=reminder.chat_id, text=text, reply_markup=build_fire_keyboard(reminder.id, snooze_minutes),
        )
    except Forbidden:
        # The user blocked the bot or deleted the chat; retrying won't help.
        logger.warning("Reminder %s undeliverable (blocked); marking failed", reminder.id)
        reminders.mark_failed(reminder.id)
        return

    # Only one copy on screen: remove the previous repeat.
    await _delete(bot, reminder.chat_id, reminder.last_message_id)

    if reminders.mark_fired(reminder.id, message.message_id, now + repeat_every) is None:
        # Acknowledged or cancelled while we were sending.
        await _delete(bot, reminder.chat_id, message.message_id)
