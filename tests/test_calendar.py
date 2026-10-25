"""📅 Google Calendar: RRULEs, Google's JSON, linking and syncing both ways against a fake Google."""

import asyncio
import json

from datetime   import datetime, time, timedelta, timezone
from types      import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit
from zoneinfo   import ZoneInfo

import httpx
import pytest

from cryptography.fernet import Fernet

from core               import recurrence as recurrences
from core.events        import next_occurrence, occurs_on, rule_of
from core.gcal          import from_google, to_google
from tests.test_handlers import _buttons, _replies


TZ = ZoneInfo("Europe/Lisbon")


def at(day, hour, minute=0, month=10):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


def event(starts_at, recurrence=None, **more):
    values = dict(title="padel", starts_at=starts_at, recurrence=recurrence, timezone="Europe/Lisbon", skipped=None,
                  moved=None, all_day=False, ends_at=None)
    values.update(more)
    return SimpleNamespace(**values)


# --- RRULEs -------------------------------------------------------------------

@pytest.mark.parametrize("old, rule", [
    ("mon,tue,wed,thu,fri,sat,sun@09:00", "FREQ=DAILY"),
    ("mon,thu@21:00", "FREQ=WEEKLY;BYDAY=MO,TH"),
    ("month:15@09:00", "FREQ=MONTHLY;BYMONTHDAY=15"),
    ("month:30@09:00", "FREQ=MONTHLY;BYMONTHDAY=28,29,30;BYSETPOS=-1"),
    ("month:-1fri@19:00", "FREQ=MONTHLY;BYDAY=-1FR"),
    ("every:20160m@2026-10-22T20:00Z", "FREQ=WEEKLY;INTERVAL=2"),
    ("every:4320m@2026-10-22T20:00Z", "FREQ=DAILY;INTERVAL=3"),
])
def test_to_rrule(old, rule):
    assert recurrences.to_rrule(recurrences.parse(old)) == rule


def test_the_30th_in_february_is_its_last_day():
    rule = recurrences.RRuleSet("FREQ=MONTHLY;BYMONTHDAY=28,29,30;BYSETPOS=-1", at(30, 9, month=1), "Europe/Lisbon")
    assert rule.next_after(at(31, 0, month=1), TZ) == datetime(2026, 2, 28, 9, tzinfo=TZ)


@pytest.mark.parametrize("rule, start, text", [
    ("FREQ=WEEKLY;BYDAY=TH", at(22, 21), "every Thu at 21:00"),
    ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", at(22, 8, 30), "weekdays at 08:30"),
    ("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH", at(22, 21), "every 2 weeks on Mon, Thu at 21:00"),
    ("FREQ=MONTHLY;BYDAY=2TU", at(13, 19), "monthly on the 2nd Tue at 19:00"),
    ("FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1", at(31, 9), "monthly on the 31st at 09:00"),
    ("FREQ=YEARLY", at(24, 18, month=12), "every year on 24 Dec at 18:00"),
    ("FREQ=WEEKLY;BYDAY=TH;UNTIL=20261224T225959Z", at(22, 21), "every Thu at 21:00, until 24 Dec 2026"),
    ("FREQ=DAILY;COUNT=10", at(22, 7), "every day at 07:00, 10 times"),
])
def test_describe_rule(rule, start, text):
    assert recurrences.describe_rule(rule, start) == text


def test_a_repeat_can_end():
    padel = event(at(22, 21), "FREQ=WEEKLY;BYDAY=TH;COUNT=2")
    assert next_occurrence(padel, at(23, 0)) == at(29, 21)
    assert next_occurrence(padel, at(30, 0)) is None


def test_events_from_before_rrules_still_work():
    padel = event(at(22, 21), "thu@21:00")
    assert rule_of(padel).rule == "FREQ=WEEKLY;BYDAY=TH"
    assert next_occurrence(padel, at(23, 0)) == at(29, 21)


def test_moved_occurrences():
    padel = event(at(22, 21), "FREQ=WEEKLY;BYDAY=TH", moved="20261029T2100Z>20261030T1800Z")
    assert next_occurrence(padel, at(23, 0)) == at(30, 18)
    assert not occurs_on(padel, at(29, 0).date(), TZ) and occurs_on(padel, at(30, 0).date(), TZ)


def test_an_occurrence_is_on_until_it_ends():
    trip = event(at(24, 0), all_day=True, ends_at=at(27, 0), title="trip")
    assert next_occurrence(trip, at(26, 12)) == at(24, 0)
    assert [d for d in range(23, 28) if occurs_on(trip, at(d, 0).date(), TZ)] == [24, 25, 26]
    dinner = event(at(24, 19), ends_at=at(24, 22))
    assert next_occurrence(dinner, at(24, 21)) == at(24, 19)
    assert next_occurrence(dinner, at(24, 23)) is None


