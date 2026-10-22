"""⏰ Reminders: create, edit, list, and the buttons on reminder messages.

A reminder is made by one user (its creator) for themselves or for one of
their contacts (its target, "remind anna …"), and is delivered to the
target's chat. Only the target presses ✅ OK and 💤; only the creator
↩️ Undo, ✏️ Edit and 👎 Wrong; either can cancel it from their list.
"""

import logging

from    datetime                        import datetime, timedelta
from    typing                          import Optional
from    zoneinfo                        import ZoneInfo

from    telegram                        import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.error                  import TelegramError
from    telegram.ext                    import ContextTypes

from    core                            import recurrence as recurrences
from    core.commands                   import matches, occurs_on, parse_day, search_words
from    core.contacts                   import split_name, unknown_name
from    core.parser                     import MissingText, MissingTime, ParseError, parse_reminder, time_answer
from    core.quiet                      import skip_quiet
from    core.settings                   import (
    QUIET_HOURS, SENDER_UPDATES, SNOOZE_MAX_MINUTES, SNOOZE_MIN_MINUTES, format_minutes, quiet_window,
)
from    core.timezones                  import format_when, user_now
from    db.models.reminder              import utcnow
from    db.repositories.contact         import ContactRepository
from    db.repositories.reminder        import ReminderRepository
from    db.repositories.settings        import SettingsRepository
from    db.repositories.user            import UserRepository
from    db.repositories.failed_message  import FailedMessageRepository
from    enums                           import (
    Awaiting, Callback, CallbackPrefix, ContactStatus, FailureReason, IntentName, MessageSource,
    ReminderAction, ReminderStatus,
)
from    handlers.failed                 import record, record_not_understood
from    handlers.people                 import display
from    handlers.settings               import ask_timezone
from    handlers.ui                     import (
    ASKED_REQUEST, AWAITING, EDIT_REMINDER_ID, LAST_REMINDER_ID, PENDING_CONTACT_ID, PENDING_PART, PENDING_REQUEST,
    message_source, reminder_callback, render_menu,
)


logger = logging.getLogger(__name__)

users = UserRepository()
contacts = ContactRepository()
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


def schedule_text(reminder, tz_name: str, rule_tz: str = None, whose: str = None) -> str:
    """"🗓 Tomorrow, 09:00 (in 9 h)" plus "🔁 every day at 09:00" if recurring.

    The time is shown in `tz_name`, the repeat in the timezone it was given
    in (`rule_tz`, its creator's); if those differ, "(Roman's time)" says whose.
    """
    text = f"🗓 {format_when(reminder.remind_at, tz_name, utcnow())}"
    if reminder.recurrence:
        rule_tz = rule_tz or tz_name
        text += f"\n🔁 {recurrences.parse(reminder.recurrence).describe(ZoneInfo(rule_tz))}"
        if rule_tz != tz_name and whose:
            text += f" ({whose} time)"
    return text


# --- reminders for others ---------------------------------------------------
# "tomorrow at 9" and "every day at 9" are read in the creator's timezone:
# they said it. The target sees the time in their own timezone, and their
# own settings (snooze, repeat interval, quiet hours) apply to it.

def creator_tz(reminder, user) -> str:
    """The timezone a reminder's time and repeat were given in: its creator's. `user` is whoever asks."""
    if reminder.creator_user_id == user.id:
        return user.timezone or "UTC"
    creator = users.get_by_id(reminder.creator_user_id)
    return (creator.timezone if creator else None) or "UTC"


def contact_name(owner_id, person) -> str:
    """What the owner calls `person` in 👥 People ("mom"), else how Telegram shows them."""
    contact = contacts.find(owner_id, person.id)
    return contact.name if contact is not None and contact.status != ContactStatus.DECLINED else display(person)


def from_line(creator) -> str:
    """Under a reminder someone else made: "📨 from Roman (@roman)"."""
    return f"📨 from {display(creator)}"


# What the creator is told; done and missed only with 📣 Updates from people on.
UPDATES = {
    ReminderStatus.DONE: "✅ {name} did it: {text}",
    ReminderStatus.MISSED: "❌ {name} missed it: {text}",
    ReminderStatus.CANCELLED: "🗑 {name} cancelled your reminder: {text}",
}


