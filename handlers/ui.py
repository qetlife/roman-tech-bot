"""Telegram UI helpers: the menu message, callback data, user_data keys."""

import logging
import re

from    telegram                    import Update
from    telegram.ext                import ContextTypes
from    telegram.error              import BadRequest

from    core.conversation           import Conversation
from    db.models.reminder          import utcnow
from    enums                       import (
    Callback, CallbackPrefix, EventAction, ItemKind, MessageSource, OptionAction, ReminderAction,
)


# --- user_data keys ---------------------------------------------------------

# What the user's next plain message answers (an Awaiting value).
AWAITING = "awaiting"
# For Awaiting.CONTACT_NAME: the id of the contact being renamed.
RENAME_CONTACT_ID = "rename_contact_id"
# For Awaiting.EDIT: the id of the reminder being edited.
EDIT_REMINDER_ID = "edit_reminder_id"
# A reminder request waiting for the user to pick a timezone first.
PENDING_REQUEST = "pending_request"
# For Awaiting.REMINDER_TEXT: the time as the user gave it ("tomorrow at 12");
# for Awaiting.REMINDER_TIME: the reminder text ("call mom").
PENDING_PART = "pending_part"
# The message the bot is asking about (ask_what / ask_when): "that's wrong"
# while it still asks means it shouldn't have (handlers/text.py, the only
# reader, which checks `awaiting` too).
ASKED_REQUEST = "asked_request"
# The contact (id) the reminder being made is for ("remind anna …"), while the
# bot asks its time, its text or the timezone; unset for one's own.
PENDING_CONTACT_ID = "pending_contact_id"
# Where ↩️ Back on ⏰ Reminder settings returns to (a Callback).
REMINDER_SETTINGS_BACK = "reminder_settings_back"
# What "that's wrong" refers to: the id of the reminder made from the user's
# last message, or None if that message wasn't understood (already saved).
LAST_REMINDER_ID = "last_reminder_id"
# The id of the event made (or edited) from the user's last message: then
# "that's wrong" means it. Unset once a reminder is made or a message isn't understood.
LAST_EVENT_ID = "last_event_id"
# For Awaiting.EVENT_EDIT: the id of the event being edited.
EDIT_EVENT_ID = "edit_event_id"
# An event request waiting for the user to pick a timezone first.
PENDING_EVENT_REQUEST = "pending_event_request"
# A reminder relative to a repeating event, waiting for “just the next one, or
# every time?”: {"event_id", "minutes", "text", "request", "source", "contact_id"}.
PENDING_EVENT_REMINDER = "pending_event_reminder"
# What "it" and "the second one" mean for a while (a core.conversation.Conversation).
CONVERSATION = "conversation"
# What the waiting question is about, for “Dropped: …” when the user moves on:
# (the Awaiting value it was asked with, "the reminder “dentist”").
ASKED_ABOUT = "asked_about"
# The message asking the question that has answer buttons (What time? Which day?): only its buttons answer it.
ASKED_MESSAGE_ID = "asked_message_id"
# A message without a trigger phrase that could be an event or a reminder
# (“padel on thursday at 21:00”), waiting for 📅 Event / ⏰ Reminder.
PENDING_PICK = "pending_pick"


def conversation(context: ContextTypes.DEFAULT_TYPE, touch: bool = False):
    """The conversation if it's still fresh (core/conversation.py), else None.

    `touch` (on every message): it is the user's latest message now, so
    starts a new conversation if the old one went stale.
    """
    now = utcnow()
    current = context.user_data.get(CONVERSATION)
    if current is not None and not current.fresh(now):
        current = None
    if touch:
        current = current or Conversation(now)
        current.last = now
        context.user_data[CONVERSATION] = current
    else:
        context.user_data[CONVERSATION] = current
    return current


def about(context: ContextTypes.DEFAULT_TYPE, kind: ItemKind, item_id: int):
    """The bot made or changed this: now it is "it"."""
    conversation(context, touch=True).subject = (kind, item_id)


def listed(context: ContextTypes.DEFAULT_TYPE, kind: ItemKind, item_ids: list):
    """The bot showed these, numbered: now "the second one" is one of them."""
    conversation(context, touch=True).listed = [(kind, i) for i in item_ids]


def ask(context: ContextTypes.DEFAULT_TYPE, awaiting, about_what: str):
    """The bot asks a question (`awaiting`) about `about_what` ("the reminder “dentist”")."""
    context.user_data[AWAITING] = awaiting
    context.user_data[ASKED_ABOUT] = (awaiting, about_what)


async def remember_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Every update: store the user's Telegram first name and @username if they changed (known users only)."""
    user = update.effective_user
    if user is None:
        return
    try:
        # Imported here: db code isn't needed for the rest of this module.
        from db.repositories.user import UserRepository
        UserRepository().remember_profile(user.id, user.first_name, user.username)
    except Exception:
        logging.getLogger(__name__).exception("Failed to store the profile of %s", user.id)


def message_source(update: Update) -> MessageSource:
    """Whether the message being handled was typed or a (transcribed) voice message."""
    return MessageSource.VOICE if update.effective_message.voice is not None else MessageSource.TYPED


# --- callback data ----------------------------------------------------------
# The values are the Callback, CallbackPrefix, ReminderAction, EventAction and
# OptionAction enums in enums.py.

def reminder_callback(action: ReminderAction, reminder_id: int, *args) -> str:
    return ":".join([f"{CallbackPrefix.REMINDER}{action}", str(reminder_id), *map(str, args)])


def event_callback(action: EventAction, event_id: int, *args) -> str:
    return ":".join([f"{CallbackPrefix.EVENT}{action}", str(event_id), *map(str, args)])


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
