"""📅 Events: create, list, move, cancel, and reminders relative to them.

An event ("padel on thursday at 21:00", maybe every week) belongs to the
user who made it. Reminders can hang off it ("30 min before padel, remind me
to pack the racket"): they move when it moves (`follow`) and are cancelled
with it. For a repeating event the bot asks whether a reminder is for just
the next one or every time. The logic is in core/events.py.
"""

import logging

from    datetime                        import datetime, timedelta
from    typing                          import Optional
from    zoneinfo                        import ZoneInfo

from    telegram                        import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext                    import ContextTypes

from    core                            import recurrence as recurrences
from    core.commands                   import parse_day
from    core.conversation               import needs_day, read_weekday, with_day
from    core.events                     import (
    clean_text, duration, match_title, nearest_occurrence, next_occurrence, occurrence_on, occurs_on, parse_event,
    reminder_time, rrule, rule_of, skipped, split_move, split_move_statement, split_relative, unknown_title,
    with_skipped,
)
from    core.parser                     import MissingText, MissingTime, ParseError, parse_move, parse_reminder
from    core.timezones                  import format_delta, format_when, to_local, user_now
from    db.models.reminder              import utcnow
from    db.repositories.event           import EventRepository
from    db.repositories.failed_message  import FailedMessageRepository
from    db.repositories.reminder        import ReminderRepository
from    db.repositories.user            import UserRepository
from    enums                           import (
    Awaiting, Callback, CallbackPrefix, CardKind, EventAction, EventStatus, FailureReason, IntentName, ItemKind,
    MessageSource,
)
from    handlers                        import reminders as rh
from    handlers                        import report
from    handlers.failed                 import record, record_not_understood
from    handlers.settings               import ask_timezone
from    handlers.ui                     import (
    ASKED_MESSAGE_ID, ASKED_REQUEST, AWAITING, EDIT_EVENT_ID, LAST_EVENT_ID, LAST_REMINDER_ID, PENDING_CONTACT_ID,
    PENDING_EVENT_REMINDER, PENDING_EVENT_REQUEST, PENDING_PART, PENDING_PICK, about, ask, event_callback, listed,
    message_source, render_menu,
)


logger = logging.getLogger(__name__)

users = UserRepository()
events = EventRepository()
reminders = ReminderRepository()
failed = FailedMessageRepository()

# ⏰ buttons on an event: minutes from its start (negative: before)
QUICK_REMINDERS = (-15, -30, -60)
# On an all-day event (which starts at midnight): 09:00 the day before, 09:00 on the day
QUICK_ALL_DAY = ((-15 * 60, "the day before, 09:00"), (9 * 60, "on the day, 09:00"))
# A reminder at most 5 years from its event (minutes), typed or from a button's callback data
MAX_OFFSET = 5 * 365 * 24 * 60


# --- showing ----------------------------------------------------------------

def _day(local: datetime, now_local: datetime) -> str:
    if local.date() == now_local.date():
        return "Today"
    if local.date() == now_local.date() + timedelta(days=1):
        return "Tomorrow"
    return local.strftime("%a %d %b") + (f" {local.year}" if local.year != now_local.year else "")


def at_text(event, when: datetime, tz_name: str, now: datetime) -> str:
    """When the occurrence starting `when` is on.

    "Thu 23 Oct, 21:00 (in 2 d)", with an end "Thu 23 Oct, 21:00–22:30 (in 2 d)"
    or "Fri 24 Oct, 18:00 – Sun 26 Oct, 12:00"; all day "Thu 23 Oct (all day)"
    or "Fri 24 – Sun 26 Oct (all day)", in its own dates.
    """
    end = when + duration(event) if event.ends_at is not None or event.all_day else None
    if event.all_day:
        local, today = to_local(when, event.timezone), to_local(now, event.timezone)
        last = to_local(end - timedelta(seconds=1), event.timezone)
        if last.date() == local.date():
            return f"{_day(local, today)} (all day)"
        first = _day(local, today) if local.date() <= today.date() + timedelta(days=1) or local.month != last.month \
            else local.strftime("%a %d")
        return f"{first} – {_day(last, today)} (all day)"
    local, today = to_local(when, tz_name), to_local(now, tz_name)
    soon = f" (in {format_delta(when - now)})" if when > now else ""
    if end is None or end == when:
        return f"{_day(local, today)}, {local:%H:%M}{soon}"
    last = to_local(end, tz_name)
    if last.date() == local.date():
        return f"{_day(local, today)}, {local:%H:%M}–{last:%H:%M}{soon}"
    return f"{_day(local, today)}, {local:%H:%M} – {_day(last, today)}, {last:%H:%M}{soon}"


def repeat_text(event, tz_name: str) -> str:
    """"every Thu at 21:00", in the event's clock ("(Europe/Lisbon)" if that isn't the user's)."""
    text = rule_of(event).describe(ZoneInfo(event.timezone))
    if event.all_day:
        text = text.removesuffix(" at 00:00")
    if event.timezone != tz_name and not event.all_day:
        text += f" ({event.timezone})"
    return text


