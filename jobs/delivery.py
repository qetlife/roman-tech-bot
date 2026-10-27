"""Background loop that sends due reminders and repeats them until OK.

A reminder goes to its target's chat with the target's settings (snooze
buttons, repeat interval, quiet hours); its repeat follows the clock of
whoever made it (handlers/reminders.py, reminders for others).
"""

import logging

from    datetime                    import timedelta
from    zoneinfo                    import ZoneInfo

from    telegram.error              import Forbidden, TelegramError
from    telegram.ext                import ContextTypes

from    core                        import recurrence as recurrences
from    core.quiet                  import is_quiet, quiet_end, skip_quiet
from    core.settings               import QUIET_HOURS, REPEAT_MINUTES, SNOOZE_OPTIONS, quiet_window
from    db.models.reminder          import utcnow
from    db.repositories.contact     import ContactRepository
from    db.repositories.event       import EventRepository
from    db.repositories.reminder    import ReminderRepository
from    db.repositories.settings    import SettingsRepository
from    db.repositories.user        import UserRepository
from    enums                       import ReminderStatus
from    handlers.events             import occurrence_line
from    handlers.reminders          import build_fire_keyboard, from_line, tell_creator


logger = logging.getLogger(__name__)

contacts = ContactRepository()
events = EventRepository()
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
    timezones = users.get_timezones(user_ids | {r.creator_user_id for r in due})
    # Who made the reminders for others, for "📨 from …"
    creators = users.get_many({r.creator_user_id for r in due if r.creator_user_id != r.target_user_id})
    # The events they follow, for "📅 padel: Today, 21:00 (in 30 min)"
    followed = events.get_many({r.event_id for r in due if r.event_id is not None})

    for reminder in due:
        try:
            await _deliver(
                bot, reminder, now,
                snooze_options[reminder.target_user_id],
                timedelta(minutes=repeat_minutes[reminder.target_user_id]),
                ZoneInfo(timezones.get(reminder.target_user_id) or "UTC"),
                quiet_window(quiet_hours[reminder.target_user_id]),
                rule_tz=ZoneInfo(timezones.get(reminder.creator_user_id) or "UTC"),
                creator=creators.get(reminder.creator_user_id),
                event=followed.get(reminder.event_id),
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


async def _unreachable(bot, reminder, creator):
    """A reminder for someone else can't reach them: they leave the creator's 👥 People, who is told.

    Like 🚫 Stop: their other reminders from the creator are cancelled too.
    Blocking the bot is the one way to say no without the bot.
    """
    contact = contacts.find(creator.id, reminder.target_user_id)
    removed = contacts.remove(contact.id, creator.id) if contact is not None else None
    if removed is None:
        # Already gone (removed, stopped, or by another reminder): nothing to say.
        return
    name, others = contact.name, len(removed.cancelled)
    text = (f"⚠️ I couldn't deliver “{reminder.text}” to {name}: they've blocked the bot or left Telegram. "
            f"I removed them from 👥 People")
    if others:
        text += " and cancelled your other " + ("reminder" if others == 1 else f"{others} reminders") + " for them"
    text += ". If they want your reminders again, send them a new invite."
    try:
        await bot.send_message(chat_id=creator.telegram_id, text=text)
    except TelegramError:
        logger.info("Couldn't tell user %s about reminder %s", creator.telegram_id, reminder.id)


def _catch_up(recurrence, reminder, now, tz):
    """(latest occurrence after remind_at that is already due or None, the one after it)."""
    latest = None
    upcoming = recurrence.next_after(reminder.remind_at, tz)
    # None: a repeat with an end (an event's "until December") has no more
    while upcoming is not None and upcoming <= now:
        latest, upcoming = upcoming, recurrence.next_after(upcoming, tz)
    return latest, upcoming


async def _deliver(bot, reminder, now, snooze_minutes, repeat_every, tz, quiet=None, rule_tz=None, creator=None,
                   event=None):
    """Send (or move on) one due reminder.

    `tz` and `quiet` are its target's, `rule_tz` the timezone its repeat is
    in (its creator's; `tz` if not given), `creator` who made it if that
    was someone else, `event` the event it follows, if any.
    """
    firing = reminder.status == ReminderStatus.FIRING
    gave_up = firing and now - reminder.remind_at >= GIVE_UP_AFTER

    recurrence = recurrences.parse(reminder.recurrence) if reminder.recurrence else None
    if recurrence is not None:
        latest, upcoming = _catch_up(recurrence, reminder, now, rule_tz or tz)
        if latest is not None or gave_up:
            # This occurrence is over: move on. A due one is sent on the next poll.
            if firing:
                await _mark_message_missed(bot, reminder, "the next one is due" if latest else "no response for 24 h")
                await tell_creator(bot, reminder, ReminderStatus.MISSED)
            if latest is None and upcoming is None:
                # That was the last one.
                reminders.mark_missed(reminder.id)
            else:
                reminders.advance(reminder.id, latest or upcoming)
            return

    elif gave_up:
        if reminders.mark_missed(reminder.id) is not None:
            await tell_creator(bot, reminder, ReminderStatus.MISSED)
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
    if event is not None:
        text += f"\n{occurrence_line(event, reminder, str(tz), now)}"
    if creator is not None:
        text += f"\n{from_line(creator)}"
    if reminder.fire_count > 0:
        text += "\n\n🔁 Still waiting for your OK."

    try:
        message = await bot.send_message(
            chat_id=reminder.chat_id, text=text, reply_markup=build_fire_keyboard(reminder.id, snooze_minutes),
        )
    except Forbidden:
        # The user blocked the bot or deleted the chat; retrying won't help.
        logger.warning("Reminder %s undeliverable (blocked); marking failed", reminder.id)
        # None if it was cancelled meanwhile, e.g. by _unreachable for another one in this poll.
        if reminders.mark_failed(reminder.id) is not None and creator is not None:
            await _unreachable(bot, reminder, creator)
        return

    # Only one copy on screen: remove the previous repeat.
    await _delete(bot, reminder.chat_id, reminder.last_message_id)

    if reminders.mark_fired(reminder.id, message.message_id, now + repeat_every) is None:
        # Acknowledged or cancelled while we were sending.
        await _delete(bot, reminder.chat_id, message.message_id)