# --- Google's JSON ------------------------------------------------------------

def test_from_google():
    g = from_google({
        "id": "abc", "status": "confirmed", "summary": "Padel", "etag": '"1"', "updated": "2026-10-20T10:00:00.000Z",
        "start": {"dateTime": "2026-10-22T21:00:00+01:00", "timeZone": "Europe/Lisbon"},
        "end": {"dateTime": "2026-10-22T22:30:00+01:00", "timeZone": "Europe/Lisbon"},
        "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TH", "EXDATE;TZID=Europe/Lisbon:20261029T210000"],
    }, "Europe/Lisbon")
    assert (g.title, g.rule, g.cancelled, g.all_day) == ("Padel", "FREQ=WEEKLY;BYDAY=TH", False, False)
    assert g.starts_at == datetime(2026, 10, 22, 21, tzinfo=timezone(timedelta(hours=1)))
    assert g.ends_at - g.starts_at == timedelta(minutes=90)
    assert g.exdates == {at(29, 21)}
    assert g.updated == datetime(2026, 10, 20, 10, tzinfo=timezone.utc)


def test_from_google_all_day_and_exception():
    g = from_google({"id": "d", "summary": "Trip", "start": {"date": "2026-10-24"}, "end": {"date": "2026-10-27"}},
                    "Europe/Lisbon")
    assert (g.all_day, g.starts_at, g.ends_at) == (True, at(24, 0), at(27, 0))
    g = from_google({"id": "abc_1", "status": "cancelled", "recurringEventId": "abc",
                     "originalStartTime": {"dateTime": "2026-10-29T21:00:00Z"}}, "Europe/Lisbon")
    assert (g.cancelled, g.recurring_event_id, g.original_start) == (True, "abc", at(29, 21))


def test_to_google():
    body = to_google(event(at(22, 21), "FREQ=WEEKLY;BYDAY=TH", skipped="20261029T2100Z"))
    assert body["start"] == {"dateTime": "2026-10-22T21:00:00+01:00", "timeZone": "Europe/Lisbon"}
    assert body["end"]["dateTime"] == "2026-10-22T22:00:00+01:00"   # Google's default hour
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TH", "EXDATE;TZID=Europe/Lisbon:20261029T210000"]
    body = to_google(event(at(24, 0), all_day=True, title="dentist"))
    assert (body["start"], body["end"], body["recurrence"]) == ({"date": "2026-10-24"}, {"date": "2026-10-25"}, [])


# --- a fake Google ------------------------------------------------------------

class FakeGoogle:
    """Google's OAuth and Calendar API, enough for the bot; everything it was asked is in `calls`."""

    def __init__(self):
        self.calendars = [
            {"id": "me@gmail.com", "summary": "Roman", "timeZone": "Europe/Lisbon", "primary": True},
            {"id": "work@group.calendar.google.com", "summary": "Work", "timeZone": "Europe/Lisbon",
             "accessRole": "writer"},
            {"id": "pt.portuguese#holiday@group.v.calendar.google.com", "summary": "Holidays",
             "timeZone": "Europe/Lisbon", "accessRole": "reader"},
        ]
        self.events = {}        # (calendar id, event id) → item
        self.version = 0
        self.calls = []
        self.refused = False    # the login expired
        self.gone_tokens = set()
        self.ids = 0

    def add(self, calendar_id, item):
        """An event made or changed in Google."""
        self.version += 1
        item = {"status": "confirmed", "etag": f'"{self.version}"',
                "updated": datetime.now(timezone.utc).isoformat(), **item, "_v": self.version}
        self.events[(calendar_id, item["id"])] = item
        return item

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        form = parse_qs(request.content.decode()) if request.method == "POST" and b"=" in request.content \
            and not request.content.startswith(b"{") else {}
        body = json.loads(request.content) if request.content.startswith(b"{") else None
        self.calls.append((request.method, url.path, dict(parse_qs(url.query)), body))
        if url.netloc == "oauth2.googleapis.com" and url.path == "/token":
            if self.refused and form.get("grant_type") == ["refresh_token"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            tokens = {"access_token": "access", "expires_in": 3600,
                      "scope": "https://www.googleapis.com/auth/calendar.events "
                               "https://www.googleapis.com/auth/calendar.calendarlist.readonly"}
            if form.get("grant_type") == ["authorization_code"]:
                tokens["refresh_token"] = "refresh-" + form["code"][0]
            return httpx.Response(200, json=tokens)
        if url.path == "/revoke":
            return httpx.Response(200)
        path = url.path.removeprefix("/calendar/v3")
        if path == "/users/me/calendarList":
            return httpx.Response(200, json={"items": self.calendars})
        if path == "/channels/stop":
            return httpx.Response(204)
        parts = path.split("/")    # ["", "calendars", <id>, "events", <event id or "watch">]
        calendar_id = unquote(parts[2]) if len(parts) > 2 else None
        if path.endswith("/events/watch"):
            expiration = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp() * 1000)
            return httpx.Response(200, json={"resourceId": f"res-{body['id']}", "expiration": str(expiration)})
        if len(parts) == 4 and request.method == "GET":
            query = parse_qs(url.query)
            token = query.get("syncToken", [None])[0]
            if token == "too-old":
                return httpx.Response(410, json={"error": {"code": 410}})
            since = int(token) if token else 0
            items = [{k: v for k, v in item.items() if k != "_v"} for (c, _), item in self.events.items()
                     if c == calendar_id and item["_v"] > since]
            return httpx.Response(200, json={"items": items, "nextSyncToken": str(self.version)})
        if len(parts) == 4 and request.method == "POST":
            self.ids += 1
            item = self.add(calendar_id, {**body, "id": f"bot{self.ids}"})
            return httpx.Response(200, json={k: v for k, v in item.items() if k != "_v"})
        event_id = unquote(parts[4])
        key = (calendar_id, event_id)
        if request.method == "PATCH":
            if key not in self.events:
                return httpx.Response(404)
            if self.events[key]["status"] == "cancelled":
                # What Google answers for a deleted event
                return httpx.Response(410, json={"error": {"code": 410, "message": "Resource has been deleted"}})
            item = self.add(calendar_id, {**self.events[key], **body})
            return httpx.Response(200, json={k: v for k, v in item.items() if k != "_v"})
        if request.method == "DELETE":
            if key in self.events:
                self.add(calendar_id, {**self.events[key], "status": "cancelled"})
            return httpx.Response(204)
        return httpx.Response(500)

    def asked(self, method, suffix=""):
        return [c for c in self.calls if c[0] == method and c[1].endswith(suffix)]


