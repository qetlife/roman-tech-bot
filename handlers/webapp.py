"""The web app (#58): the bot's chat in a page, inside Telegram (a Mini App) and in a browser.

The page (webapp/) talks to this JSON API on the bot's web server
(handlers/web.py). A message from the page goes through the same text path
as Telegram (`handlers/text.handle_text`) and a tap on a button through the
same handlers (`handlers/buttons.py`): they get a `WebUpdate`, whose
replies, edits and alerts are collected (`WebChat`) and sent back as JSON
instead of to Telegram. The conversation state (`user_data`) is the user's
own, the same as in Telegram, so "move it to 10" works across both.
Anything the bot sends to other people (a reminder for Anna) still goes
through Telegram.

    GET  /                the page; /app.js, /style.css
    GET  /api/config      the bot's @username, whether voice works
    POST /api/login       {"init_data"} (Mini App) or {"login": {…}} (Login Widget) → {"token", "name"}
    POST /api/message     {"text"} → {"messages", "edits", "alert"}
    POST /api/voice       the recording → the same, after "🎙 “what was heard”"
    POST /api/button      {"data", "message_id"} → the same
    POST /api/speak       {"text"} → the reply spoken (MP3), by the speech-service
    GET  /api/upcoming    the next 7 days: reminders and events

Every /api call but config and login needs "Authorization: Bearer <token>".
"""

import logging

from    datetime                    import datetime, time, timedelta
from    pathlib                     import Path
from    types                       import SimpleNamespace
from    zoneinfo                    import ZoneInfo

from    aiohttp                     import web
from    telegram                    import InlineKeyboardMarkup
from    telegram.ext                import CallbackContext

import  config

from    core                        import recurrence as recurrences
from    core.commands               import occurs_on as reminder_occurs_on
from    core.events                 import occurrence_on, occurs_on as event_occurs_on
from    core.speakable              import speakable
from    core.timezones              import user_now
from    core.webauth                import check_init_data, check_login, sign_session, verify_session
from    db.repositories.event       import EventRepository
from    db.repositories.reminder    import ReminderRepository
from    db.repositories.user        import UserRepository
from    handlers.buttons            import handler_for
from    handlers.errors             import SORRY
from    handlers.text               import handle_text
from    handlers.voice              import NO_WORDS, NOT_SET_UP, UNAVAILABLE
from    services                    import speech


logger = logging.getLogger(__name__)

users = UserRepository()
reminders = ReminderRepository()
events = EventRepository()

PAGE_DIR = Path(__file__).resolve().parent.parent / "webapp"
STATIC = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}

# The largest recording /api/voice takes (about 2 minutes of browser audio)
MAX_AUDIO_BYTES = 10 * 1024 * 1024
# user_data key: the last id given to a message in the web chat (they count down from -1, so never a Telegram one)
WEB_MESSAGE_ID = "web_message_id"
DAYS = 7


# --- a Telegram update, for the web -----------------------------------------

def _buttons(markup) -> list:
    """[[{"text", "data"} or {"text", "url"}]] of an inline keyboard."""
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [[{"text": b.text, "url": b.url} if b.url else {"text": b.text, "data": b.callback_data} for b in row]
            for row in markup.inline_keyboard]


class WebChat:
    """What the bot says while handling one request from the page."""

    def __init__(self, user_data: dict):
        self.user_data = user_data
        self.messages = []
        self.edits = {}
        self.alert = None

    def new_message(self, text: str, markup=None) -> "WebMessage":
        message_id = self.user_data.get(WEB_MESSAGE_ID, 0) - 1
        self.user_data[WEB_MESSAGE_ID] = message_id
        self.messages.append({"id": message_id, "text": text, "buttons": _buttons(markup)})
        return WebMessage(self, message_id, text)

    def edit(self, message_id: int, text: str = None, markup=None, keep_text: bool = False):
        for message in self.messages:
            if message["id"] == message_id:
                # A message from this same request: change it before it's sent
                if not keep_text:
                    message["text"] = text
                message["buttons"] = _buttons(markup)
                return
        edit = self.edits.setdefault(message_id, {"id": message_id})
        if not keep_text:
            edit["text"] = text
        edit["buttons"] = _buttons(markup)

    def result(self) -> dict:
        return {"messages": self.messages, "edits": list(self.edits.values()), "alert": self.alert}


class WebMessage:
    """A message in the web chat, as handlers use one: its text, reply_text, edits."""

    def __init__(self, chat: WebChat, message_id: int, text: str = None, voice=None):
        self.chat = chat
        self.message_id = message_id
        self.text = text
        # Not None for a recording: the reminders made from it are "voice"
        self.voice = voice
        self.reply_to_message = None

    async def reply_text(self, text: str, reply_markup=None, **kwargs) -> "WebMessage":
        return self.chat.new_message(text, reply_markup)

    async def edit_text(self, text: str, reply_markup=None, **kwargs):
        self.chat.edit(self.message_id, text, reply_markup)

    async def edit_reply_markup(self, reply_markup=None, **kwargs):
        self.chat.edit(self.message_id, markup=reply_markup, keep_text=True)