async def tell_creator(bot, reminder, what: ReminderStatus):
    """Tell whoever made a reminder for someone else that it was done, missed or cancelled."""
    if reminder.creator_user_id == reminder.target_user_id:
        return
    people = users.get_many({reminder.creator_user_id, reminder.target_user_id})
    creator, target = people.get(reminder.creator_user_id), people.get(reminder.target_user_id)
    if creator is None or target is None:
        return
    if what != ReminderStatus.CANCELLED and not settings.get(creator.id, SENDER_UPDATES):
        return
    text = UPDATES[what].format(name=contact_name(creator.id, target), text=reminder.text)
    try:
        await bot.send_message(chat_id=creator.telegram_id, text=text)
    except TelegramError:
        # They blocked the bot; the update isn't worth more than that.
        logger.info("Couldn't tell user %s about reminder %s", creator.telegram_id, reminder.id)


async def remind_someone(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str):
    """Intent action for "remind …" without "me": "remind anna tomorrow at 9 to …", or one's own."""
    user = users.get_or_create(update.effective_user.id)
    names = {}
    for contact, person in contacts.people_of(user.id):
        names[contact.name] = contact
        if person.username:
            names[f"@{person.username}"] = contact
    found = split_name(request, names)
    if found is not None:
        name, rest = found
        await create_reminder(update, context, rest, contact_id=names[name].id)
        return
    name = unknown_name(request, user_now(user.timezone or "UTC"))
    if name is not None:
        # Not a guess: “anna to call” shouldn't become your own reminder “anna to call”.
        context.user_data.pop(AWAITING, None)
        await update.effective_message.reply_text(
            f"Who's “{name}”? To remind someone, invite them in 👥 People first. "
            f"For yourself, say “remind me …”.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👥 People", callback_data=Callback.PEOPLE_MENU)]]),
        )
        return
    await create_reminder(update, context, request)


async def usable_contact(update: Update, context: ContextTypes.DEFAULT_TYPE, user, contact_id: int):
    """The user's contact `contact_id` if reminders can be sent to them; else None, after saying why."""
    contact = contacts.get(contact_id)
    if contact is not None and contact.owner_user_id == user.id and contact.status == ContactStatus.ACCEPTED:
        return contact
    context.user_data.pop(AWAITING, None)
    context.user_data.pop(PENDING_CONTACT_ID, None)
    if contact is not None and contact.owner_user_id == user.id and contact.status == ContactStatus.PENDING:
        await update.effective_message.reply_text(f"⏳ {contact.name} hasn't allowed reminders from you yet.")
    else:
        await update.effective_message.reply_text("That person isn't in your 👥 People any more.")
    return None


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
    The user's clock is that of the reminders they made, also for others.
    """
    now = utcnow()
    for reminder in reminders.list_created(user_id):
        if reminder.status != ReminderStatus.PENDING or reminder.recurrence is None:
            continue
        recurrence = recurrences.parse(reminder.recurrence)
        if isinstance(recurrence, recurrences.Interval):
            continue
        # Snoozed: remind_at isn't one of its occurrences any more.
        if recurrence.next_after(reminder.remind_at - timedelta(seconds=1), ZoneInfo(old_tz)) != reminder.remind_at:
            continue
        reminders.advance(reminder.id, recurrence.next_after(now, ZoneInfo(new_tz)))


async def create_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str, contact_id: int = None):
    """Intent action for "remind me ..." / "set a reminder ..."; for a contact with `contact_id`."""
    user = users.get_or_create(update.effective_user.id)
    whom = "you"
    if contact_id is None:
        context.user_data.pop(PENDING_CONTACT_ID, None)
    else:
        contact = await usable_contact(update, context, user, contact_id)
        if contact is None:
            return
        context.user_data[PENDING_CONTACT_ID] = contact_id
        whom = contact.name

    if not user.timezone:
        context.user_data[PENDING_REQUEST] = request
        await ask_timezone(update, context, "First, one-time setup. ")
        return

    try:
        parsed = parse_reminder(request, user_now(user.timezone))
    except MissingText:
        await ask_what(update, context, request, whom)
        return
    except MissingTime as e:
        if e.text:
            await ask_when(update, context, e.text, request=request, whom=whom)
            return
        await not_understood(update, context, request, e)
        return
    except ParseError as e:
        await not_understood(update, context, request, e)
        return

    await save_reminder(update, context, user, parsed, request)


async def answer_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str):
    """A reminder sent again after the bot asked (not understood, or the timezone first): for the same person."""
    await create_reminder(update, context, request, contact_id=context.user_data.get(PENDING_CONTACT_ID))


def pending_whom(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Who the reminder being asked about is for: a contact's name, or "you"."""
    contact_id = context.user_data.get(PENDING_CONTACT_ID)
    contact = contacts.get(contact_id) if contact_id is not None else None
    return contact.name if contact is not None else "you"


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