@pytest.fixture
def google(monkeypatch):
    import config
    from services import google_calendar

    fake = FakeGoogle()
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(config, "GOOGLE_REDIRECT_URI", "https://calendar.example.com/oauth/callback")
    monkeypatch.setattr(config, "CALENDAR_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(google_calendar, "transport", httpx.MockTransport(fake.handle))
    google_calendar._access.clear()
    return fake


def run(coroutine):
    """Run it and the tasks it starts (the first sync after linking, a sync after a push)."""
    async def everything():
        result = await coroutine
        while pending := [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
            await asyncio.gather(*pending)
        return result
    return asyncio.run(everything())


def _user(chat):
    from db.repositories.user import UserRepository
    return UserRepository().get_by_telegram_id(chat.telegram_id)


def _events(chat):
    from db.repositories.event import EventRepository
    return EventRepository().list_active(_user(chat).id)


def link(chat, google_fake):
    from core import secrets
    import config
    from handlers.calendar import complete_link

    state = secrets.sign_state(chat.telegram_id, config.CALENDAR_KEY)
    return run(complete_link(chat.context.bot, state, "code1"))


def sync(chat):
    from handlers.calendar import sync_user
    run(sync_user(chat.context.bot, _user(chat)))


def _told(chat):
    return [c.kwargs.get("text") for c in chat.context.bot.send_message.call_args_list]


# --- linking ----------------------------------------------------------------------

def test_not_set_up(chat):
    from handlers.calendar import on_calendar_cmd
    assert _replies(chat(text="/calendar", handler=on_calendar_cmd))[0] == "📅 Google Calendar isn't set up on this bot."


def test_link_button(chat, google):
    from handlers.calendar import on_calendar_cmd

    update = chat(text="/calendar", handler=on_calendar_cmd)
    assert "your events then go to Google" in _replies(update)[0]
    button = update.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    query = parse_qs(urlsplit(button.url).query)
    assert query["client_id"] == ["client.apps.googleusercontent.com"] and query["access_type"] == ["offline"]
    assert query["scope"] == ["https://www.googleapis.com/auth/calendar.events "
                              "https://www.googleapis.com/auth/calendar.calendarlist.readonly"]


def test_linking(chat, google):
    from db.repositories.google import GoogleRepository

    chat("event padel on dec 24 at 21:00")
    page = link(chat, google)
    assert page == "✅ Google Calendar is linked. You can go back to Telegram."
    assert _told(chat)[0].startswith("✅ Google Calendar linked.")
    account = GoogleRepository().account(_user(chat).id)
    assert account.default_calendar_id == "me@gmail.com" and "refresh-code1" not in account.refresh_token
    calendars = GoogleRepository().calendars(_user(chat).id)
    assert [(c.summary, c.selected, c.writable) for c in calendars] == [
        ("Roman", True, True), ("Holidays", False, False), ("Work", False, True)]
    assert calendars[0].channel_id and google.asked("POST", "/events/watch")[0][3]["address"] \
        == "https://calendar.example.com/google/push"
    # The event made in the bot went to Google
    [padel] = _events(chat)
    assert padel.external_id == "bot1" and padel.external_calendar_id == "me@gmail.com"
    assert google.events[("me@gmail.com", "bot1")]["summary"] == "padel"


def test_link_with_a_forged_or_old_state(chat, google):
    from core import secrets
    import config
    from handlers.calendar import complete_link

    old = secrets.sign_state(chat.telegram_id, config.CALENDAR_KEY, now=0)
    assert run(complete_link(chat.context.bot, old, "c")).startswith("That link has expired.")
    assert run(complete_link(chat.context.bot, f"{chat.telegram_id}.1.forged", "c")).startswith("That link has expired.")


# --- Google → bot -----------------------------------------------------------------

def _padel(google, **more):
    return google.add("me@gmail.com", {
        "id": "g1", "summary": "Padel",
        "start": {"dateTime": "2026-10-29T21:00:00+00:00", "timeZone": "Europe/Lisbon"},
        "end": {"dateTime": "2026-10-29T22:30:00+00:00", "timeZone": "Europe/Lisbon"},
        "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TH"], **more,
    })


def test_import_and_remind_before_a_google_event(chat, google):
    _padel(google)
    google.add("work@group.calendar.google.com", {"id": "w1", "summary": "Standup",
                                                  "start": {"dateTime": "2026-10-29T09:00:00+00:00"},
                                                  "end": {"dateTime": "2026-10-29T09:15:00+00:00"}})
    link(chat, google)
    [padel] = _events(chat)     # Work isn't synced
    assert (padel.title, padel.recurrence, padel.external_id) == ("Padel", "FREQ=WEEKLY;BYDAY=TH", "g1")
    assert padel.ends_at - padel.starts_at == timedelta(minutes=90)
    text = _replies(chat("my events"))[0]
    assert "1. Padel\n    🗓 " in text and "21:00–22:30" in text and "🔁 every Thu at 21:00" in text
    assert _replies(chat("remind me 30 min before padel to pack the racket"))[0].endswith("or every time?")


def test_changes_in_google(chat, google):
    from db.repositories.reminder import ReminderRepository
    from handlers.events import on_event_button

    _padel(google)
    link(chat, google)
    [padel] = _events(chat)
    chat(data=f"evt:rem:{padel.id}:-30", handler=on_event_button)
    chat(data=f"evt:every:{padel.id}", handler=on_event_button)
    # Moved to 20:00 in Google: the reminder follows
    _padel(google, start={"dateTime": "2026-10-29T20:00:00+00:00", "timeZone": "Europe/Lisbon"},
           end={"dateTime": "2026-10-29T21:00:00+00:00", "timeZone": "Europe/Lisbon"})
    sync(chat)
    [reminder] = ReminderRepository().list_for_event(padel.id)
    assert reminder.remind_at.astimezone(TZ).time() == time(19, 30)
    # One Thursday cancelled in Google: skipped
    google.add("me@gmail.com", {"id": "g1_20261105", "status": "cancelled", "recurringEventId": "g1",
                                "originalStartTime": {"dateTime": "2026-11-05T20:00:00+00:00"}})
    sync(chat)
    [padel] = _events(chat)
    assert padel.skipped == "20261105T2000Z"
    # Deleted in Google: so are the event (not even kept as cancelled) and its reminder
    from db.repositories.event import EventRepository
    google.add("me@gmail.com", {"id": "g1", "status": "cancelled"})
    sync(chat)
    assert _events(chat) == [] and EventRepository().get(padel.id) is None
    assert ReminderRepository().get(reminder.id).status == "cancelled"


def test_an_occurrence_moved_in_google(chat, google):
    _padel(google)
    link(chat, google)
    google.add("me@gmail.com", {"id": "g1_20261029", "recurringEventId": "g1", "summary": "Padel",
                                "originalStartTime": {"dateTime": "2026-10-29T21:00:00+00:00"},
                                "start": {"dateTime": "2026-10-30T18:00:00+00:00"},
                                "end": {"dateTime": "2026-10-30T19:30:00+00:00"}})
    sync(chat)
    [padel] = _events(chat)
    assert padel.moved == "20261029T2100Z>20261030T1800Z"
    assert next_occurrence(padel, datetime(2026, 10, 24, tzinfo=timezone.utc)) == datetime(2026, 10, 30, 18,
                                                                                           tzinfo=timezone.utc)


def test_a_sync_token_too_old(chat, google):
    from db.repositories.google import GoogleRepository

    link(chat, google)
    [calendar, *_] = GoogleRepository().calendars(_user(chat).id)
    GoogleRepository().update_calendar(calendar.id, sync_token="too-old")
    _padel(google)
    sync(chat)
    assert [e.title for e in _events(chat)] == ["Padel"]


# --- bot → Google -----------------------------------------------------------------

def test_cancelling_a_google_event_in_the_bot_deletes_it(chat, google):
    from db.repositories.event import EventRepository
    from handlers.events import on_event_button
    from services import google_calendar

    _padel(google)
    google.add("me@gmail.com", {"id": "g2", "summary": "Dinner",
                                "start": {"dateTime": "2026-12-24T19:00:00+00:00"},
                                "end": {"dateTime": "2026-12-24T22:00:00+00:00"}})
    link(chat, google)
    padel, dinner = sorted(_events(chat), key=lambda e: e.title, reverse=True)
    chat(data=f"evt:del:{padel.id}", handler=on_event_button)
    assert google.events[("me@gmail.com", "g1")]["status"] == "cancelled"
    assert EventRepository().get(padel.id) is None
    # Google unreachable: kept (cancelled) until Google knows, then deleted
    working = google_calendar.transport
    google_calendar.transport = httpx.MockTransport(lambda request: httpx.Response(503))
    chat(data=f"evt:del:{dinner.id}", handler=on_event_button)
    assert EventRepository().get(dinner.id).pending_push
    google_calendar.transport = working
    sync(chat)
    assert EventRepository().get(dinner.id) is None
    assert google.events[("me@gmail.com", "g2")]["status"] == "cancelled"


def test_changes_in_the_bot_go_to_google(chat, google):
    from handlers.events import on_event_button

    link(chat, google)
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat)
    assert google.events[("me@gmail.com", padel.external_id)]["start"]["dateTime"] == "2026-12-24T21:00:00+00:00"
    chat("move padel to 20:00")
    assert google.events[("me@gmail.com", padel.external_id)]["start"]["dateTime"] == "2026-12-24T20:00:00+00:00"
    chat(data=f"evt:del:{padel.id}", handler=on_event_button)
    assert google.events[("me@gmail.com", padel.external_id)]["status"] == "cancelled"
    # Made in the bot: kept as cancelled, like any event of the bot's
    from db.repositories.event import EventRepository
    assert EventRepository().get(padel.id).status == "cancelled"