def when_text(event, tz_name: str, now: datetime = None) -> str:
    """"🗓 Thu 23 Oct, 21:00 (in 2 d)" plus "🔁 every Thu at 21:00" if it repeats."""
    now = now or utcnow()
    upcoming = next_occurrence(event, now)
    text = f"🗓 {at_text(event, upcoming or event.starts_at, tz_name, now)}"
    if event.recurrence:
        text += f"\n🔁 {repeat_text(event, tz_name)}"
    return text


def occurrence_line(event, reminder, tz_name: str, now: datetime) -> str:
    """Under a reminder that follows an event: "📅 padel: Today, 21:00 (in 30 min)"."""
    start = reminder.remind_at - timedelta(minutes=reminder.event_offset or 0)
    if event.recurrence:
        start = nearest_occurrence(event, start)
    else:
        start = event.starts_at
    return f"📅 {event.title}: {at_text(event, start, tz_name, now)}"


def upcoming_events(user, now: datetime = None) -> list:
    """(next time, event) of the user's events that aren't over, soonest first."""
    now = now or utcnow()
    found = [(next_occurrence(e, now), e) for e in events.list_active(user.id)]
    return sorted(((when, e) for when, e in found if when is not None), key=lambda pair: (pair[0], pair[1].id))


def titles_of(user) -> dict:
    """Title → the soonest upcoming event with it."""
    titles = {}
    for _, event in upcoming_events(user):
        titles.setdefault(event.title, event)
    return titles


def build_created_keyboard(event):
    """⏰ reminder buttons, then ↩️ Undo / ✏️ Edit / 👎 Wrong."""
    return InlineKeyboardMarkup([
        _quick_buttons(event),
        [
            InlineKeyboardButton("↩️ Undo", callback_data=event_callback(EventAction.UNDO, event.id)),
            InlineKeyboardButton("✏️ Edit", callback_data=event_callback(EventAction.EDIT, event.id)),
            InlineKeyboardButton("👎 Wrong", callback_data=event_callback(EventAction.WRONG, event.id)),
        ],
    ])


def _quick_buttons(event) -> list:
    if event.all_day:
        return [InlineKeyboardButton(f"⏰ {label}", callback_data=event_callback(EventAction.REMIND, event.id, m))
                for m, label in QUICK_ALL_DAY]
    return [InlineKeyboardButton(f"⏰ {recurrences.format_offset(m)}",
                                 callback_data=event_callback(EventAction.REMIND, event.id, m))
            for m in QUICK_REMINDERS]


def report_card(update: Update, sent, event, tz_name: str):
    """The web app's card for an event just made or changed (handlers/report.py)."""
    now = utcnow()
    when = next_occurrence(event, now) or event.starts_at
    local = to_local(when, event.timezone if event.all_day else tz_name)
    report.card(update, sent, CardKind.EVENT, title=event.title, date=local.date().isoformat(),
                time=None if event.all_day else f"{local:%H:%M}", when=at_text(event, when, tz_name, now),
                repeat=repeat_text(event, tz_name) if event.recurrence else None)


async def report_google(update: Update, context: ContextTypes.DEFAULT_TYPE, event, done: str):
    """Send the change to Google Calendar; a step in the web app if it got there."""
    if await to_google(context, event):
        report.step(update, done)


# --- creating ---------------------------------------------------------------

def understood(event) -> dict:
    """What the bot made of the message, kept with the failed message (👎 Wrong)."""
    return {"title": event.title, "starts_at": event.starts_at.isoformat(), "recurrence": event.recurrence,
            "all_day": event.all_day}


async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str):
    """Intent action for "event padel on thursday at 21:00"."""
    user = users.get_or_create(update.effective_user.id)
    if not user.timezone:
        context.user_data[PENDING_EVENT_REQUEST] = request
        await ask_timezone(update, context, "First, one-time setup. ")
        return
    if needs_day(request):
        await ask_day(update, context, request)
        return
    try:
        parsed = parse_event(request, user_now(user.timezone))
    except MissingText:
        await ask_title(update, context, request)
        return
    except MissingTime as e:
        if e.text:
            await ask_time(update, context, e.text, request=request)
            return
        await not_understood(update, context, request, e)
        return
    except ParseError as e:
        await not_understood(update, context, request, e)
        return
    await save_event(update, context, user, parsed, request)


async def put_in_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str):
    """Intent action for "put padel on thursday at 21:00 in my calendar" / "add … to my calendar"."""
    words = request.split()
    lowered = [w.lower().strip(".,!:") for w in words]
    places = ("in", "on", "to", "into")
    if len(words) >= 3 and lowered[-3] in places and lowered[-2] in ("my", "the") and lowered[-1] == "calendar":
        await create_event(update, context, " ".join(words[:-3]))
        return
    if len(words) >= 3 and lowered[0] in places and lowered[1] in ("my", "the") and lowered[2] == "calendar":
        await create_event(update, context, " ".join(words[3:]))
        return
    record_not_understood(update, context, update.effective_message.text or request)
    await update.effective_message.reply_text(
        "I didn't get that."
    )


async def not_understood(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str, error: ParseError):
    record_not_understood(update, context, request, IntentName.EVENT_CREATE, str(error))
    context.user_data[AWAITING] = Awaiting.EVENT
    await update.effective_message.reply_text(
        f"{error} Send it again."
    )


