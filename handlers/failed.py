"""👎 Failed messages: what the bot didn't understand, or got wrong.

Saved automatically when the bot doesn't understand a message, and when the
user flags a reminder (👎 Wrong, "that's wrong"; see handlers/reminders.py).
Only the admin (ADMIN_TELEGRAM_ID) can list them with /failed, tap ✅ once
the parser handles them, or 🗑 to ignore one that can't be learned. Most
are closed automatically: see jobs/failed.py and scripts/failed.py.
"""

import logging

from    datetime                        import datetime
from    zoneinfo                        import ZoneInfo

from    telegram                        import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext                    import ContextTypes

import  config

from    core                            import recurrence as recurrences
from    core.timezones                  import to_local
from    db.repositories.failed_message  import FailedMessageRepository
from    db.repositories.user            import UserRepository
from    enums                           import CallbackPrefix, FailureReason, MessageSource
from    handlers.ui                     import LAST_EVENT_ID, LAST_REMINDER_ID, message_source


logger = logging.getLogger(__name__)

failed = FailedMessageRepository()
users = UserRepository()

# Entries shown by /failed (newest first); Telegram messages are limited in length.
LIST_LIMIT = 10
TEXT_LIMIT = 120


# --- saving -----------------------------------------------------------------

def record(update: Update, reason: FailureReason, text: str, source: MessageSource = None,
           intent: str = None, bot_understood: dict = None, reminder_id: int = None, event_id: int = None):
    """Save a failed message. A database error is logged, never shown: the reply still goes out."""
    try:
        user = users.get_or_create(update.effective_user.id)
        return failed.create(
            user.id, text, source or message_source(update), reason, intent, bot_understood, reminder_id, event_id,
        )
    except Exception:
        logger.exception("Failed to save a failed message from %s", update.effective_user.id)
        return None


def record_not_understood(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str,
                          intent: str = None, error: str = None):
    """The bot is about to say it didn't understand `text`."""
    record(update, FailureReason.NOT_UNDERSTOOD, text, intent=intent,
           bot_understood={"error": error} if error else None)
    # "that's wrong" now means this message, which is already saved.
    context.user_data[LAST_REMINDER_ID] = None
    context.user_data.pop(LAST_EVENT_ID, None)


# --- /failed ----------------------------------------------------------------

def is_admin(update: Update) -> bool:
    return config.ADMIN_TELEGRAM_ID is not None and update.effective_user.id == config.ADMIN_TELEGRAM_ID


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def describe(entry, tz_name: str) -> str:
    """What went wrong, e.g. "👎 Wrong: Thu 22 Oct, 09:00 · “at 21.20 to call mom”"."""
    understood = entry.bot_understood or {}
    if entry.reason == FailureReason.NOT_UNDERSTOOD:
        return f"❓ Not understood: {understood['error']}" if understood.get("error") else "❓ Not understood"

    parts = []
    if understood.get("remind_at") or understood.get("starts_at"):
        when = to_local(datetime.fromisoformat(understood.get("remind_at") or understood["starts_at"]), tz_name)
        parts.append(f"{when:%a %d %b}" + (" (all day)" if understood.get("all_day") else f", {when:%H:%M}"))
    if understood.get("recurrence"):
        stored = understood["recurrence"]
        if recurrences.is_rrule(stored):
            # An event's: the time of day is its start's
            start = to_local(datetime.fromisoformat(understood.get("starts_at")), tz_name)
            parts.append(f"🔁 {recurrences.describe_rule(stored, start)}")
        else:
            parts.append(f"🔁 {recurrences.parse(stored).describe(ZoneInfo(tz_name))}")
    if understood.get("text"):
        parts.append(f"“{shorten(understood['text'], TEXT_LIMIT)}”")
    if understood.get("title"):
        parts.append(f"📅 “{shorten(understood['title'], TEXT_LIMIT)}”")
    return "👎 Wrong: " + " · ".join(parts) if parts else "👎 Wrong"


def failed_text(items, total: int, tz_name: str) -> str:
    if not items:
        return "👎 No failed messages. 🎉"
    lines = [f"👎 Failed messages: {total} open" + (f", newest {len(items)} shown" if total > len(items) else ""), ""]
    for n, entry in enumerate(items, 1):
        icon = "🎙" if entry.source == MessageSource.VOICE else "⌨️"
        lines.append(f"{n}. {icon} “{shorten(entry.text, TEXT_LIMIT)}”")
        lines.append(f"    {describe(entry, tz_name)}")
        if entry.fix_pr:
            lines.append(f"    🔧 Fix waiting in pull request #{entry.fix_pr}")
        elif entry.note:
            lines.append(f"    ⏳ Waiting for: {shorten(entry.note, TEXT_LIMIT)}")
        lines.append(f"    {to_local(entry.created_at, tz_name):%d %b, %H:%M}")
    lines += ["", "Tap ✅ <number> once the bot understands it, 🗑 <number> to ignore it."]
    return "\n".join(lines)


def build_failed_keyboard(items):
    """Rows of ✅ <n>, then rows of 🗑 <n>, five to a row."""
    if not items:
        return None
    rows = []
    for icon, prefix in (("✅", CallbackPrefix.FAILED_FIXED), ("🗑", CallbackPrefix.FAILED_IGNORED)):
        buttons = [
            InlineKeyboardButton(f"{icon} {n}", callback_data=f"{prefix}{entry.id}")
            for n, entry in enumerate(items, 1)
        ]
        rows += [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    return InlineKeyboardMarkup(rows)


def _screen(update: Update):
    user = users.get_or_create(update.effective_user.id)
    items = failed.list_open(LIST_LIMIT)
    return failed_text(items, failed.count_open(), user.timezone or "UTC"), build_failed_keyboard(items)


async def on_failed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/failed: the open failed messages (admin only; ignored for anyone else)."""
    if not is_admin(update):
        return
    text, keyboard = _screen(update)
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def on_failed_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✅ <n> / 🗑 <n> on the /failed list: mark that entry fixed or ignored."""
    query = update.callback_query
    if not is_admin(update):
        await query.answer("Only the admin can do this.", show_alert=True)
        return
    if query.data.startswith(CallbackPrefix.FAILED_IGNORED):
        failed.mark_ignored(int(query.data.removeprefix(CallbackPrefix.FAILED_IGNORED)), "ignored with 🗑 on /failed")
        await query.answer("Ignored")
    else:
        failed.mark_fixed(int(query.data.removeprefix(CallbackPrefix.FAILED_FIXED)), "marked with ✅ on /failed")
        await query.answer("Marked fixed")
    text, keyboard = _screen(update)
    await query.edit_message_text(text, reply_markup=keyboard)