class WebQuery:
    """A tap on a button in the web chat, as handlers use a CallbackQuery."""

    def __init__(self, chat: WebChat, data: str, message: WebMessage):
        self.chat = chat
        self.data = data
        self.message = message

    async def answer(self, text: str = None, show_alert: bool = False, **kwargs):
        if text:
            self.chat.alert = text

    async def edit_message_text(self, text: str, reply_markup=None, **kwargs):
        self.chat.edit(self.message.message_id, text, reply_markup)

    async def edit_message_reply_markup(self, reply_markup=None, **kwargs):
        self.chat.edit(self.message.message_id, markup=reply_markup, keep_text=True)


class WebUpdate:
    """What handlers read from an Update: who, which chat, the message or the tap."""

    def __init__(self, user, message: WebMessage = None, query: WebQuery = None):
        self.effective_user = SimpleNamespace(id=user.telegram_id, first_name=user.first_name,
                                              username=user.username, is_bot=False)
        # A private chat's id is the user's
        self.effective_chat = SimpleNamespace(id=user.telegram_id, type="private")
        self.callback_query = query
        self.effective_message = query.message if query is not None else message
        self.message = message


class WebContext(CallbackContext):
    """The user's own context (user_data, the bot); chat_data of its own, so Telegram's menu message isn't touched."""

    def __init__(self, application, telegram_id: int):
        super().__init__(application, user_id=telegram_id)
        self._web_chat_data = application.bot_data.setdefault("web_chat_data", {}).setdefault(telegram_id, {})

    @property
    def chat_data(self):
        return self._web_chat_data


async def _run(handler, update: WebUpdate, context: WebContext, *args):
    """Run a handler; an unexpected error is recorded (core/errors.py) and the user told, as in Telegram."""
    try:
        await handler(update, context, *args)
    except Exception:
        logger.exception("Unexpected error in the web app",
                         extra={"error_context": {"user": update.effective_user.id, "update": "web app"}})
        update.effective_message.chat.new_message(SORRY)


# --- the API ----------------------------------------------------------------