async def answer_event(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str):
    """An event sent after the bot asked (📅 ➕ New, not understood, or the timezone first)."""
    await create_event(update, context, request)


async def ask_title(update: Update, context: ContextTypes.DEFAULT_TYPE, when: str):
    ask(context, Awaiting.EVENT_TITLE, f"the event on {when}")
    context.user_data[PENDING_PART] = when
    context.user_data[ASKED_REQUEST] = when
    await update.effective_message.reply_text(f"📅 {when}: what's the event?")


async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str, prefix: str = "",
                   request: str = None):
    ask(context, Awaiting.EVENT_TIME, f"the event “{title}”")
    context.user_data[PENDING_PART] = title
    if request is not None:
        context.user_data[ASKED_REQUEST] = request
    await update.effective_message.reply_text(
        f"{prefix}📅 When is “{title}”?"
    )


async def ask_day(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str, prefix: str = ""):
    """ "event yoga every week at 19:00": which day? The answer goes into the request (answer_day)."""
    ask(context, Awaiting.EVENT_DAY, "the weekly event")
    context.user_data[PENDING_PART] = request
    context.user_data[ASKED_REQUEST] = request
    asked = await update.effective_message.reply_text(f"{prefix}📅 Every week: on which day?",
                                                      reply_markup=rh.day_keyboard())
    # Its buttons answer this question only, not a later one
    context.user_data[ASKED_MESSAGE_ID] = asked.message_id


async def answer_day(update: Update, context: ContextTypes.DEFAULT_TYPE, answer: str):
    """The answer to ask_day: "monday", "on fri". Asks again if it isn't a day of the week."""
    request = context.user_data.get(PENDING_PART, "")
    weekday = read_weekday(answer)
    if weekday is None:
        record_not_understood(update, context, answer, IntentName.EVENT_WHEN, "not a day of the week")
        await ask_day(update, context, request, "That isn't a day of the week. ")
        return
    context.user_data.pop(PENDING_PART, None)
    await create_event(update, context, with_day(request, weekday))


async def answer_title(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str):
    """The answer to ask_title: the title for the time given before."""
    when = context.user_data.pop(PENDING_PART, "")
    await create_event(update, context, f"{when}: {title}")


async def answer_time(update: Update, context: ContextTypes.DEFAULT_TYPE, when: str):
    """The answer to ask_time: the time for the title given before. Asks again if it isn't one."""
    user = users.get_or_create(update.effective_user.id)
    title = context.user_data.get(PENDING_PART, "")
    request = f"{when}: {title}"
    try:
        parsed = parse_event(request, user_now(user.timezone))
    except ParseError as e:
        # The title is known, so whatever failed is the time.
        record_not_understood(update, context, when, IntentName.EVENT_WHEN, str(e))
        await ask_time(update, context, title, prefix=f"{e} ")
        return
    context.user_data.pop(PENDING_PART, None)
    await save_event(update, context, user, parsed, request)


async def save_event(update: Update, context: ContextTypes.DEFAULT_TYPE, user, parsed, request: str):
    context.user_data.pop(AWAITING, None)
    recurrence = recurrences.to_rrule(parsed.recurrence) if parsed.recurrence else None
    event = events.create(
        user.id, parsed.title, parsed.starts_at, user.timezone, recurrence, parsed.all_day,
        request, message_source(update),
    )
    context.user_data[LAST_EVENT_ID] = event.id
    about(context, ItemKind.EVENT, event.id)
    said = repeat_text(event, user.timezone) if event.recurrence \
        else report.when(at_text(event, event.starts_at, user.timezone, utcnow()))
    report.step(update, f"Understood: an event, {said}")
    report.step(update, f"Saved “{event.title}”")
    sent = await update.effective_message.reply_text(
        f"📅 Added: {event.title}\n{when_text(event, user.timezone)}\n\nA reminder before it?",
        reply_markup=build_created_keyboard(event),
    )
    report_card(update, sent, event, user.timezone)
    await report_google(update, context, event, "Added to Google Calendar")