def test_google_unreachable_sends_it_later(chat, google):
    from services import google_calendar

    link(chat, google)
    working = google_calendar.transport
    google_calendar.transport = httpx.MockTransport(lambda request: httpx.Response(503))
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat)
    assert padel.pending_push and padel.external_id is None
    google_calendar.transport = working
    sync(chat)
    [padel] = _events(chat)
    assert not padel.pending_push and padel.external_id is not None


def test_last_change_wins(chat, google):
    from db.repositories.event import EventRepository

    _padel(google)
    link(chat, google)
    [padel] = _events(chat)
    # Changed in the bot (not sent yet), then an older change comes from Google
    EventRepository().update(padel.id, title="Padel with Anna", pending_push=True)
    _padel(google, summary="Old title", updated="2026-01-01T00:00:00Z")
    sync(chat)
    [padel] = _events(chat)
    assert padel.title == "Padel with Anna"
    assert google.events[("me@gmail.com", "g1")]["summary"] == "Padel with Anna"


# --- syncing when asked, push notifications ---------------------------------------

def test_sync_when_asked_at_most_every_5_minutes(chat, google):
    from db.repositories.google import GoogleRepository

    link(chat, google)
    lists = len(google.asked("GET", "/events"))
    chat("my events")
    assert len(google.asked("GET", "/events")) == lists     # just synced when linking
    GoogleRepository().update_account(_user(chat).id, last_poll_at=datetime.now(timezone.utc) - timedelta(minutes=6))
    _padel(google)
    chat("my events")
    assert len(google.asked("GET", "/events")) == lists + 1
    assert [e.title for e in _events(chat)] == ["Padel"]
    chat("what do I have tomorrow?")
    assert len(google.asked("GET", "/events")) == lists + 1


