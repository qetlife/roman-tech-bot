"""Replies to a reminder message: "done", "snooze 20 min", "move it to 10", "cancel".

A Telegram reply to a delivered reminder acts on that reminder, like its
buttons. Replies that aren't a command (core/replies.py) are handled like
any other message.
"""

from    datetime                    import timedelta

from    telegram                    import Update
from    telegram.ext                import ContextTypes

from    core.parser                 import ParseError, parse_reminder
from    core.replies                import parse_reply
from    core.settings               import SNOOZE_MAX_MINUTES, SNOOZE_MIN_MINUTES, SNOOZE_OPTIONS
from    core.timezones              import format_when, user_now
from    db.models.reminder          import utcnow
from    db.repositories.reminder    import ReminderRepository
from    db.repositories.settings    import SettingsRepository
from    db.repositories.user        import UserRepository
from    enums                       import ReminderStatus, ReplyCommand
from    handlers                    import reminders as rh


# Stands in for the reminder's text when parsing the new time of "move it to …".
MOVE_PLACEHOLDER = "x"

reminders = ReminderRepository()
settings = SettingsRepository()
users = UserRepository()


async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Act on a reply to a reminder message; False if the message isn't one."""
    replied = update.effective_message.reply_to_message
    if replied is None or replied.from_user is None or not replied.from_user.is_bot:
        return False
    command = parse_reply(text)
    if command is None:
        return False
    reminder = reminders.get_by_message(replied.message_id, update.effective_chat.id, update.effective_user.id)
    if reminder is None:
        return False

    reply = update.effective_message.reply_text
    user = users.get_or_create(update.effective_user.id)
    tz_name = user.timezone or "UTC"

    if command.command == ReplyCommand.DONE:
        done = rh.finish(user, reminder)
        if done is None:
            await reply(f"✅ Already done: {reminder.text}")
            return True
        await rh.retire_fired_message(context, reminder, done)
        await reply(done)
        await rh.tell_creator(context.bot, reminder, ReminderStatus.DONE)

    elif command.command == ReplyCommand.SNOOZE:
        minutes = (command.snooze.total_seconds() // 60 if command.snooze
                   else settings.get(user.id, SNOOZE_OPTIONS)[0])
        minutes = min(max(int(minutes), SNOOZE_MIN_MINUTES), SNOOZE_MAX_MINUTES)
        until = utcnow() + timedelta(minutes=minutes)
        reminders.snooze(reminder.id, until)
        note = f"💤 Snoozed until {format_when(until, tz_name, utcnow())}"
        await rh.retire_fired_message(context, reminder, note)
        await reply(f"💤 {reminder.text}\n{note.removeprefix('💤 ')}")

    elif command.command == ReplyCommand.MOVE:
        try:
            # Only the reply's time: words in the reminder's text ("pay rent at 5") don't count.
            parsed = parse_reminder(f"{command.when} to {MOVE_PLACEHOLDER}", user_now(tz_name))
            if parsed.text != MOVE_PLACEHOLDER:
                raise ParseError("I couldn't understand when.")
        except ParseError as e:
            await reply(f"{e} Try e.g. “move it to 10” or “move it to tomorrow at 9”.")
            return True
        if parsed.recurrence:
            await reply("To change how it repeats, use ✏️ Edit on its confirmation.")
            return True
        if reminder.recurrence:
            # A repeat: only this time moves; the repeat stays as it is.
            reminders.snooze(reminder.id, parsed.when)
        else:
            reminders.reschedule(reminder.id, reminder.text, parsed.when, None, reminder.request, reminder.source)
        note = f"🗓 Moved to {format_when(parsed.when, tz_name, utcnow())}"
        await rh.retire_fired_message(context, reminder, note)
        await reply(f"⏰ {reminder.text}\n{note}")

    elif command.command == ReplyCommand.CANCEL:
        if reminders.cancel(reminder.id) is not None:
            await rh.tell_creator(context.bot, reminder, ReminderStatus.CANCELLED)
        await rh.retire_fired_message(context, reminder, "↩️ Cancelled.")
        await reply(f"↩️ Cancelled: {reminder.text}")

    return True