async def on_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu button: 📅 ➕ New event."""
    await update.callback_query.answer()
    context.user_data[AWAITING] = Awaiting.EVENT
    await update.effective_message.reply_text("What's the event, and when?")


# --- editing and moving -----------------------------------------------------

async def follow(context: ContextTypes.DEFAULT_TYPE, old, event) -> int:
    """The event changed (`old` is how it was): its reminders move with it. Returns how many moved.

    "Every time" ones follow its new repeat; one for a single occurrence of
    a repeating event moves to the occurrence nearest the old one, or is
    cancelled if that one is skipped; one for a one-off moves with its start.
    """
    now = utcnow()
    moved = 0
    for reminder in reminders.list_for_event(event.id):
        minutes = reminder.event_offset or 0
        delta = timedelta(minutes=minutes)
        if event.recurrence and reminder.recurrence:
            when, rule = reminder_time(event, minutes, now, every=True)
            recurrence = rule.serialize()
            if rule.next_after(reminder.remind_at - timedelta(seconds=1), ZoneInfo(event.timezone)) == reminder.remind_at:
                # Its occurrence still happens: only the repeat (skipped days) changes.
                when = reminder.remind_at
            elif when is None:
                # The repeat has ended (it got an "until")
                if reminders.cancel(reminder.id) is not None:
                    await rh.retire_fired_message(context, reminder, f"↩️ Cancelled: no more {event.title}.")
                continue
        elif event.recurrence:
            before = reminder.remind_at - delta
            occurrence = nearest_occurrence(event, before) if old.recurrence else next_occurrence(event, now)
            if occurrence is None or occurrence in skipped(event):
                if reminders.cancel(reminder.id) is not None:
                    await rh.retire_fired_message(context, reminder, f"↩️ Cancelled: no {event.title} that day.")
                continue
            when, recurrence = occurrence + delta, None
        else:
            when, recurrence = event.starts_at + delta, None
        if when == reminder.remind_at:
            if recurrence != reminder.recurrence:
                reminders.relink(reminder.id, recurrence)
            continue
        if reminders.follow_event(reminder.id, when, recurrence) is not None:
            moved += 1
            await rh.retire_fired_message(context, reminder, f"📅 {event.title} moved, and this reminder with it.")
    return moved


def _moved_note(moved: int) -> str:
    if not moved:
        return ""
    return "\n⏰ " + ("Its reminder moved" if moved == 1 else f"Its {moved} reminders moved") + " with it."


async def start_edit(context: ContextTypes.DEFAULT_TYPE, event, reply):
    """Ask for the new time and title of an event (✏️ Edit)."""
    context.user_data[AWAITING] = Awaiting.EVENT_EDIT
    context.user_data[EDIT_EVENT_ID] = event.id
    await reply(f"Send the new time and title for “{event.title}”.")


async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, request: str):
    """The answer to ✏️ Edit: a new time and title; its reminders follow."""
    user = users.get_or_create(update.effective_user.id)
    event = events.get(event_id)
    if event is None or event.user_id != user.id:
        context.user_data.pop(AWAITING, None)
        await update.effective_message.reply_text("That event no longer exists.")
        return
    try:
        parsed = parse_event(request, user_now(event.timezone))
    except ParseError as e:
        record_not_understood(update, context, request, IntentName.EVENT_EDIT, str(e))
        await update.effective_message.reply_text(f"{e} Try again.")
        return
    context.user_data.pop(AWAITING, None)
    updated = events.update(
        event.id, title=parsed.title, starts_at=parsed.starts_at, ends_at=None, all_day=parsed.all_day, skipped=None,
        moved=None, recurrence=recurrences.to_rrule(parsed.recurrence) if parsed.recurrence else None,
        request=request, source=message_source(update),
    )
    if updated is None:
        await update.effective_message.reply_text("That event has been cancelled.")
        return
    moved = await follow(context, event, updated)
    context.user_data[LAST_EVENT_ID] = updated.id
    about(context, ItemKind.EVENT, updated.id)
    report.step(update, f"Updated “{updated.title}”")
    if moved:
        report.step(update, _moved_note(moved).strip().removeprefix("⏰ "))
    sent = await update.effective_message.reply_text(
        f"✏️ Updated: {updated.title}\n{when_text(updated, user.timezone)}{_moved_note(moved)}",
        reply_markup=build_created_keyboard(updated),
    )
    report_card(update, sent, updated, user.timezone)
    await report_google(update, context, updated, "Updated in Google Calendar")


async def move_event(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str):
    """Intent action for "move padel to 20:00" / "reschedule padel to friday"."""
    user = users.get_or_create(update.effective_user.id)
    found = split_move(request, titles_of(user))
    if found is None:
        name = unknown_title(request.split())
        await update.effective_message.reply_text(
            f"I don't have an event called “{name}”. See 📅 Events for yours.",
            reply_markup=_events_button(),
        )
        return
    title, phrase = found
    await move(update, context, user, titles_of(user)[title], phrase, request)


async def move(update: Update, context: ContextTypes.DEFAULT_TYPE, user, event, phrase: str, request: str):
    """Move `event` to the time in `phrase`, in the event's clock; what isn't said stays."""
    now = user_now(event.timezone)
    current = next_occurrence(event, utcnow()) or event.starts_at
    rule = rrule(event)
    moved = parse_move(phrase, current, now, rule) if phrase else None
    reply = update.effective_message.reply_text
    if moved is None:
        record_not_understood(update, context, request, IntentName.EVENT_MOVE, "couldn't read the new time")
        hint = " For a bigger change, ✏️ Edit it in 📅 Events." if rule is not None else ""
        await reply(f"I couldn't understand the new time.{hint}")
        return
    all_day = event.all_day and not moved.timed
    when = moved.when
    if all_day:
        when = datetime.combine(when.date(), datetime.min.time(), tzinfo=when.tzinfo)
    if moved.rule is None and (when.date() < now.date() if all_day else when <= now):
        await reply("That time has already passed.")
        return
    # It lasts as long as before; the skipped and moved days were of the old times.
    length = event.ends_at - event.starts_at if event.ends_at is not None else None
    updated = events.update(
        event.id, starts_at=when, ends_at=when + length if length is not None else None, recurrence=moved.rule,
        all_day=all_day, skipped=None, moved=None,
    )
    if updated is None:
        await reply("That event has been cancelled.")
        return
    count = await follow(context, event, updated)
    about(context, ItemKind.EVENT, updated.id)
    report.step(update, f"Moved “{updated.title}”")
    if count:
        report.step(update, _moved_note(count).strip().removeprefix("⏰ "))
    sent = await reply(f"📅 Moved: {updated.title}\n{when_text(updated, user.timezone)}{_moved_note(count)}",
                       reply_markup=build_created_keyboard(updated))
    report_card(update, sent, updated, user.timezone)
    await report_google(update, context, updated, "Updated in Google Calendar")


def names_event(update: Update, request: str) -> bool:
    """Whether `request` starts with the name of one of the user's events ("padel to 20:00")."""
    user = users.get_or_create(update.effective_user.id)
    return split_move(request, titles_of(user)) is not None


