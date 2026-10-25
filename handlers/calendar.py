"""📅 Google Calendar: linking, picking calendars, and syncing events both ways.

- Linking: ⚙️ Settings → 📅 Calendar (or /calendar) shows a 🔗 button to
  Google's consent page; Google sends the user back to the bot's web server
  (handlers/web.py), which calls `complete_link`.
- Bot → Google: handlers/events.py calls `push` after every change; if
  Google can't be reached the event is `pending_push` and sent on the next sync.
- Google → bot: push notifications (`on_push`), a sync when the user asks
  about reminders or events (`maybe_sync`, at most every 5 minutes), and one
  a day (jobs/calendar.py). Each is incremental (Google's sync token).
- Last change wins: an event changed in the bot and not yet in Google stays
  as it is if its change is newer than Google's.
- An expired or revoked login (`GoogleAuthError`) stops syncing, warns the
  user once with a button to link again, and leaves their events as they are.
"""

import asyncio
import contextvars
import logging
import secrets as random_secrets
import uuid

from    datetime                        import datetime, timedelta, timezone
from    types                           import SimpleNamespace
from    typing                          import Optional
from    zoneinfo                        import ZoneInfo

from    telegram                        import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.error                  import TelegramError
from    telegram.ext                    import ContextTypes

import  config

from    core                            import secrets
from    core.recurrence                 import format_stamp
from    core.events                     import format_moved, moved, next_occurrence, skipped, with_skipped
from    core.gcal                       import from_google, stored_rule, to_google
from    db.models.reminder              import utcnow
from    db.repositories.event           import EventRepository
from    db.repositories.google          import GoogleRepository
from    db.repositories.user            import UserRepository
from    enums                           import (
    Callback, CalendarAction, CallbackPrefix, EventStatus, ExternalSource, GoogleStatus, MessageSource,
)
from    handlers.ui                     import render_menu
from    services                        import google_calendar as google
from    services.google_calendar        import GoogleAuthError, GoogleUnavailable, NotFound, SyncExpired


logger = logging.getLogger(__name__)

users = UserRepository()
events = EventRepository()
accounts = GoogleRepository()

# Syncing when the user asks something: at most this often, per user
POLL_EVERY = timedelta(minutes=5)
# …and the reply waits at most this long for it (the sync goes on after)
POLL_WAIT = 8
# A push channel is renewed this long before it expires
RENEW_BEFORE = timedelta(days=2)
# On the first sync, one-offs that ended longer ago than this aren't imported
IMPORT_PAST = timedelta(days=1)

NOT_SET_UP = "📅 Google Calendar isn't set up on this bot."
PRIVACY = ("Linking lets the bot read and change the events in the calendars you pick. "
           "Unlike the rest of the bot, your events then go to Google.")


# Syncs running in the background: kept here so they aren't garbage collected mid-way
_running = set()


def spawn(coroutine) -> asyncio.Task:
    """Run a sync in the background; a failure is logged."""
    task = asyncio.get_running_loop().create_task(coroutine)
    _running.add(task)

    def done(finished):
        _running.discard(finished)
        if not finished.cancelled() and finished.exception() is not None:
            logger.error("Google Calendar sync failed", exc_info=finished.exception())
    task.add_done_callback(done)
    return task


# One sync (or send) at a time per user, so two of them can't both import the same Google event.
# Per event loop too: a lock belongs to the loop it was first used in (the tests run several).
_locks = {}
# Set while a sync runs: what it does inside sends without taking the lock again (it isn't reentrant)
_syncing = contextvars.ContextVar("syncing", default=False)


def _lock(user_id) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), user_id)
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


# Google events that failed to apply, per (calendar, event): after MAX_TRIES the sync goes past them
_failures = {}
MAX_TRIES = 3


def _bot_context(bot):
    """What handlers/events.follow needs from a context (`.bot`), for a sync outside a Telegram update."""
    return SimpleNamespace(bot=bot)


def link_button(telegram_id: int, text: str = "🔗 Link Google Calendar") -> InlineKeyboardButton:
    return InlineKeyboardButton(text, url=google.auth_url(secrets.sign_state(telegram_id, config.CALENDAR_KEY)))


def _client(account) -> Optional[google.Calendar]:
    token = secrets.decrypt(account.refresh_token, config.CALENDAR_KEY)
    return google.Calendar(token) if token is not None else None