async def ask_what(update: Update, context: ContextTypes.DEFAULT_TYPE, when: str, whom: str = "you"):
    context.user_data[AWAITING] = Awaiting.REMINDER_TEXT
    context.user_data[PENDING_PART] = when
    context.user_data[ASKED_REQUEST] = when
    await update.effective_message.reply_text(f"⏰ {when}: what should I remind {whom} about?")


async def ask_when(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, prefix: str = "",
                   request: str = None, whom: str = "you"):
    context.user_data[AWAITING] = Awaiting.REMINDER_TIME
    context.user_data[PENDING_PART] = text
    if request is not None:
        context.user_data[ASKED_REQUEST] = request
    await update.effective_message.reply_text(
        f"{prefix}⏰ When should I remind {whom}: “{text}”?\n"
        "e.g. “tomorrow at 9”, “in 2 hours”, “every Monday at 8”"
    )


async def answer_what(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """The answer to ask_what: the text for the time given before."""
    when = context.user_data.pop(PENDING_PART, "")
    joiner = " " if text.lower().startswith(("to ", "about ", "that ")) else " to "
    await answer_reminder(update, context, f"{when}{joiner}{text}")


async def answer_when(update: Update, context: ContextTypes.DEFAULT_TYPE, when: str):
    """The answer to ask_when: the time for the text given before. Asks again if it isn't one."""
    user = users.get_or_create(update.effective_user.id)
    text = context.user_data.get(PENDING_PART, "")
    request = f"{time_answer(when)} to {text}"
    try:
        parsed = parse_reminder(request, user_now(user.timezone))
    except ParseError as e:
        # The text is known, so whatever failed is the time.
        record_not_understood(update, context, when, IntentName.REMINDER_WHEN, str(e))
        await ask_when(update, context, text, prefix=f"{e} ", whom=pending_whom(context))
        return
    context.user_data.pop(PENDING_PART, None)
    await save_reminder(update, context, user, parsed, request)


async def save_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, user, parsed, request: str):
    contact_id = context.user_data.get(PENDING_CONTACT_ID)
    target, for_whom = None, ""
    if contact_id is not None:
        # Checked again: they may have left 👥 People while the bot asked.
        contact = await usable_contact(update, context, user, contact_id)
        if contact is None:
            return
        target, for_whom = users.get_by_id(contact.contact_user_id), f" for {contact.name}"
    context.user_data.pop(AWAITING, None)
    context.user_data.pop(PENDING_CONTACT_ID, None)
    recurrence = parsed.recurrence.serialize() if parsed.recurrence else None
    # The quiet hours of whoever gets it
    when = outside_quiet_hours(target or user, parsed.recurrence, parsed.when)
    reminder = reminders.create(
        user, target.telegram_id if target else update.effective_chat.id, parsed.text, when, recurrence,
        request, message_source(update), target=target,
    )
    context.user_data[LAST_REMINDER_ID] = reminder.id
    await update.effective_message.reply_text(
        f"⏰ Got it{for_whom}: {reminder.text}\n{schedule_text(reminder, user.timezone)}",
        reply_markup=build_created_keyboard(reminder.id),
    )


async def edit_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, reminder_id: int, request: str):
    user = users.get_or_create(update.effective_user.id)
    reminder = reminders.get_created(reminder_id, update.effective_user.id)
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
    target = user if reminder.target_user_id == user.id else users.get_by_id(reminder.target_user_id)
    when = outside_quiet_hours(target, parsed.recurrence, parsed.when)
    updated = reminders.reschedule(reminder.id, parsed.text, when, recurrence, request, message_source(update))
    if updated is None:
        await update.effective_message.reply_text("That reminder has already finished.")
        return
    context.user_data[LAST_REMINDER_ID] = updated.id
    await retire_fired_message(context, reminder, "✏️ Edited, see the updated reminder below.")
    for_whom = f" for {contact_name(user.id, target)}" if target.id != user.id else ""
    await update.effective_message.reply_text(
        f"✏️ Updated{for_whom}: {updated.text}\n{schedule_text(updated, user.timezone)}",
        reply_markup=build_created_keyboard(updated.id),
    )