# --- messages without a trigger phrase --------------------------------------

async def handle_untriggered(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """"padel is at 20:00 now" moves an event; "padel on thursday at 21:00" asks event or reminder.

    False if it's neither (the bot says it didn't get it).
    """
    user = users.get_or_create(update.effective_user.id)
    titles = titles_of(user)
    statement = split_move_statement(text, titles)
    if statement is not None:
        title, phrase = statement
        await move(update, context, user, titles[title], phrase, text)
        return True
    try:
        parsed = parse_reminder(text, user_now(user.timezone or "UTC"))
    except ParseError:
        return False
    context.user_data[PENDING_PICK] = text
    await update.effective_message.reply_text(
        f"“{parsed.text}”, {format_when(parsed.when, user.timezone or 'UTC', utcnow())}\n"
        "Is this an event or a reminder?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Event", callback_data=Callback.PICK_EVENT),
            InlineKeyboardButton("⏰ Reminder", callback_data=Callback.PICK_REMINDER),
        ]]),
    )
    return True


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📅 Event / ⏰ Reminder, for a message that could be either."""
    query = update.callback_query
    text = context.user_data.pop(PENDING_PICK, None)
    if text is None:
        await query.answer("That question has expired. Send it again.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None)
        return
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    if query.data == Callback.PICK_EVENT:
        await create_event(update, context, text)
    else:
        context.user_data.pop(PENDING_CONTACT_ID, None)
        await rh.create_reminder(update, context, text)


# --- reminders relative to an event -----------------------------------------

async def remind_relative(update: Update, context: ContextTypes.DEFAULT_TYPE, user, request: str,
                          contact_id: int = None) -> bool:
    """"30 min before padel to pack the racket" (after "remind me"): a reminder that follows the event.

    False if the request isn't relative to an event, so it's an ordinary reminder.
    Called by handlers/reminders.create_reminder.
    """
    relative = split_relative(request)
    if relative is None:
        return False
    if abs(relative.minutes) > MAX_OFFSET:
        context.user_data.pop(AWAITING, None)
        await update.effective_message.reply_text("That's too far from the event: at most 5 years before or after it.")
        return True
    titles = titles_of(user)
    found = match_title(relative.event, titles)
    reply = update.effective_message.reply_text
    if found is None or (relative.text and found[1]):
        try:
            # "to take pills 30 min after breakfast every day" is an ordinary reminder.
            parse_reminder(request, user_now(user.timezone))
            return False
        except ParseError:
            pass
        name = unknown_title(relative.event)
        context.user_data.pop(AWAITING, None)
        await reply(f"I don't have an event called “{name}”. Add it first.",
                    reply_markup=_events_button())
        return True
    title, rest = found
    text = clean_text(relative.text if relative.text else rest) or title
    await add_reminder(update, context, user, titles[title], relative.minutes, text, request,
                       message_source(update), contact_id)
    return True


async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, user, event, minutes: int, text: str,
                       request: Optional[str], source: MessageSource, contact_id: int = None):
    """A reminder `minutes` from the event's start; for a repeating event, asks “just the next one, or every time?”."""
    if not event.recurrence:
        await save_reminder(update, context, user, event, minutes, text, request, source, contact_id, every=False)
        return
    context.user_data.pop(AWAITING, None)
    context.user_data[PENDING_EVENT_REMINDER] = {
        "event_id": event.id, "minutes": minutes, "text": text, "request": request, "source": source,
        "contact_id": contact_id,
    }
    await update.effective_message.reply_text(
        f"⏰ {text}, {recurrences.format_offset(minutes)} {event.title}: just the next one, or every time?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("1️⃣ Just the next one", callback_data=event_callback(EventAction.ONCE, event.id)),
            InlineKeyboardButton("🔁 Every time", callback_data=event_callback(EventAction.EVERY, event.id)),
        ]]),
    )