# --- the login ---------------------------------------------------------------

async def expire(bot, user_id) -> None:
    """Google refused the login: stop syncing and warn the user, once, with a button to link again."""
    account = accounts.account(user_id)
    if account is None or account.status == GoogleStatus.EXPIRED:
        return
    accounts.update_account(user_id, status=GoogleStatus.EXPIRED)
    user = users.get_by_id(user_id)
    if user is None:
        return
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text="⚠️ Google Calendar disconnected: your Google login expired or was removed. Your events and "
                 "reminders stay as they are, but don't sync until you link it again.",
            reply_markup=InlineKeyboardMarkup([[link_button(user.telegram_id, "🔗 Link again")]]),
        )
    except TelegramError:
        logger.info("Couldn't warn user %s about Google Calendar", user.telegram_id)


def warning(user) -> str:
    """A line for the top of 📅 Events if the user's Google Calendar doesn't sync; "" otherwise."""
    if not google.is_configured():
        return ""
    account = accounts.account(user.id)
    if account is None or account.status != GoogleStatus.EXPIRED:
        return ""
    return "⚠️ Google Calendar isn't syncing: link it again in ⚙️ Settings → 📅 Calendar.\n\n"


async def complete_link(bot, state: str, code: str) -> str:
    """Google sent the user back with `code`: link their account. Returns what the web page says."""
    telegram_id = secrets.verify_state(state, config.CALENDAR_KEY)
    if telegram_id is None:
        return "That link has expired. Open 📅 Calendar in the bot and try again."
    user = users.get_by_telegram_id(telegram_id)
    if user is None:
        return "Start the bot in Telegram first."
    try:
        tokens = await google.exchange_code(code)
    except (GoogleAuthError, GoogleUnavailable) as e:
        logger.warning("Linking Google Calendar for %s failed: %s", telegram_id, e)
        return "Google didn't accept that. Open 📅 Calendar in the bot and try again."
    if not tokens.get("refresh_token"):
        return "Google didn't give the bot a lasting login. Open 📅 Calendar in the bot and try again."
    granted = set(tokens.get("scope", "").split())
    if granted and not set(google.SCOPES) <= granted:
        return "The bot needs both permissions to sync. Open 📅 Calendar in the bot and try again, ticking both."

    before = accounts.account(user.id)
    accounts.link(user.id, secrets.encrypt(tokens["refresh_token"], config.CALENDAR_KEY))
    client = google.Calendar(tokens["refresh_token"])
    try:
        try:
            calendars = await refresh_calendars(client, user)
        except GoogleUnavailable as e:
            logger.warning("Couldn't list the calendars of %s: %s", telegram_id, e)
            calendars = accounts.calendars(user.id)
        account = accounts.account(user.id)
        if account.default_calendar_id is None:
            writable = [c for c in calendars if c.writable]
            primary = next((c for c in writable if c.primary), writable[0] if writable else None)
            if primary is not None:
                accounts.update_account(user.id, default_calendar_id=primary.calendar_id)
        for calendar in calendars:
            if calendar.selected:
                await _watch(client, calendar)
    except GoogleAuthError as e:
        # Google took the login but refuses it (a permission left unticked): undo the link
        logger.warning("Google refused the new login of %s: %s", telegram_id, e)
        await google.revoke(tokens["refresh_token"])
        if before is None:
            accounts.unlink(user.id)
        else:
            # Linked before: back as it was, waiting to be linked again
            accounts.update_account(user.id, refresh_token=before.refresh_token, status=GoogleStatus.EXPIRED)
        return "The bot needs both permissions. Open 📅 Calendar in the bot and try again, ticking both."

    text, keyboard = screen(user)
    try:
        await bot.send_message(chat_id=telegram_id, text=f"✅ Google Calendar linked.\n\n{text}", reply_markup=keyboard)
    except TelegramError:
        pass
    # Events made in the bot so far go to Google, then Google's come in
    spawn(_first_sync(bot, user))
    return "✅ Google Calendar is linked. You can go back to Telegram."


async def refresh_calendars(client, user) -> list:
    """Google's list of the user's calendars, saved; the ones gone from Google stop syncing."""
    for gone in accounts.save_calendars(user.id, await client.calendars()):
        events.detach(user.id, gone.calendar_id)
    return accounts.calendars(user.id)