def test_push_notifications(chat, google):
    from db.repositories.google import GoogleRepository
    from handlers.calendar import on_push

    link(chat, google)
    [calendar, *_] = GoogleRepository().calendars(_user(chat).id)
    _padel(google)
    assert not run(on_push(chat.context.bot, calendar.channel_id, "wrong", "exists"))
    assert _events(chat) == []
    assert run(on_push(chat.context.bot, calendar.channel_id, calendar.channel_token, "exists"))
    assert [e.title for e in _events(chat)] == ["Padel"]


def test_renewing_channels(chat, google):
    from db.repositories.google import GoogleRepository
    from handlers.calendar import renew_channels

    link(chat, google)
    [calendar, *_] = GoogleRepository().calendars(_user(chat).id)
    GoogleRepository().update_calendar(calendar.id, channel_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    run(renew_channels(chat.context.bot))
    renewed = GoogleRepository().calendar(calendar.id)
    assert renewed.channel_id != calendar.channel_id and google.asked("POST", "/channels/stop")


def test_web_routes(chat, google):
    from aiohttp.test_utils import make_mocked_request
    from handlers import web

    app = web.make_app(chat.context.bot)
    request = make_mocked_request("GET", "/oauth/callback?error=access_denied", app=app)
    assert "cancelled" in run(web.oauth_callback(request)).text
    request = make_mocked_request("POST", "/google/push", headers={"X-Goog-Channel-ID": "nope"}, app=app)
    assert run(web.google_push(request)).status == 404


# --- an expired login, unlinking ------------------------------------------------------

def test_an_expired_login_warns_once(chat, google):
    from db.repositories.google import GoogleRepository
    from services import google_calendar

    chat("event padel on dec 24 at 21:00")
    link(chat, google)
    google.refused = True
    google_calendar._access.clear()
    GoogleRepository().update_account(_user(chat).id, last_poll_at=datetime.now(timezone.utc) - timedelta(minutes=6))
    text = _replies(chat("my events"))[0]
    assert text.startswith("⚠️ Google Calendar isn't syncing: link it again")
    warnings = [t for t in _told(chat) if t.startswith("⚠️ Google Calendar disconnected")]
    assert len(warnings) == 1
    sync(chat)
    assert len([t for t in _told(chat) if t.startswith("⚠️ Google Calendar disconnected")]) == 1
    # Events stay as they are; a change waits for linking again
    assert [e.title for e in _events(chat)] == ["padel"]
    chat("move padel to 20:00")
    assert _events(chat)[0].pending_push
    google.refused = False
    link(chat, google)
    [padel] = _events(chat)
    assert not padel.pending_push
    assert google.events[("me@gmail.com", padel.external_id)]["start"]["dateTime"] == "2026-12-24T20:00:00+00:00"


@pytest.mark.parametrize("answer, left", [("keep", ["Padel"]), ("rm", [])])
def test_unlink(chat, google, answer, left):
    from db.repositories.google import GoogleRepository
    from handlers.calendar import on_calendar_button

    _padel(google)
    link(chat, google)
    chat(data="gcal:unl", handler=on_calendar_button)
    text, keyboard = chat.screen()
    assert text.startswith("Unlink Google Calendar? 1 of its events are in the bot.")
    assert _buttons(keyboard) == [[("📌 Keep them", "gcal:keep:all"), ("🗑 Remove them", "gcal:rm:all")]]
    [padel] = _events(chat)
    chat(data=f"gcal:{answer}:all", handler=on_calendar_button)
    assert [e.title for e in _events(chat)] == left
    from db.repositories.event import EventRepository
    assert (EventRepository().get(padel.id) is None) == (answer == "rm")
    # Kept ones aren't synced any more (their Google ids stay, to link up again later)
    assert all(e.external_source is None for e in _events(chat))
    assert GoogleRepository().account(_user(chat).id) is None
    assert google.asked("POST", "/revoke")


def test_picking_calendars(chat, google):
    from db.repositories.google import GoogleRepository
    from handlers.calendar import on_calendar_button

    link(chat, google)
    google.add("work@group.calendar.google.com", {"id": "w1", "summary": "Standup",
                                                  "start": {"dateTime": "2026-12-29T09:00:00+00:00"},
                                                  "end": {"dateTime": "2026-12-29T09:15:00+00:00"}})
    [_, holidays, work] = GoogleRepository().calendars(_user(chat).id)
    run_button = lambda data: chat(data=data, handler=on_calendar_button)  # noqa: E731
    run_button(f"gcal:tgl:{work.id}")
    run_button(f"gcal:tgl:{holidays.id}")
    sync(chat)
    assert [e.title for e in _events(chat)] == ["Standup"]
    text, keyboard = chat.screen()
    assert ("✅ Work", f"gcal:tgl:{work.id}") in [b for row in _buttons(keyboard) for b in row]
    run_button("gcal:def")
    assert GoogleRepository().account(_user(chat).id).default_calendar_id == "work@group.calendar.google.com"
    run_button("gcal:def")    # not Holidays: read-only
    assert GoogleRepository().account(_user(chat).id).default_calendar_id == "me@gmail.com"
    run_button(f"gcal:tgl:{work.id}")
    assert chat.screen()[0].startswith("Stop syncing Work? 1 of its events")


def test_cancelled_before_it_reached_google(chat, google):
    from db.repositories.event import EventRepository
    from handlers.events import on_event_button
    from services import google_calendar

    link(chat, google)
    working = google_calendar.transport
    google_calendar.transport = httpx.MockTransport(lambda request: httpx.Response(503))
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat)
    chat(data=f"evt:del:{padel.id}", handler=on_event_button)
    google_calendar.transport = working
    assert not EventRepository().get(padel.id).pending_push
    # Syncing still works afterwards
    _padel(google)
    sync(chat)
    assert [e.title for e in _events(chat)] == ["Padel"]