async def save_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, user, event, minutes: int, text: str,
                        request: Optional[str], source: MessageSource, contact_id: int = None, every: bool = False):
    target, for_whom = None, ""
    if contact_id is not None:
        contact = await rh.usable_contact(update, context, user, contact_id)
        if contact is None:
            return
        target, for_whom = users.get_by_id(contact.contact_user_id), f" for {contact.name}"
    context.user_data.pop(AWAITING, None)
    context.user_data.pop(PENDING_CONTACT_ID, None)
    current = events.get(event.id)
    if current is None or current.status != EventStatus.ACTIVE:
        # Cancelled meanwhile: nothing would cancel this reminder any more.
        await update.effective_message.reply_text(f"“{event.title}” has been cancelled.")
        return
    now = utcnow()
    when, rule = reminder_time(event, minutes, now, every)
    if when is None:
        await update.effective_message.reply_text(f"{event.title} doesn't happen again.")
        return
    if when <= now:
        await update.effective_message.reply_text(
            f"That's already passed: {event.title} is {at_text(event, event.starts_at, user.timezone, now)}."
        )
        return
    reminder = reminders.create(
        user, target.telegram_id if target else update.effective_chat.id, text, when,
        rule.serialize() if rule else None, request, source, target=target, event_id=event.id, event_offset=minutes,
    )
    context.user_data[LAST_REMINDER_ID] = reminder.id
    context.user_data.pop(LAST_EVENT_ID, None)
    report.step(update, f"Added a reminder {recurrences.format_offset(minutes)} {event.title}")
    sent = await update.effective_message.reply_text(
        f"⏰ Got it{for_whom}: {reminder.text}\n📅 {recurrences.format_offset(minutes)} {event.title}\n"
        f"{rh.schedule_text(reminder, user.timezone)}",
        reply_markup=rh.build_created_keyboard(reminder.id),
    )
    rh.report_card(update, sent, reminder, user.timezone, for_whom.removeprefix(" for ") or None)


# --- listing ----------------------------------------------------------------

def _events_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📅 Events", callback_data=Callback.EVENTS_MENU)]])


def events_text(user, items, title: str = "Your events", empty: str = None) -> str:
    """The numbered list of (next time, event)."""
    if not items:
        return empty or (
            "You have no upcoming events."
        )
    tz_name = user.timezone or "UTC"
    lines = [f"📅 {title}:", ""]
    for n, (when, event) in enumerate(items, 1):
        lines.append(f"{n}. {event.title}")
        lines += ["    " + line for line in when_text(event, tz_name).split("\n")]
    return "\n".join(lines)


def build_list_keyboard(items):
    rows = [[InlineKeyboardButton(f"📅 {rh.shorten(e.title, 28)}", callback_data=event_callback(EventAction.OPEN, e.id))]
            for _, e in items]
    rows.append([
        InlineKeyboardButton("➕ New", callback_data=Callback.NEW_EVENT),
        InlineKeyboardButton("↩️ Back", callback_data=Callback.MAIN_MENU),
    ])
    return InlineKeyboardMarkup(rows)


async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = "", toast: str = None):
    """Intent action for "my events" (and "my events on friday"), and the 📅 Events menu button."""
    user = users.get_or_create(update.effective_user.id)
    day = parse_day(request, user_now(user.timezone or "UTC")) if request.strip() else None
    items = upcoming_events(user)
    if day is not None:
        tz = ZoneInfo(user.timezone or "UTC")
        items = [(w, e) for w, e in items if occurs_on(e, day, tz)]
        text = events_text(user, items, f"Your events on {day:%a %d %b}", f"No events on {day:%a %d %b}.")
    else:
        text = events_text(user, items)
    # Imported here: handlers.calendar imports this module.
    from handlers.calendar import warning
    text = warning(user) + text
    keyboard = build_list_keyboard(items)
    listed(context, ItemKind.EVENT, [e.id for _, e in items])
    if update.callback_query is not None:
        await update.callback_query.answer(toast)
        await render_menu(update, context, text, keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


def day_text(user, day) -> str:
    """The events on `day`, for “what do I have tomorrow?”; "" if none."""
    tz_name = user.timezone or "UTC"
    tz = ZoneInfo(tz_name)
    lines = []
    for event in events.list_active(user.id):
        if not occurs_on(event, day, tz):
            continue
        if event.all_day:
            lines.append((0, f"• all day: {event.title}"))
            continue
        local = occurrence_on(event, day, tz).astimezone(tz)
        lines.append((local.hour * 60 + local.minute + 1, f"• {local:%H:%M} {event.title}"))
    if not lines:
        return ""
    return "\n".join([f"📅 Events on {day:%a %d %b}:"] + [line for _, line in sorted(lines)])


async def agenda(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "what do I have tomorrow?": that day's events and reminders; without a day, today."""
    user = users.get_or_create(update.effective_user.id)
    now = user_now(user.timezone or "UTC")
    day = parse_day(request, now) if request.strip().strip("?!. ") else now.date()
    if day is None:
        await update.effective_message.reply_text(
            "I couldn't understand the day."
        )
        return
    await rh.show_day(update, context, user, day, day_text(user, day))


def event_screen(user, event):
    """An event's screen in 📅 Events: when, its reminders, and what can be done."""
    tz_name = user.timezone or "UTC"
    now = utcnow()
    lines = [f"📅 {event.title}", when_text(event, tz_name, now)]
    if event.external_id is not None:
        lines.append("🔗 In Google Calendar")
    attached = reminders.list_for_event(event.id)
    if attached:
        lines += ["", "Reminders:"]
        for r in attached:
            whom = ""
            if r.target_user_id != user.id and (target := users.get_by_id(r.target_user_id)) is not None:
                whom = f" (for {rh.contact_name(user.id, target)})"
            every = ", every time" if r.recurrence else ""
            lines.append(f"• {recurrences.format_offset(r.event_offset or 0)}{every}: {r.text}{whom}")
    rows = [_quick_buttons(event), [
        InlineKeyboardButton("✏️ Edit", callback_data=event_callback(EventAction.EDIT, event.id)),
    ]]
    upcoming = next_occurrence(event, now)
    if event.recurrence and upcoming is not None:
        rows[1].append(InlineKeyboardButton(
            f"⏭ Skip {to_local(upcoming, event.timezone):%a %d %b}",
            callback_data=event_callback(EventAction.SKIP, event.id, recurrences.format_stamp(upcoming)),
        ))
    rows.append([InlineKeyboardButton("🗑 Cancel event", callback_data=event_callback(EventAction.CANCEL, event.id))])
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=Callback.EVENTS_MENU)])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# --- cancelling -------------------------------------------------------------