async def on_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu button: ➕ New reminder."""
    await update.callback_query.answer()
    context.user_data[AWAITING] = Awaiting.REMINDER
    context.user_data.pop(PENDING_CONTACT_ID, None)
    await update.effective_message.reply_text(f"What should I remind you about, and when?\n\n{EXAMPLES}")


# --- listing ----------------------------------------------------------------

def list_items(user) -> list:
    """What the 📋 list shows: the user's reminders (sent to them too), then those they made for others."""
    return reminders.list_active(user.id) + reminders.list_sent(user.id)


def reminders_list_text(user, items, title: str = "Your reminders", empty: str = "You have no upcoming reminders.") -> str:
    """The numbered list; reminders for others (which come last) under "For others"."""
    if not items:
        return empty
    tz_name = user.timezone or "UTC"
    others = users.get_many({r.creator_user_id for r in items} | {r.target_user_id for r in items} - {user.id})
    lines = [f"{title} (tap ❌ to cancel):", ""]
    for n, r in enumerate(items, 1):
        if r.target_user_id != user.id:
            if n == 1:
                lines.append("For others:")
            elif items[n - 2].target_user_id == user.id:
                lines += ["", "For others:"]
            target = others.get(r.target_user_id)
            name = contact_name(user.id, target) if target else "Someone"
            title_line, details = f"{name}: {r.text}", [schedule_text(r, tz_name)]
        elif r.creator_user_id != user.id and (creator := others.get(r.creator_user_id)) is not None:
            whose = f"{creator.first_name}'s" if creator.first_name else "their"
            title_line = r.text
            details = [from_line(creator), schedule_text(r, tz_name, creator.timezone or "UTC", whose)]
        else:
            title_line, details = r.text, [schedule_text(r, tz_name)]
        lines.append(f"{n}. {title_line}")
        lines += ["    " + line for detail in details for line in detail.split("\n")]
    return "\n".join(lines)


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = "", toast: str = None):
    """Intent action for "my reminders" (and "my reminders on friday"), and the 📋 menu button."""
    user = users.get_or_create(update.effective_user.id)
    day = parse_day(request, user_now(user.timezone or "UTC")) if request.strip() else None
    if day is not None:
        await show_day(update, user, day)
        return
    # Anything else after the phrase ("my reminders please") is ignored.
    items = list_items(user)
    text = reminders_list_text(user, items)
    keyboard = build_reminders_list_keyboard(items)

    if update.callback_query is not None:
        await update.callback_query.answer(toast)
        await render_menu(update, context, text, keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def agenda(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "what do I have tomorrow?"; without a day, today."""
    user = users.get_or_create(update.effective_user.id)
    now = user_now(user.timezone or "UTC")
    day = parse_day(request, now) if request.strip().strip("?!. ") else now.date()
    if day is None:
        await update.effective_message.reply_text(
            "I can show one day, e.g. “what do I have tomorrow?” or “what's on friday?”."
        )
        return
    await show_day(update, user, day)


async def show_day(update: Update, user, day):
    """The user's reminders due on `day` (also those sent to them), repeats included, as a reply."""
    tz = ZoneInfo(user.timezone or "UTC")
    items = reminders.list_active(user.id)
    rule_tzs = users.get_timezones({r.creator_user_id for r in items})
    items = [r for r in items if occurs_on(r.remind_at, r.recurrence, day, tz, r.created_at,
                                            ZoneInfo(rule_tzs.get(r.creator_user_id) or "UTC"))]
    title = f"{day:%a %d %b}"
    await update.effective_message.reply_text(
        reminders_list_text(user, items, f"Your reminders on {title}", f"Nothing on {title}. 🎉"),
        reply_markup=build_reminders_list_keyboard(items),
    )


async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "cancel the dentist reminder": cancels the one that matches, or asks which."""
    user = users.get_or_create(update.effective_user.id)
    items = list_items(user)
    words = search_words(request)
    found = [r for r in items if matches(r.text, words)] if words else items
    reply = update.effective_message.reply_text

    if words and len(found) == 1:
        # Asked, not done: a loose match shouldn't cancel the wrong one.
        [reminder] = found
        await reply(
            f"Cancel “{reminder.text}”?\n{schedule_text(reminder, user.timezone or 'UTC')}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "❌ Cancel it", callback_data=reminder_callback(ReminderAction.DELETE, reminder.id),
            )]]),
        )
        return
    if words and not found:
        await reply(reminders_list_text(user, items, f"No reminder matches “{' '.join(words)}”. Yours",
                                        f"No reminder matches “{' '.join(words)}”."),
                    reply_markup=build_reminders_list_keyboard(items))
        return
    await reply(reminders_list_text(user, found, "Which one? Your reminders"),
                reply_markup=build_reminders_list_keyboard(found))


# --- buttons ----------------------------------------------------------------

# Who may press what: the one it reminds answers it, the one who made it
# changes it; ❌ in a list (DELETE) is for both.
TARGET_ACTIONS = {ReminderAction.OK, ReminderAction.SNOOZE}
CREATOR_ACTIONS = {ReminderAction.UNDO, ReminderAction.EDIT, ReminderAction.WRONG}


async def _own_reminder(update: Update, reminder_id: int, action: ReminderAction):
    """(the reminder, the user) if whoever pressed the button may use it, else (None, user)."""
    user = users.get_or_create(update.effective_user.id)
    reminder = reminders.get(reminder_id)
    allowed = set()
    if reminder is not None:
        if action not in CREATOR_ACTIONS:
            allowed.add(reminder.target_user_id)
        if action not in TARGET_ACTIONS:
            allowed.add(reminder.creator_user_id)
    if user.id not in allowed:
        await update.callback_query.answer("This reminder isn't yours.", show_alert=True)
        return None, user
    return reminder, user


async def on_reminder_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, reminder_id, *args = query.data.removeprefix(CallbackPrefix.REMINDER).split(":")
    action, reminder_id = ReminderAction(action), int(reminder_id)

    reminder, user = await _own_reminder(update, reminder_id, action)
    if reminder is None:
        return

    if action == ReminderAction.OK:
        text = finish(user, reminder)
        if text is None:
            # A stale message; the reminder has already moved on.
            await query.answer("Already done.")
            await query.edit_message_reply_markup(reply_markup=None)
            return
        await query.answer("Done!")
        await query.edit_message_text(text)
        await tell_creator(context.bot, reminder, ReminderStatus.DONE)

    elif action == ReminderAction.SNOOZE:
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
            if user.id == reminder.target_user_id:
                await tell_creator(context.bot, reminder, ReminderStatus.CANCELLED)
        await list_reminders(update, context, toast="Cancelled")

    elif action == ReminderAction.WRONG:
        await query.answer("Deleted and saved as failed")
        # Shown on the confirmation itself, like ↩️ Undo, so its buttons go away.
        await query.edit_message_text(await flag_wrong(update, context, reminder))


def finish(user, reminder) -> Optional[str]:
    """✅ OK by `user`, its target: a one-off is done, a repeat moves on to its next time.

    The reminder message's new text, or None if it was already done (a repeat
    that isn't firing has already moved on).
    """
    if not reminder.recurrence:
        if reminders.acknowledge(reminder.id) is None:
            return None
        return f"✅ {reminder.text}"
    if reminder.status != ReminderStatus.FIRING:
        return None
    # The next time is the creator's clock; it's shown in the user's.
    tz_name, rule_tz = user.timezone or "UTC", creator_tz(reminder, user)
    recurrence = recurrences.parse(reminder.recurrence)
    next_at = recurrence.next_after(max(utcnow(), reminder.remind_at), ZoneInfo(rule_tz))
    next_at = outside_quiet_hours(user, recurrence, next_at)
    if reminders.advance(reminder.id, next_at) is None:
        return f"✅ {reminder.text}"
    return f"✅ {reminder.text}\n\nNext: {format_when(next_at, tz_name, utcnow())}"


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
        reminder = reminders.get_created(reminder_id, update.effective_user.id)
    else:
        reminder = reminders.latest_created(update.effective_user.id)
    if reminder is None:
        await reply("There's no reminder to save as failed yet.")
        return
    await reply(await flag_wrong(update, context, reminder))