def test_a_pending_cancellation_that_never_reached_google(chat, google):
    from db.repositories.event import EventRepository

    from services import google_calendar

    link(chat, google)
    working = google_calendar.transport
    google_calendar.transport = httpx.MockTransport(lambda request: httpx.Response(503))
    chat("event padel on dec 24 at 21:00")
    google_calendar.transport = working
    [padel] = _events(chat)
    # Left over from before the fix: cancelled, never in Google, still marked pending
    EventRepository().cancel(padel.id)
    assert EventRepository().get(padel.id).pending_push
    _padel(google)
    sync(chat)
    assert not EventRepository().get(padel.id).pending_push
    assert [e.title for e in _events(chat)] == ["Padel"]


def test_a_failed_google_event_is_retried(chat, google, monkeypatch):
    from db.repositories.google import GoogleRepository
    from handlers import calendar as handlers_calendar

    link(chat, google)
    [calendar, *_] = GoogleRepository().calendars(_user(chat).id)
    token = GoogleRepository().calendar(calendar.id).sync_token
    _padel(google)
    real = handlers_calendar.apply

    async def broken(*args, **kwargs):
        raise RuntimeError("database hiccup")
    monkeypatch.setattr(handlers_calendar, "apply", broken)
    sync(chat)
    assert _events(chat) == [] and GoogleRepository().calendar(calendar.id).sync_token == token
    monkeypatch.setattr(handlers_calendar, "apply", real)
    sync(chat)
    assert [e.title for e in _events(chat)] == ["Padel"]
    assert GoogleRepository().calendar(calendar.id).sync_token != token