def _reminders_note(count: int) -> str:
    if not count:
        return ""
    return " and its reminder" if count == 1 else f" and its {count} reminders"


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = "", events_only: bool = False):
    """Intent action for "cancel padel" (an event if one is called that, else a reminder) and "cancel event padel"."""
    user = users.get_or_create(update.effective_user.id)
    reply = update.effective_message.reply_text
    titles = titles_of(user) if "reminder" not in request.lower() else {}
    found = match_title(request.split(), titles) if request.strip() else None
    day = None
    if found is not None and found[1]:
        # "cancel padel on thursday": one day of it
        day = parse_day(" ".join(found[1]), user_now(user.timezone or "UTC"))
        if day is None:
            found = None
    if found is None:
        if events_only:
            items = upcoming_events(user)
            await reply(events_text(user, items, "No event matches that. Yours", "No event matches that."),
                        reply_markup=build_list_keyboard(items))
            return
        await rh.cancel_reminder(update, context, request)
        return

    event = titles[found[0]]
    tz_name = user.timezone or "UTC"
    if day is not None:
        if not occurs_on(event, day, ZoneInfo(tz_name)):
            await reply(f"There's no {event.title} on {day:%a %d %b}.\n{when_text(event, tz_name)}")
            return
        if event.recurrence:
            occurrence = occurrence_on(event, day, ZoneInfo(tz_name))
            await reply(
                f"Skip {event.title} on {day:%a %d %b}?",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "⏭ Skip it",
                    callback_data=event_callback(EventAction.SKIP, event.id, recurrences.format_stamp(occurrence)),
                )]]),
            )
            return
    await confirm_cancel(update, user, event)


async def confirm_cancel(update: Update, user, event):
    """ "Cancel “padel”?" with ⏭ Just <the next one> (if it repeats) and 🗑: an event is never cancelled unasked."""
    tz_name = user.timezone or "UTC"
    count = len(reminders.list_for_event(event.id))
    buttons = []
    upcoming = next_occurrence(event, utcnow())
    if event.recurrence and upcoming is not None:
        buttons.append(InlineKeyboardButton(
            f"⏭ Just {to_local(upcoming, event.timezone):%a %d %b}",
            callback_data=event_callback(EventAction.SKIP, event.id, recurrences.format_stamp(upcoming)),
        ))
    buttons.append(InlineKeyboardButton(
        "🗑 Every time" if event.recurrence else "🗑 Cancel it",
        callback_data=event_callback(EventAction.CANCEL, event.id),
    ))
    note = f"\nIts {'reminder is' if count == 1 else f'{count} reminders are'} cancelled with it." if count else ""
    await update.effective_message.reply_text(f"Cancel “{event.title}”?\n{when_text(event, tz_name)}{note}",
                                              reply_markup=InlineKeyboardMarkup([buttons]))


async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "cancel event padel": only events."""
    await cancel(update, context, request, events_only=True)


async def retire_all(context: ContextTypes.DEFAULT_TYPE, cancelled):
    for reminder in cancelled.reminders:
        await rh.retire_fired_message(context, reminder, "↩️ Cancelled.")


async def to_google(context: ContextTypes.DEFAULT_TYPE, event) -> bool:
    """Send the change to Google Calendar, if the event's owner linked it (handlers/calendar.py); True if it got there."""
    # Imported here: handlers.calendar imports this module.
    from handlers.calendar import push
    return await push(context.bot, event)


async def cancel_with_reminders(context: ContextTypes.DEFAULT_TYPE, event, push_to_google: bool = True):
    """Cancel an event and its waiting reminders (taking the buttons off one going off). None if it already was.

    One imported from Google Calendar is then deleted (not kept as cancelled),
    once Google knows (handlers/calendar.py deletes it when a pending one gets there).
    """
    cancelled = events.cancel(event.id)
    if cancelled is None:
        return None
    await retire_all(context, cancelled)
    if push_to_google:
        await to_google(context, cancelled.event)
    current = events.get(event.id)
    if current is not None and current.source == MessageSource.GOOGLE and not current.pending_push:
        events.delete(event.id)
    return cancelled