async def _first_sync(bot, user) -> None:
    try:
        account = accounts.account(user.id)
        now = utcnow()
        for event in events.list_unsynced(user.id):
            if account.default_calendar_id and next_occurrence(event, now) is not None:
                await push(bot, event)
        await sync_user(bot, user)
    except Exception:
        logger.exception("First sync of %s failed", user.telegram_id)


# --- bot → Google --------------------------------------------------------------

async def push(bot, event) -> None:
    """Send an event's change (or cancellation) to Google, if its owner synced; later if Google is unreachable."""
    if not google.is_configured():
        return
    account = accounts.account(event.user_id)
    if account is None:
        return
    event = events.get(event.id) or event
    if event.external_id is not None and event.external_source is None:
        # Kept from a calendar that no longer syncs (📌 Keep them)
        return
    if account.status != GoogleStatus.LINKED:
        # Sent once the user links again
        if event.external_id is not None:
            events.set_sync(event.id, pending_push=True)
        return
    calendar_id = event.external_calendar_id or account.default_calendar_id
    if calendar_id is None or (event.external_id is None and event.status != EventStatus.ACTIVE):
        # Nothing to send (cancelled before it ever reached Google): nothing waits either
        if event.pending_push:
            events.set_sync(event.id, pending_push=False)
        return
    client = _client(account)
    if client is None:
        await expire(bot, event.user_id)
        return
    events.set_sync(event.id, pending_push=True)
    try:
        if _syncing.get():
            await _send(client, events.get(event.id) or event, calendar_id)
        else:
            async with _lock(event.user_id):
                await _send(client, events.get(event.id) or event, calendar_id)
    except GoogleUnavailable as e:
        logger.info("Event %s not sent to Google yet: %s", event.id, e)
    except GoogleAuthError:
        await expire(bot, event.user_id)


