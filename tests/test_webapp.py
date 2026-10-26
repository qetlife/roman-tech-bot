"""The web app (#58): Telegram's login data, the session, and the chat API end to end."""

import asyncio
import hashlib
import hmac
import json
import random
import time

from collections    import defaultdict
from types          import SimpleNamespace
from unittest.mock  import AsyncMock, MagicMock
from urllib.parse   import urlencode

import httpx
import pytest

from aiohttp.test_utils import TestClient, TestServer

from core.speakable import speakable
from core.webauth   import (
    LOGIN_MAX_AGE, SESSION_MAX_AGE, check_init_data, check_login, sign_session, verify_session,
)


TOKEN = "123456:test-token"
NOW = 1_800_000_000


def init_data(user: dict, token: str = TOKEN, auth_date: int = NOW) -> str:
    """initData as Telegram signs it for a Mini App."""
    fields = {"auth_date": str(auth_date), "query_id": "AAH", "user": json.dumps(user)}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def login_fields(user_id: int, token: str = TOKEN, auth_date: int = NOW) -> dict:
    """What the Login Widget gives the page."""
    fields = {"id": str(user_id), "first_name": "Roman", "username": "roman", "auth_date": str(auth_date)}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    return fields


# --- login data and sessions (pure) ---------------------------------------------

def test_init_data():
    data = init_data({"id": 42, "first_name": "Roman"})
    assert check_init_data(data, TOKEN, now=NOW + 60) == {"id": 42, "first_name": "Roman"}
    # Another bot's, changed, or old
    assert check_init_data(data, "999:other", now=NOW) is None
    assert check_init_data(data.replace("Roman", "Romam"), TOKEN, now=NOW) is None
    assert check_init_data(data, TOKEN, now=NOW + LOGIN_MAX_AGE + 1) is None
    assert check_init_data("", TOKEN, now=NOW) is None and check_init_data("garbage", TOKEN, now=NOW) is None


def test_login_widget():
    fields = login_fields(42)
    assert check_login(fields, TOKEN, now=NOW)["id"] == 42
    assert check_login({**fields, "id": "43"}, TOKEN, now=NOW) is None
    assert check_login(fields, "999:other", now=NOW) is None
    assert check_login(fields, TOKEN, now=NOW + LOGIN_MAX_AGE + 1) is None
    # initData's key doesn't make Login Widget data, nor the other way round
    assert check_init_data(urlencode(fields), TOKEN, now=NOW) is None


def test_sessions():
    token = sign_session(42, TOKEN, now=NOW)
    assert verify_session(token, TOKEN, now=NOW + 3600) == 42
    assert verify_session(token, "999:other", now=NOW) is None
    assert verify_session(token.replace("42.", "43.", 1), TOKEN, now=NOW) is None
    assert verify_session(token, TOKEN, now=NOW + SESSION_MAX_AGE + 1) is None
    assert verify_session("nonsense", TOKEN) is None


def test_speakable():
    assert speakable("⏰ Got it: call mom\n🗓 Tomorrow, 09:00 (in 9 h)\n🔁 every Mon at 19:00") == \
        "Got it: call mom. Tomorrow, 9:00, in 9 hours. Every Mon at 19:00."
    assert speakable("⏰ What time should I remind you: “dentist”?") == "What time should I remind you: dentist?"
    assert speakable("🎉") == ""
    assert len(speakable("word " * 500)) <= 901


# --- the API ------------------------------------------------------------------------