# --- 👎 Wrong -----------------------------------------------------------------

async def flag_wrong(update: Update, context: ContextTypes.DEFAULT_TYPE, event) -> str:
    """Save an event the bot got wrong as a failed message and cancel it (and its reminders)."""
    if failed.open_for_event(event.id) is None:
        record(
            update, FailureReason.WRONG_RESULT, event.request or event.title,
            source=event.source or MessageSource.TYPED, intent=IntentName.EVENT_CREATE,
            bot_understood=understood(event), event_id=event.id,
        )
    # "that's wrong" again now means this one, which is already saved.
    context.user_data.pop(LAST_EVENT_ID, None)
    context.user_data[LAST_REMINDER_ID] = None
    cancelled = await cancel_with_reminders(context, event)
    if cancelled is None:
        return f"👎 Saved as failed, so I can learn it. “{event.title}” had already been cancelled."
    return (
        f"👎 Cancelled: {event.title}{_reminders_note(len(cancelled.reminders))}\n"
        "Saved as failed, so I can learn it. Send it again if you still need it."
    )


async def flag_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """"that's wrong" right after making an event: flag it. False if the last thing made wasn't one."""
    event_id = context.user_data.get(LAST_EVENT_ID)
    if event_id is None:
        return False
    event = events.get(event_id)
    if event is None or event.user_id != users.get_or_create(update.effective_user.id).id:
        return False
    await update.effective_message.reply_text(await flag_wrong(update, context, event))
    return True


# --- buttons ----------------------------------------------------------------

async def on_events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📅 Events in the main menu, and ↩️ Back to it."""
    # Imported here: handlers.calendar imports this module.
    from handlers.calendar import maybe_sync
    await maybe_sync(context.bot, update.effective_user.id)
    await list_events(update, context)


async def on_event_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, event_id, *args = query.data.removeprefix(CallbackPrefix.EVENT).split(":")
    action, event_id = EventAction(action), int(event_id)
    user = users.get_or_create(update.effective_user.id)
    event = events.get(event_id)
    if event is None or event.user_id != user.id:
        await query.answer("This event isn't yours.", show_alert=True)
        return
    if event.status != EventStatus.ACTIVE and action not in (EventAction.UNDO, EventAction.WRONG, EventAction.CANCEL):
        # Buttons on an old message: ⏰ would make a reminder nothing ever cancels.
        context.user_data.pop(PENDING_EVENT_REMINDER, None)
        await query.answer("This event has been cancelled.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if action == EventAction.OPEN:
        await query.answer()
        text, keyboard = event_screen(user, event)
        await render_menu(update, context, text, keyboard)

    elif action == EventAction.UNDO:
        cancelled = await cancel_with_reminders(context, event)
        if cancelled is None:
            await query.answer("This event has already been cancelled.")
            return
        await query.answer("Cancelled")
        await query.edit_message_text(f"↩️ Cancelled: {event.title}{_reminders_note(len(cancelled.reminders))}")

    elif action == EventAction.EDIT:
        await query.answer()
        await start_edit(context, event, update.effective_message.reply_text)

    elif action == EventAction.WRONG:
        await query.answer("Cancelled and saved as failed")
        await query.edit_message_text(await flag_wrong(update, context, event))

    elif action == EventAction.CANCEL:
        await cancel_with_reminders(context, event)
        await list_events(update, context, toast="Cancelled")

    elif action == EventAction.SKIP:
        await skip(update, context, user, event, recurrences.parse_stamp(args[0]))

    elif action == EventAction.REMIND:
        minutes = min(max(int(args[0]), -MAX_OFFSET), MAX_OFFSET)
        await query.answer()
        await add_reminder(update, context, user, event, minutes, event.title, None, MessageSource.TYPED)

    elif action in (EventAction.ONCE, EventAction.EVERY):
        pending = context.user_data.get(PENDING_EVENT_REMINDER)
        if pending is None or pending["event_id"] != event.id:
            await query.answer("That question has expired. Send it again.", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=None)
            return
        context.user_data.pop(PENDING_EVENT_REMINDER, None)
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await save_reminder(update, context, user, event, pending["minutes"], pending["text"], pending["request"],
                            pending["source"], pending["contact_id"], every=action == EventAction.EVERY)


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE, user, event, occurrence: datetime):
    """⏭ Skip: one occurrence of a repeating event doesn't happen; its reminders for it are skipped too."""
    query = update.callback_query
    now = utcnow()
    # Still on until it ends (an all-day one, its day)
    ends = occurrence + duration(event)
    if not event.recurrence or ends <= now or nearest_occurrence(event, occurrence) != occurrence:
        await query.answer("That one has already passed.", show_alert=True)
        return
    updated = events.update(event.id, skipped=with_skipped(event, occurrence, now))
    if updated is None:
        await query.answer("This event has been cancelled.", show_alert=True)
        return
    await follow(context, event, updated)
    await to_google(context, updated)
    await query.answer(f"No {event.title} on {to_local(occurrence, event.timezone):%a %d %b}")
    text, keyboard = event_screen(user, updated)
    await render_menu(update, context, text, keyboard)

