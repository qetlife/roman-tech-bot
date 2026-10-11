"""Background loop that sends due reminders and repeats them until OK."""

import logging

from    datetime                    import timedelta
from    zoneinfo                    import ZoneInfo

from    telegram.error              import Forbidden, TelegramError
from    telegram.ext                import ContextTypes

from    db.repository.reminder_repository import ReminderRepository
from    db.repository.settings_repository import SettingsRepository
from    db.repository.user_repository import UserRepository
from    models.reminder             import ReminderStatus, utcnow
from    reminders.handlers          import build_fire_keyboard
from    reminders                   import recurrence as recurrences
from    settings.registry           import REPEAT_MINUTES, SNOOZE_OPTIONS


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
    timezones = users.get_timezones(user_ids)

    for reminder in due:
        try:
            await _deliver(
                bot, reminder, now,
                snooze_options[reminder.target_user_id],
                timedelta(minutes=repeat_minutes[reminder.target_user_id]),
                ZoneInfo(timezones.get(reminder.target_user_id) or "UTC"),
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


async def _deliver(bot, reminder, now, snooze_minutes, repeat_every, tz):
    firing = reminder.status == ReminderStatus.FIRING
    gave_up = firing and now - reminder.remind_at >= GIVE_UP_AFTER

    if reminder.recurrence:
        latest, upcoming = _catch_up(recurrences.parse(reminder.recurrence), reminder, now, tz)
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