def _google_time(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


async def _send(client, event, calendar_id: str) -> None:
    if event.status != EventStatus.ACTIVE and event.external_id is None:
        # Cancelled before it reached Google: nothing to delete there
        events.set_sync(event.id, pending_push=False)
        return
    if event.status != EventStatus.ACTIVE:
        await client.delete(calendar_id, event.external_id)
        if event.source == MessageSource.GOOGLE:
            # It came from Google and is gone there too: nothing kept
            events.delete(event.id)
        else:
            events.set_sync(event.id, pending_push=False)
        return
    body = to_google(event)
    sent = None
    if event.external_id is not None:
        try:
            sent = await client.patch(calendar_id, event.external_id, body)
        except NotFound:
            # Deleted in Google meanwhile; the bot's change is newer
            sent = None
    if sent is None:
        sent = await client.insert(calendar_id, body)
    events.set_sync(
        event.id, external_source=ExternalSource.GOOGLE, external_calendar_id=calendar_id, external_id=sent["id"],
        etag=sent.get("etag"), external_updated_at=_google_time(sent.get("updated")), pending_push=False,
    )


# --- Google → bot --------------------------------------------------------------

async def maybe_sync(bot, telegram_id: int) -> None:
    """The user asked something about reminders or events: sync first, unless the last sync was under 5 minutes ago."""
    if not google.is_configured():
        return
    user = users.get_by_telegram_id(telegram_id)
    if user is None or not accounts.claim_poll(user.id, utcnow() - POLL_EVERY):
        return
    task = spawn(sync_user(bot, user))
    # Answer within a few seconds even if Google is slow; the sync finishes anyway
    await asyncio.wait({task}, timeout=POLL_WAIT)


async def sync_user(bot, user, only=None) -> None:
    """Send what's waiting, then bring in what changed in the user's synced calendars (or just `only`).

    One at a time per user: another sync (a burst of push notifications, a
    question, 🔄) waits, then finds the changes already applied.
    """
    if _syncing.get():
        await _sync_user(bot, user, only)
        return
    async with _lock(user.id):
        token = _syncing.set(True)
        try:
            await _sync_user(bot, user, only)
        finally:
            _syncing.reset(token)


async def _sync_user(bot, user, only=None) -> None:
    account = accounts.account(user.id)
    if account is None or account.status != GoogleStatus.LINKED:
        return
    client = _client(account)
    if client is None:
        await expire(bot, user.id)
        return
    accounts.update_account(user.id, last_poll_at=utcnow())
    try:
        for event in events.list_pending(user.id):
            calendar_id = event.external_calendar_id or account.default_calendar_id
            if calendar_id is None:
                continue
            try:
                await _send(client, event, calendar_id)
            except (GoogleUnavailable, GoogleAuthError):
                raise
            except Exception:
                # One event Google won't take mustn't stop the user's whole sync; it's tried again next time
                logger.exception("Couldn't send event %s to Google", event.id)
        for calendar in accounts.calendars(user.id):
            if calendar.selected and (only is None or calendar.id == only):
                await sync_calendar(bot, client, user, calendar)
    except GoogleUnavailable as e:
        logger.info("Google Calendar sync of %s stopped: %s", user.telegram_id, e)
    except GoogleAuthError:
        await expire(bot, user.id)


async def sync_calendar(bot, client, user, calendar) -> None:
    """Everything that changed in one calendar since its sync token (everything, the first time)."""
    token, page, items = calendar.sync_token, None, []
    while True:
        try:
            body = await client.events(calendar.calendar_id, token, page)
        except SyncExpired:
            if token is None:
                raise
            # Too old: everything again
            token, page, items = None, None, []
            continue
        items += body.get("items", [])
        page = body.get("nextPageToken")
        if page:
            continue
        first = calendar.sync_token is None
        failed = 0
        # Repeating events before their exceptions (moved or cancelled occurrences)
        for item in sorted(items, key=lambda i: "recurringEventId" in i):
            key = (calendar.id, item.get("id"))
            try:
                await apply(bot, user, calendar, from_google(item, calendar.time_zone), first)
                _failures.pop(key, None)
            except Exception:
                _failures[key] = _failures.get(key, 0) + 1
                logger.exception("Couldn't apply Google event %s for %s", item.get("id"), user.telegram_id)
                if _failures[key] >= MAX_TRIES:
                    # Always fails (odd data): go past it rather than re-reading the calendar forever
                    logger.error("Giving up on Google event %s for %s after %s tries", item.get("id"),
                                 user.telegram_id, MAX_TRIES)
                    _failures.pop(key, None)
                else:
                    failed += 1
        if failed:
            # Keep the old token: the next sync gets these changes again (the ones
            # applied are skipped then, by their etag), so none is lost
            logger.warning("%s Google event(s) for %s not applied; retried on the next sync",
                           failed, user.telegram_id)
            return
        accounts.update_calendar(calendar.id, sync_token=body.get("nextSyncToken"))
        return


async def apply(bot, user, calendar, g, first: bool = False) -> None:
    """One event from Google: create, change or cancel the bot's copy (and move or cancel its reminders)."""
    # Imported here: handlers.events imports this module.
    from handlers.events import cancel_with_reminders, follow

    context = _bot_context(bot)
    if g.recurring_event_id is not None:
        await _apply_exception(context, user, calendar, g, follow)
        return

    existing = events.find_external(user.id, calendar.calendar_id, g.id)
    if g.cancelled:
        if existing is not None and existing.status == EventStatus.ACTIVE \
                and not (existing.pending_push and _newer(existing, g)):
            # Google has it already: nothing to send back
            await cancel_with_reminders(context, existing, push_to_google=False)
        return
    if existing is not None and existing.etag == g.etag and existing.external_source is not None:
        # Our own change coming back, or nothing new
        return
    if existing is not None and existing.pending_push and _newer(existing, g):
        # Changed in the bot after Google: the bot's version wins and is sent on
        return

    values = dict(
        title=g.title, starts_at=g.starts_at, ends_at=g.ends_at if g.ends_at != g.starts_at else None,
        all_day=g.all_day, timezone=g.timezone, recurrence=stored_rule(g.rule),
        skipped=",".join(sorted(format_stamp(s) for s in g.exdates)) or None,
    )
    # (Also links up one kept when its calendar stopped syncing)
    sync = dict(external_source=ExternalSource.GOOGLE, etag=g.etag, external_updated_at=g.updated, pending_push=False)
    if existing is None or existing.status != EventStatus.ACTIVE:
        if existing is not None:
            # Cancelled in the bot, and Google doesn't know: that's still pending
            return
        if first and g.rule is None and (g.ends_at or g.starts_at) < utcnow() - IMPORT_PAST:
            return
        created = events.create(
            user.id, values.pop("title"), values.pop("starts_at"), values.pop("timezone"), values.pop("recurrence"),
            values.pop("all_day"), source=MessageSource.GOOGLE, external_calendar_id=calendar.calendar_id,
            external_id=g.id, updated_at=g.updated or utcnow(), moved=_rdates_as_moved(g), **values, **sync,
        )
        logger.info("Imported Google event %s as %s", g.id, created.id)
        return
    if g.rdates:
        values["moved"] = _merge_rdates(existing, g)
    updated = events.update(existing.id, updated_at=g.updated or utcnow(), **values, **sync)
    if updated is not None:
        await follow(context, existing, updated)


def _newer(event, g) -> bool:
    """Whether the bot's change to `event` is newer than Google's."""
    return g.updated is None or event.updated_at > g.updated


def _rdates_as_moved(g) -> Optional[str]:
    # An extra date (RDATE) is kept like an occurrence moved onto that date from itself
    return format_moved({d: d for d in g.rdates})


def _merge_rdates(event, g) -> Optional[str]:
    shifted = {o: n for o, n in moved(event).items() if o != n}
    shifted.update({d: d for d in g.rdates})
    return format_moved(shifted)


async def _apply_exception(context, user, calendar, g, follow) -> None:
    """One occurrence of a repeating event cancelled or moved in Google."""
    parent = events.find_external(user.id, calendar.calendar_id, g.recurring_event_id)
    if parent is None or parent.status != EventStatus.ACTIVE or g.original_start is None:
        return
    now = utcnow()
    shifted = moved(parent)
    if g.cancelled:
        shifted.pop(g.original_start, None)
        values = dict(skipped=with_skipped(parent, g.original_start, now) if g.original_start not in skipped(parent)
                      else parent.skipped, moved=format_moved(shifted))
    elif shifted.get(g.original_start) == g.starts_at:
        return
    else:
        shifted[g.original_start] = g.starts_at
        values = dict(moved=format_moved(shifted))
    updated = events.set_sync(parent.id, **values)
    if updated is not None:
        await follow(context, parent, updated)


async def on_push(bot, channel_id: str, token: str, state: str) -> bool:
    """A push notification from Google (handlers/web.py). False if it isn't one of ours."""
    calendar = accounts.by_channel(channel_id or "")
    # As bytes: compare_digest refuses a str that isn't ASCII, and the header is anyone's
    if calendar is None or not calendar.channel_token or not random_secrets.compare_digest(
            (token or "").encode(), calendar.channel_token.encode()):
        return False
    if state == "sync":
        # The first one, when the channel opens
        return True
    user = users.get_by_id(calendar.user_id)
    if user is not None:
        spawn(sync_user(bot, user, only=calendar.id))
    return True


# --- push channels -------------------------------------------------------------

async def _watch(client, calendar) -> None:
    """Ask Google to push changes to this calendar; nothing if the bot has no public HTTPS address."""
    address = google.push_address()
    if address is None:
        return
    channel_id, token = uuid.uuid4().hex, random_secrets.token_hex(16)
    try:
        channel = await client.watch(calendar.calendar_id, channel_id, token, address)
    except (GoogleUnavailable, NotFound) as e:
        logger.info("No push channel for calendar %s: %s", calendar.id, e)
        return
    old = (calendar.channel_id, calendar.channel_resource_id)
    expires = datetime.fromtimestamp(int(channel["expiration"]) / 1000, timezone.utc) if channel.get("expiration") \
        else None
    accounts.update_calendar(calendar.id, channel_id=channel_id, channel_token=token,
                             channel_resource_id=channel.get("resourceId"), channel_expires_at=expires)
    if old[0] and old[1]:
        await _stop(client, *old)


async def _stop(client, channel_id: Optional[str], resource_id: Optional[str]) -> None:
    if not channel_id or not resource_id:
        return
    try:
        await client.stop(channel_id, resource_id)
    except (GoogleUnavailable, GoogleAuthError):
        # It expires on its own
        pass


async def renew_channels(bot) -> None:
    """Open a new push channel for each synced calendar whose channel expires soon (or has none)."""
    soon = utcnow() + RENEW_BEFORE
    for account in accounts.linked():
        client = _client(account)
        if client is None:
            continue
        try:
            for calendar in accounts.calendars(account.user_id):
                if calendar.selected and (calendar.channel_expires_at is None or calendar.channel_expires_at < soon):
                    await _watch(client, calendar)
        except GoogleAuthError:
            await expire(bot, account.user_id)


async def sync_everyone(bot) -> None:
    """The daily sync: every linked user, in case a push got lost."""
    for account in accounts.linked():
        user = users.get_by_id(account.user_id)
        if user is not None:
            try:
                await sync_user(bot, user)
            except Exception:
                logger.exception("Daily Google Calendar sync of %s failed", user.telegram_id)


# --- ⚙️ Settings → 📅 Calendar ---------------------------------------------------

def calendar_callback(action: CalendarAction, value=None) -> str:
    return f"{CallbackPrefix.CALENDAR}{action}" + (f":{value}" if value is not None else "")


def screen(user):
    """The 📅 Calendar screen: link, or what syncs and where new events go."""
    back = [InlineKeyboardButton("↩️ Back", callback_data=Callback.SETTINGS_MENU)]
    if not google.is_configured():
        return NOT_SET_UP, InlineKeyboardMarkup([back])
    account = accounts.account(user.id)
    if account is None:
        return (f"📅 Google Calendar\n\nSync your events both ways: what you add here shows up in Google "
                f"Calendar, and Google's events are here too, for reminders before them.\n\n{PRIVACY}",
                InlineKeyboardMarkup([[link_button(user.telegram_id)], back]))
    if account.status == GoogleStatus.EXPIRED:
        return ("📅 Google Calendar\n\n⚠️ Your Google login expired or was removed, so nothing syncs. Your events "
                "and reminders stay as they are. Link it again to go on syncing.",
                InlineKeyboardMarkup([[link_button(user.telegram_id, "🔗 Link again")],
                                      [InlineKeyboardButton("🔓 Unlink", callback_data=calendar_callback(
                                          CalendarAction.UNLINK))], back]))
    calendars = accounts.calendars(user.id)
    default = next((c for c in calendars if c.calendar_id == account.default_calendar_id), None)
    lines = ["📅 Google Calendar: linked", "", "Tap a calendar to sync it or stop:"]
    rows = [[InlineKeyboardButton(f"{'✅' if c.selected else '⬜'} {c.summary[:40]}",
                                  callback_data=calendar_callback(CalendarAction.TOGGLE, c.id))] for c in calendars]
    if default is not None:
        lines += ["", f"New events from the bot go to: {default.summary}"]
        if sum(c.selected and c.writable for c in calendars) > 1:
            rows.append([InlineKeyboardButton("📥 Put new events in another one",
                                              callback_data=calendar_callback(CalendarAction.DEFAULT))])
    if account.last_poll_at is not None:
        lines.append(f"Last synced: {account.last_poll_at.astimezone(_tz(user)):%a %d %b, %H:%M}")
    rows.append([InlineKeyboardButton("🔄 Sync now", callback_data=calendar_callback(CalendarAction.SYNC)),
                 InlineKeyboardButton("🔓 Unlink", callback_data=calendar_callback(CalendarAction.UNLINK))])
    rows.append(back)
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _tz(user):
    return ZoneInfo(user.timezone or "UTC")


async def on_calendar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/calendar"""
    user = users.get_or_create(update.effective_user.id)
    text, keyboard = screen(user)
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def on_calendar_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Settings → 📅 Calendar"""
    await update.callback_query.answer()
    user = users.get_or_create(update.effective_user.id)
    text, keyboard = screen(user)
    await render_menu(update, context, text, keyboard)


def _ask_keep(what: str, count: int, value) -> tuple:
    return (
        f"{what} {count} of its events are in the bot. Keep them here (no longer synced), or remove them?",
        InlineKeyboardMarkup([[
            InlineKeyboardButton("📌 Keep them", callback_data=calendar_callback(CalendarAction.KEEP, value)),
            InlineKeyboardButton("🗑 Remove them", callback_data=calendar_callback(CalendarAction.REMOVE, value)),
        ]]),
    )


async def on_calendar_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, _, value = query.data.removeprefix(CallbackPrefix.CALENDAR).partition(":")
    action = CalendarAction(action)
    user = users.get_or_create(update.effective_user.id)
    account = accounts.account(user.id) if google.is_configured() else None
    if account is None:
        await query.answer("Google Calendar isn't linked.", show_alert=True)
        text, keyboard = screen(user)
        await render_menu(update, context, text, keyboard)
        return
    client = _client(account)

    if action == CalendarAction.TOGGLE:
        calendar = accounts.calendar(int(value))
        if calendar is None or calendar.user_id != user.id:
            await query.answer("That calendar is gone.", show_alert=True)
        elif not calendar.selected:
            accounts.update_calendar(calendar.id, selected=True, sync_token=None)
            await query.answer(f"Syncing {calendar.summary}")
            if client is not None and account.status == GoogleStatus.LINKED:
                await _watch(client, calendar)
                spawn(sync_user(context.bot, user, only=calendar.id))
        else:
            count = len(events.list_synced(user.id, calendar.calendar_id))
            if count:
                await query.answer()
                text, keyboard = _ask_keep(f"Stop syncing {calendar.summary}?", count, calendar.id)
                await render_menu(update, context, text, keyboard)
                return
            await _stop_calendar(client, user, calendar, keep=True)
            await query.answer(f"Stopped syncing {calendar.summary}")

    elif action == CalendarAction.DEFAULT:
        selected = [c for c in accounts.calendars(user.id) if c.selected and c.writable]
        ids = [c.calendar_id for c in selected]
        if ids:
            following = ids[(ids.index(account.default_calendar_id) + 1) % len(ids)] \
                if account.default_calendar_id in ids else ids[0]
            accounts.update_account(user.id, default_calendar_id=following)
        await query.answer()

    elif action == CalendarAction.SYNC:
        if account.status != GoogleStatus.LINKED:
            await query.answer("Link it again first.", show_alert=True)
            return
        await query.answer("Syncing…")
        await sync_user(context.bot, user)

    elif action == CalendarAction.UNLINK:
        count = sum(len(events.list_synced(user.id, c.calendar_id)) for c in accounts.calendars(user.id))
        if count:
            await query.answer()
            text, keyboard = _ask_keep("Unlink Google Calendar?", count, "all")
            await render_menu(update, context, text, keyboard)
            return
        await _unlink(client, user, keep=True)
        await query.answer("Unlinked")

    elif action in (CalendarAction.KEEP, CalendarAction.REMOVE):
        keep = action == CalendarAction.KEEP
        if value == "all":
            await _unlink(client, user, keep, context)
            await query.answer("Unlinked")
        else:
            calendar = accounts.calendar(int(value))
            if calendar is not None and calendar.user_id == user.id:
                await _stop_calendar(client, user, calendar, keep, context)
            await query.answer("Done")

    text, keyboard = screen(user)
    await render_menu(update, context, text, keyboard)


async def _stop_calendar(client, user, calendar, keep: bool, context=None) -> None:
    """Stop syncing one calendar: keep its events in the bot (unsynced), or cancel them with their reminders."""
    if not keep and context is not None:
        # Imported here: handlers.events imports this module.
        from handlers.events import cancel_with_reminders
        for event in events.list_synced(user.id, calendar.calendar_id):
            events.set_sync(event.id, pending_push=False)
            await cancel_with_reminders(context, events.get(event.id), push_to_google=False)
    events.detach(user.id, calendar.calendar_id)
    if client is not None:
        await _stop(client, calendar.channel_id, calendar.channel_resource_id)
    accounts.update_calendar(calendar.id, selected=False, sync_token=None, channel_id=None, channel_token=None,
                             channel_resource_id=None, channel_expires_at=None)
    account = accounts.account(user.id)
    if account is not None and account.default_calendar_id == calendar.calendar_id:
        others = [c for c in accounts.calendars(user.id) if c.selected and c.writable]
        accounts.update_account(user.id, default_calendar_id=others[0].calendar_id if others else None)


async def _unlink(client, user, keep: bool, context=None) -> None:
    for calendar in accounts.calendars(user.id):
        await _stop_calendar(client, user, calendar, keep, context)
    if client is not None:
        await google.revoke(client.refresh_token)
    accounts.unlink(user.id)