@pytest.fixture
def web(db, monkeypatch):
    """call(method, path, json=…, data=…, token=…) against the web server, as one user who uses the bot."""
    import config
    from db.repositories.user import UserRepository
    from handlers import web as web_server

    monkeypatch.setattr(config, "BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "WEBAPP_URL", "https://app.example")
    telegram_id = random.randint(10**9, 10**12)
    UserRepository().get_or_create(telegram_id)
    UserRepository().set_timezone(telegram_id, "Europe/Lisbon")

    bot = MagicMock(username="testbot")
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    application = SimpleNamespace(user_data=defaultdict(dict), bot_data={}, bot=bot)

    def call(method, path, token=None, **kwargs):
        async def go():
            # A server per call: each runs in its own event loop
            async with TestClient(TestServer(web_server.make_app(application))) as client:
                headers = kwargs.pop("headers", {})
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                response = await client.request(method, path, headers=headers, **kwargs)
                body = await response.read()
                return response.status, response.headers, body
        return asyncio.run(go())

    call.telegram_id = telegram_id
    call.application = application
    call.token = sign_session(telegram_id, TOKEN)
    return call


def _json(result):
    status, _, body = result
    assert status == 200, body
    return json.loads(body)


def test_the_page(web):
    status, headers, body = web("GET", "/")
    assert status == 200 and b"<title>Reminders</title>" in body
    assert web("GET", "/app.js")[0] == 200 and web("GET", "/style.css")[0] == 200
    assert _json(web("GET", "/api/config"))["bot"] == "testbot"


def test_login(web):
    data = init_data({"id": web.telegram_id, "first_name": "Roman"}, auth_date=int(time.time()))
    body = _json(web("POST", "/api/login", json={"init_data": data}))
    assert verify_session(body["token"], TOKEN) == web.telegram_id and body["name"] == "Roman"
    body = _json(web("POST", "/api/login", json={"login": login_fields(web.telegram_id, auth_date=int(time.time()))}))
    assert verify_session(body["token"], TOKEN) == web.telegram_id
    assert web("POST", "/api/login", json={"init_data": "hash=forged"})[0] == 401
    assert web("POST", "/api/login", json={})[0] == 401


def test_the_api_needs_a_session(web):
    assert web("POST", "/api/message", json={"text": "hi"})[0] == 401
    assert web("POST", "/api/message", json={"text": "hi"}, token="1.2.3")[0] == 401
    assert web("GET", "/api/upcoming", token=sign_session(web.telegram_id, "999:other"))[0] == 401


def test_chat_like_telegram(web):
    body = _json(web("POST", "/api/message", json={"text": "remind me next friday dentist"}, token=web.token))
    [asked] = body["messages"]
    assert asked["text"].startswith("⏰ What time should I remind you: “dentist”?")
    assert asked["buttons"][0][0] == {"text": "🌅 Morning 09:00", "data": "ans:clock:0900"}
    assert asked["id"] < 0

    # The button answers it, and takes the buttons off the question
    body = _json(web("POST", "/api/button", json={"data": "ans:clock:0900", "message_id": asked["id"]},
                     token=web.token))
    assert body["edits"] == [{"id": asked["id"], "buttons": []}]
    [made] = body["messages"]
    assert made["text"].startswith("⏰ Got it: dentist\n")
    assert [b["text"] for b in made["buttons"][0]] == ["↩️ Undo", "✏️ Edit", "👎 Wrong"]

    # "it" is the same conversation as in Telegram
    body = _json(web("POST", "/api/message", json={"text": "cancel that"}, token=web.token))
    assert body["messages"][0]["text"].startswith("🗑 Cancelled: dentist")

    # Undo edits that message in place
    undo = body["messages"][0]
    body = _json(web("POST", "/api/button", json={"data": undo["buttons"][0][0]["data"], "message_id": undo["id"]},
                     token=web.token))
    assert body["alert"] == "It's back"
    assert body["edits"][0]["id"] == undo["id"] and body["edits"][0]["text"].startswith("↩️ Back: dentist")


def test_message_ids_never_repeat_after_a_restart(web):
    first = _json(web("POST", "/api/message", json={"text": "remind me next friday dentist"}, token=web.token))
    # A restart forgets user_data; the page still has the old messages
    web.application.user_data.clear()
    second = _json(web("POST", "/api/message", json={"text": "remind me next friday dentist"}, token=web.token))
    assert second["messages"][0]["id"] < first["messages"][0]["id"] < 0


def test_upcoming(web):
    web("POST", "/api/message", json={"text": "remind me tomorrow at 9 to call mom"}, token=web.token)
    web("POST", "/api/message", json={"text": "event padel tomorrow at 21:00"}, token=web.token)
    days = _json(web("GET", "/api/upcoming", token=web.token))["days"]
    assert len(days) == 7 and days[0]["label"] == "Today" and days[1]["label"] == "Tomorrow"
    # On one day ("tomorrow" before 04:00 is today), soonest first
    [day] = [d for d in days if d["items"]]
    assert day["items"] == [{"kind": "reminder", "time": "09:00", "text": "call mom"},
                            {"kind": "event", "time": "21:00", "text": "padel"}]


def test_voice(web, monkeypatch):
    import config
    from services import speech

    monkeypatch.setattr(config, "SPEECH_URL", "http://speech:8000")
    monkeypatch.setattr(speech, "transport", httpx.MockTransport(
        lambda request: httpx.Response(200, json={"text": "remind me tomorrow at nine to call mom"})))
    body = _json(web("POST", "/api/voice", data=b"OggS" + b"\0" * 2000, token=web.token))
    assert body["heard"] == "remind me tomorrow at nine to call mom"
    assert [m["text"].split("\n")[0] for m in body["messages"]] == \
        ["🎙 “remind me tomorrow at nine to call mom”", "⏰ Got it: call mom"]
    from tests.test_handlers import _active
    assert [r.source for r in _active(web.telegram_id)] == ["voice"]


def test_a_long_recording_arrives_whole(web, monkeypatch):
    import config
    from services import speech

    received = []

    def speech_service(request):
        received.append(request.content)
        return httpx.Response(200, json={"text": "my reminders"})

    monkeypatch.setattr(config, "SPEECH_URL", "http://speech:8000")
    monkeypatch.setattr(speech, "transport", httpx.MockTransport(speech_service))
    recording = bytes(range(256)) * 4096     # 1 MB

    async def in_pieces():
        for start in range(0, len(recording), 64 * 1024):
            yield recording[start:start + 64 * 1024]
            await asyncio.sleep(0)

    assert web("POST", "/api/voice", data=in_pieces(), token=web.token)[0] == 200
    assert received == [recording]
    # Too big: refused by the server itself
    from handlers.webapp import MAX_AUDIO_BYTES
    assert web("POST", "/api/voice", data=b"x" * (MAX_AUDIO_BYTES + 2048), token=web.token)[0] == 413
    assert web("POST", "/api/voice", data=b"", token=web.token)[0] == 400


def test_speak(web, monkeypatch):
    import config
    from services import speech

    asked = []

    def speech_service(request):
        asked.append(json.loads(request.content))
        return httpx.Response(200, content=b"ID3 mp3", headers={"content-type": "audio/mpeg"})

    monkeypatch.setattr(config, "SPEECH_URL", "http://speech:8000")
    monkeypatch.setattr(speech, "transport", httpx.MockTransport(speech_service))
    status, headers, body = web("POST", "/api/speak", json={"text": "⏰ Got it: call mom"}, token=web.token)
    assert (status, headers["Content-Type"], body) == (200, "audio/mpeg", b"ID3 mp3")
    assert asked == [{"text": "Got it: call mom.", "format": "mp3"}]

    monkeypatch.setattr(speech, "transport", httpx.MockTransport(lambda request: httpx.Response(503)))
    assert web("POST", "/api/speak", json={"text": "hi"}, token=web.token)[0] == 503
    assert web("POST", "/api/speak", json={"text": "🎉"}, token=web.token)[0] == 400


def test_a_crash_says_sorry(web, monkeypatch):
    from handlers import webapp

    async def boom(update, context, text):
        raise RuntimeError("bug")

    monkeypatch.setattr(webapp, "handle_text", boom)
    body = _json(web("POST", "/api/message", json={"text": "hi"}, token=web.token))
    assert body["messages"][0]["text"].startswith("Sorry, something went wrong")


def test_no_web_app_without_its_address(web, monkeypatch):
    import config
    from handlers import web as web_server

    monkeypatch.setattr(config, "WEBAPP_URL", None)
    app = web_server.make_app(web.application)
    assert not any(r.resource.canonical == "/api/message" for r in app.router.routes())