def test_changing_an_event_deleted_in_google(chat, google):
    from db.repositories.event import EventRepository

    link(chat, google)
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat)
    old_id = padel.external_id
    # Deleted in Google; the bot hasn't synced since. Moving it in the bot (newer) puts it back.
    google.add("me@gmail.com", {**google.events[("me@gmail.com", old_id)], "status": "cancelled"})
    chat("move padel to 20:00")
    moved = EventRepository().get(padel.id)
    assert not moved.pending_push and moved.external_id != old_id
    assert google.events[("me@gmail.com", moved.external_id)]["start"]["dateTime"] == "2026-12-24T20:00:00+00:00"


def test_one_event_google_wont_take_doesnt_stop_the_sync(chat, google, monkeypatch):
    from db.repositories.event import EventRepository
    from handlers import calendar as handlers_calendar

    link(chat, google)
    chat("event padel on dec 24 at 21:00")
    [padel] = _events(chat)
    EventRepository().set_sync(padel.id, pending_push=True)
    real = handlers_calendar._send

    async def refused(client, event, calendar_id):
        if event.id == padel.id:
            raise RuntimeError("something unexpected")
        await real(client, event, calendar_id)
    monkeypatch.setattr(handlers_calendar, "_send", refused)
    google.add("me@gmail.com", {"id": "g2", "summary": "Dinner", "start": {"dateTime": "2026-12-25T19:00:00+00:00"},
                                "end": {"dateTime": "2026-12-25T22:00:00+00:00"}})
    sync(chat)
    assert sorted(e.title for e in _events(chat)) == ["Dinner", "padel"]
    assert EventRepository().get(padel.id).pending_push     # tried again next time


def test_keep_then_sync_again_links_them_up(chat, google):
    from db.repositories.google import GoogleRepository
    from handlers.calendar import on_calendar_button

    _padel(google)
    link(chat, google)
    [roman, *_] = GoogleRepository().calendars(_user(chat).id)
    chat(data=f"gcal:tgl:{roman.id}", handler=on_calendar_button)
    chat(data=f"gcal:keep:{roman.id}", handler=on_calendar_button)
    [kept] = _events(chat)
    # Not synced meanwhile: a change here stays here
    chat("move padel to 20:00")
    assert google.asked("PATCH") == []
    chat(data=f"gcal:tgl:{roman.id}", handler=on_calendar_button)
    sync(chat)
    [padel] = _events(chat)
    assert padel.id == kept.id and padel.external_source == "google"


