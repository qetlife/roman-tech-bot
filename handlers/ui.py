"""Telegram UI helpers: the menu message, callback data, user_data keys."""

import re

from    telegram                    import Update
from    telegram.ext                import ContextTypes
from    telegram.error              import BadRequest

from    enums                       import Callback, CallbackPrefix, MessageSource, OptionAction, ReminderAction


# --- user_data keys ---------------------------------------------------------

# What the user's next plain message answers (an Awaiting value).
AWAITING = "awaiting"
# For Awaiting.EDIT: the id of the reminder being edited.
EDIT_REMINDER_ID = "edit_reminder_id"
# A reminder request waiting for the user to pick a timezone first.
PENDING_REQUEST = "pending_request"
# For Awaiting.REMINDER_TEXT: the time as the user gave it ("tomorrow at 12");
# for Awaiting.REMINDER_TIME: the reminder text ("call mom").
PENDING_PART = "pending_part"
# The message the bot is asking about (ask_what / ask_when), until a reminder
# is made: "that's wrong" meanwhile means the bot shouldn't have asked.
ASKED_REQUEST = "asked_request"
# Where ↩️ Back on ⏰ Reminder settings returns to (a Callback).
REMINDER_SETTINGS_BACK = "reminder_settings_back"
# What "that's wrong" refers to: the id of the reminder made from the user's
# last message, or None if that message wasn't understood (already saved).
LAST_REMINDER_ID = "last_reminder_id"


def message_source(update: Update) -> MessageSource:
    """Whether the message being handled was typed or a (transcribed) voice message."""
    return MessageSource.VOICE if update.effective_message.voice is not None else MessageSource.TYPED


# --- callback data ----------------------------------------------------------
# The values are the Callback, CallbackPrefix, ReminderAction and OptionAction
# enums in enums.py.

def reminder_callback(action: ReminderAction, reminder_id: int, *args) -> str:
    return ":".join([f"{CallbackPrefix.REMINDER}{action}", str(reminder_id), *map(str, args)])


def option_callback(prefix: CallbackPrefix, action: OptionAction, value: str = None) -> str:
    return f"{prefix}{action}" + (f":{value}" if value is not None else "")


def split_option(data: str, prefix: CallbackPrefix):
    """"snzopt:set:10,60" -> (OptionAction.SET, "10,60")."""
    action, _, value = data.removeprefix(prefix).partition(":")
    return OptionAction(action), value


def exact(*callbacks: Callback) -> str:
    """Handler pattern matching exactly these callbacks."""
    return "^(?:" + "|".join(re.escape(c) for c in callbacks) + ")$"


def prefixed(prefix: CallbackPrefix) -> str:
    """Handler pattern matching every callback with this prefix."""
    return "^" + re.escape(prefix)


# --- the menu message -------------------------------------------------------


async def render_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    """Render a menu screen as a single, long-lived message.

    - When triggered by an inline button (callback query), the existing
      message is edited in place.
    - When triggered by a command, the previously tracked menu message is
      edited; if that fails it is replaced with a fresh one.
    """
    chat_id = update.effective_chat.id
    query = update.callback_query

    if query is not None:
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
        except BadRequest as e:
            # Pressing a button that does not change the screen is harmless.
            if "not modified" not in str(e).lower():
                raise
        context.chat_data["menu_message_id"] = query.message.message_id
        return

    msg_id = context.chat_data.get("menu_message_id")
    if msg_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=reply_markup
            )
            return
        except BadRequest:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except BadRequest:
                pass

    msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    context.chat_data["menu_message_id"] = msg.message_id
