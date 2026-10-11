"""Background loop that sends due reminders and repeats them until OK."""

import logging

from    datetime                    import timedelta

from    telegram.error              import Forbidden, TelegramError
from    telegram.ext                import ContextTypes

from    db.repository.reminder_repository import ReminderRepository
from    db.repository.settings_repository import SettingsRepository
from    models.reminder             import ReminderStatus, utcnow
from    reminders.handlers          import build_fire_keyboard
from    settings.registry           import REPEAT_MINUTES, SNOOZE_OPTIONS


logger = logging.getLogger(__name__)

reminders = ReminderRepository()
settings = SettingsRepository()

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

    for reminder in due:
        try:
            await _deliver(
                bot, reminder, now,
                snooze_options[reminder.target_user_id],
                timedelta(minutes=repeat_minutes[reminder.target_user_id]),
            )
        except Exception:
            # One broken reminder must not stop the others; it is retried next poll.
            logger.exception("Failed to deliver reminder %s", reminder.id)


async def _deliver(bot, reminder, now, snooze_minutes, repeat_every):
    if reminder.status == ReminderStatus.FIRING and now - reminder.remind_at >= GIVE_UP_AFTER:
        reminders.mark_missed(reminder.id)
        try:
            await bot.edit_message_text(
                chat_id=reminder.chat_id,
                message_id=reminder.last_message_id,
                text=f"⏰ {reminder.text}\n\n❌ Missed: no response for 24 h.",
            )
        except TelegramError:
            pass
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