def test_unlink_keep_then_link_again(chat, google):
    from handlers.calendar import on_calendar_button

    _padel(google)
    link(chat, google)
    chat(data="gcal:unl", handler=on_calendar_button)
    chat(data="gcal:keep:all", handler=on_calendar_button)
    link(chat, google)
    assert [e.title for e in _events(chat)] == ["Padel"]


def test_a_sync_during_the_bots_own_insert_doesnt_import_it(chat, google):
    from db.repositories.event import EventRepository
    from handlers.calendar import push, sync_user
    from services import google_calendar

    link(chat, google)
    user = _user(chat)
    padel = EventRepository().create(user.id, "padel", datetime(2026, 12, 24, 21, tzinfo=TZ), "Europe/Lisbon")

    async def slow(request):
        response = google.handle(request)
        if request.method == "POST" and request.url.path.endswith("/events"):
            # Google has it, the bot doesn't know its id yet
            await asyncio.sleep(0.05)
        return response
    google_calendar.transport = httpx.MockTransport(slow)

    async def both():
        await asyncio.gather(push(chat.context.bot, padel), sync_user(chat.context.bot, user))
    run(both())
    assert [e.id for e in _events(chat)] == [padel.id]


def test_an_event_that_always_fails_is_given_up_after_3_tries(chat, google, monkeypatch):
    from db.repositories.google import GoogleRepository
    from handlers import calendar as handlers_calendar

    link(chat, google)
    [calendar, *_] = GoogleRepository().calendars(_user(chat).id)
    token = GoogleRepository().calendar(calendar.id).sync_token
    _padel(google)

    async def broken(*args, **kwargs):
        raise ValueError("odd data")
    monkeypatch.setattr(handlers_calendar, "apply", broken)
    sync(chat)
    sync(chat)
    assert GoogleRepository().calendar(calendar.id).sync_token == token
    sync(chat)
    assert GoogleRepository().calendar(calendar.id).sync_token != token


def test_push_with_an_odd_token(chat, google):
    from db.repositories.google import GoogleRepository
    from handlers.calendar import on_push

    link(chat, google)
    [calendar, *_] = GoogleRepository().calendars(_user(chat).id)
    assert not run(on_push(chat.context.bot, calendar.channel_id, "tökén", "exists"))


def test_a_wrong_client_secret_isnt_an_expired_login(chat, google):
    from db.repositories.google import GoogleRepository
    from services import google_calendar

    link(chat, google)
    google_calendar._access.clear()
    working = google.handle

    def bad_client(request):
        if request.url.path == "/token":
            return httpx.Response(401, json={"error": "invalid_client"})
        return working(request)
    google_calendar.transport = httpx.MockTransport(bad_client)
    sync(chat)
    assert GoogleRepository().account(_user(chat).id).status == "linked"
    assert not [t for t in _told(chat) if t.startswith("⚠️ Google Calendar disconnected")]


def test_an_invalid_calendar_key_turns_it_off(google, monkeypatch, caplog):
    import config

    monkeypatch.setattr(config, "CALENDAR_KEY", "not-a-key")
    assert not config.calendar_configured()
    assert "CALENDAR_KEY isn't a valid key" in caplog.text


@pytest.mark.parametrize("linked_before", [False, True])
def test_a_permission_left_unticked(chat, google, linked_before):
    from db.repositories.google import GoogleRepository
    from enums import GoogleStatus

    if linked_before:
        link(chat, google)
        GoogleRepository().update_account(_user(chat).id, status=GoogleStatus.EXPIRED)
    working = google.handle

    def no_calendar_list(request):
        # Google gave a login without saying which permissions, then refuses the calendar list
        if request.url.path == "/token":
            response = working(request)
            tokens = response.json()
            tokens.pop("scope")
            return httpx.Response(200, json=tokens)
        if request.url.path.endswith("/calendarList"):
            return httpx.Response(403, json={"error": {"message": "Request had insufficient authentication scopes."}})
        return working(request)
    from services import google_calendar
    google_calendar.transport = httpx.MockTransport(no_calendar_list)
    told = len(_told(chat))
    assert link(chat, google).startswith("The bot needs both permissions.")
    account = GoogleRepository().account(_user(chat).id)
    if linked_before:
        assert account.status == GoogleStatus.EXPIRED and GoogleRepository().calendars(_user(chat).id)
    else:
        assert account is None and GoogleRepository().calendars(_user(chat).id) == []
    assert len(_told(chat)) == told    # no "linked" and no "expired" message