def _user(request: web.Request):
    """The user the request's token is for; 401 if there's none or it's forged or old."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    telegram_id = verify_session(token, config.BOT_TOKEN) if token else None
    user = users.get_by_telegram_id(telegram_id) if telegram_id is not None else None
    if user is None:
        raise web.HTTPUnauthorized(text='{"error": "log in"}', content_type="application/json")
    return user


async def _json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text='{"error": "send JSON"}', content_type="application/json")
    return body


def _chat(request: web.Request, user):
    application = request.app["application"]
    context = WebContext(application, user.telegram_id)
    return WebChat(context.user_data), context


async def page(request: web.Request) -> web.StreamResponse:
    response = web.FileResponse(PAGE_DIR / STATIC[request.path])
    # A new version shows up at once
    response.headers["Cache-Control"] = "no-cache"
    return response


async def app_config(request: web.Request) -> web.Response:
    bot = request.app["application"].bot
    return web.json_response({"bot": getattr(bot, "username", None), "voice": speech.is_configured()})


async def login(request: web.Request) -> web.Response:
    body = await _json(request)
    if isinstance(body.get("init_data"), str):
        person = check_init_data(body["init_data"], config.BOT_TOKEN)
    elif isinstance(body.get("login"), dict):
        person = check_login(body["login"], config.BOT_TOKEN)
    else:
        person = None
    if person is None:
        raise web.HTTPUnauthorized(text='{"error": "not a Telegram login"}', content_type="application/json")
    users.get_or_create(person["id"])
    users.remember_profile(person["id"], person.get("first_name"), person.get("username"))
    return web.json_response({"token": sign_session(person["id"], config.BOT_TOKEN),
                              "name": person.get("first_name") or person.get("username")})


async def message(request: web.Request) -> web.Response:
    user = _user(request)
    text = (await _json(request)).get("text")
    if not isinstance(text, str) or not text.strip():
        raise web.HTTPBadRequest(text='{"error": "no text"}', content_type="application/json")
    chat, context = _chat(request, user)
    sent = WebMessage(chat, 0, text.strip()[:4096])
    await _run(handle_text, WebUpdate(user, sent), context, sent.text)
    return web.json_response(chat.result())


async def voice(request: web.Request) -> web.Response:
    user = _user(request)
    # The whole body (a larger one is refused with 413 by the server: client_max_size in handlers/web.py)
    audio = await request.read()
    if not audio:
        raise web.HTTPBadRequest(text='{"error": "no audio"}', content_type="application/json")
    chat, context = _chat(request, user)
    if not speech.is_configured():
        chat.new_message(NOT_SET_UP)
        return web.json_response(chat.result())
    try:
        text = await speech.transcribe(audio)
    except speech.SpeechUnavailable:
        logger.warning("speech-service unavailable", exc_info=True)
        chat.new_message(UNAVAILABLE)
        return web.json_response(chat.result())
    except speech.InvalidAudio:
        logger.warning("speech-service couldn't decode a recording from the web app", exc_info=True)
        chat.new_message(NO_WORDS)
        return web.json_response(chat.result())
    if not text:
        chat.new_message(NO_WORDS)
        return web.json_response(chat.result())
    heard = chat.new_message(f"🎙 “{text}”")
    sent = WebMessage(chat, heard.message_id, text, voice=True)
    await _run(handle_text, WebUpdate(user, sent), context, text)
    return web.json_response({**chat.result(), "heard": text})


async def button(request: web.Request) -> web.Response:
    user = _user(request)
    body = await _json(request)
    data, message_id = body.get("data"), body.get("message_id")
    if not isinstance(data, str) or not isinstance(message_id, int):
        raise web.HTTPBadRequest(text='{"error": "data and message_id"}', content_type="application/json")
    chat, context = _chat(request, user)
    handler = handler_for(data)
    if handler is None:
        chat.alert = "That button doesn't work any more."
        return web.json_response(chat.result())
    query = WebQuery(chat, data, WebMessage(chat, message_id, body.get("text")))
    await _run(handler, WebUpdate(user, query=query), context)
    return web.json_response(chat.result())


async def speak(request: web.Request) -> web.Response:
    _user(request)
    text = (await _json(request)).get("text")
    spoken = speakable(text) if isinstance(text, str) else ""
    if not spoken:
        raise web.HTTPBadRequest(text='{"error": "nothing to say"}', content_type="application/json")
    try:
        audio = await speech.speak(spoken, "mp3")
    except speech.SpeechUnavailable as e:
        logger.warning("Speaking failed: %s", e)
        raise web.HTTPServiceUnavailable(text='{"error": "no voice"}', content_type="application/json")
    return web.Response(body=audio, content_type="audio/mpeg")


async def upcoming(request: web.Request) -> web.Response:
    return web.json_response({"days": days_ahead(_user(request))})


# --- the next days ------------------------------------------------------------

def days_ahead(user, days: int = DAYS, now: datetime = None) -> list:
    """[{"date", "label", "items": [{"kind", "time", "text"}]}] for today and the next days, soonest first."""
    tz_name = user.timezone or "UTC"
    tz = ZoneInfo(tz_name)
    today = (now.astimezone(tz) if now is not None else user_now(tz_name)).date()
    active = reminders.list_active(user.id)
    rule_tzs = users.get_timezones({r.creator_user_id for r in active})
    mine = events.list_active(user.id)
    result = []
    for n in range(days):
        day = today + timedelta(days=n)
        items = []
        for r in active:
            rule_tz = ZoneInfo(rule_tzs.get(r.creator_user_id) or "UTC")
            if reminder_occurs_on(r.remind_at, r.recurrence, day, tz, r.created_at, rule_tz):
                items.append({"kind": "reminder", "time": f"{_reminder_time(r, day, tz, rule_tz):%H:%M}",
                              "text": r.text})
        for e in mine:
            if not event_occurs_on(e, day, tz):
                continue
            when = None if e.all_day else occurrence_on(e, day, tz)
            items.append({"kind": "event", "time": f"{when.astimezone(tz):%H:%M}" if when else None,
                          "text": e.title})
        items.sort(key=lambda i: (i["time"] is not None, i["time"] or ""))
        label = "Today" if n == 0 else "Tomorrow" if n == 1 else f"{day:%a %d %b}"
        result.append({"date": day.isoformat(), "label": label, "items": items})
    return result


def _reminder_time(reminder, day, tz, rule_tz) -> datetime:
    """When a reminder goes off on `day` (its next time, or its repeat's time that day)."""
    if reminder.remind_at.astimezone(tz).date() == day or not reminder.recurrence:
        return reminder.remind_at.astimezone(tz)
    start = datetime.combine(day, time(0, 0), tzinfo=tz) - timedelta(seconds=1)
    following = recurrences.parse(reminder.recurrence).next_after(start, rule_tz)
    return (following or reminder.remind_at).astimezone(tz)


def add_routes(app: web.Application):
    for path in STATIC:
        app.router.add_get(path, page)
    app.router.add_get("/api/config", app_config)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/message", message)
    app.router.add_post("/api/voice", voice)
    app.router.add_post("/api/button", button)
    app.router.add_post("/api/speak", speak)
    app.router.add_get("/api/upcoming", upcoming)
