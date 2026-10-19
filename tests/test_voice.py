"""Voice messages: the speech-service client and the handler (service faked)."""

import asyncio
import json
import random

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import config

from services import speech


@pytest.fixture
def speech_server(monkeypatch):
    """Fake speech-service: set .status / .body; .requests records what was sent."""
    class Server:
        status = 200
        body = {"text": "remind me tomorrow at nine to call mom", "duration": 2.0, "model": "fake"}
        requests = []

        def handle(self, request):
            self.requests.append(request)
            return httpx.Response(self.status, content=json.dumps(self.body))

    server = Server()
    monkeypatch.setattr(config, "SPEECH_URL", "http://speech:8000/")
    monkeypatch.setattr(config, "SPEECH_TOKEN", None)
    monkeypatch.setattr(speech, "transport", httpx.MockTransport(server.handle))
    return server


# --- client -------------------------------------------------------------------

def test_transcribe_posts_the_audio(speech_server):
    assert asyncio.run(speech.transcribe(b"OggS...")) == "remind me tomorrow at nine to call mom"
    request = speech_server.requests[0]
    assert str(request.url) == "http://speech:8000/transcribe"
    assert request.content == b"OggS..."
    assert "authorization" not in request.headers


def test_transcribe_sends_the_token(speech_server, monkeypatch):
    monkeypatch.setattr(config, "SPEECH_TOKEN", "secret")
    asyncio.run(speech.transcribe(b"x"))
    assert speech_server.requests[0].headers["authorization"] == "Bearer secret"


def test_transcribe_invalid_audio(speech_server):
    speech_server.status, speech_server.body = 400, {"detail": "Couldn't decode the audio."}
    with pytest.raises(speech.InvalidAudio):
        asyncio.run(speech.transcribe(b"x"))


@pytest.mark.parametrize("status", [401, 500, 503])
def test_transcribe_server_errors(speech_server, status):
    speech_server.status, speech_server.body = status, {"detail": "no"}
    with pytest.raises(speech.SpeechUnavailable):
        asyncio.run(speech.transcribe(b"x"))


def test_transcribe_unreachable(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(config, "SPEECH_URL", "http://speech:8000")
    monkeypatch.setattr(speech, "transport", httpx.MockTransport(refuse))
    with pytest.raises(speech.SpeechUnavailable):
        asyncio.run(speech.transcribe(b"x"))


def test_not_configured(monkeypatch):
    monkeypatch.setattr(config, "SPEECH_URL", None)
    assert not speech.is_configured()
    with pytest.raises(speech.SpeechUnavailable):
        asyncio.run(speech.transcribe(b"x"))


# --- handler ------------------------------------------------------------------

@pytest.fixture
def voice_update(db):
    """A voice message from a user with a timezone; returns (update, context)."""
    from db.repositories.user import UserRepository

    telegram_id = random.randint(10**9, 10**12)
    UserRepository().get_or_create(telegram_id)
    UserRepository().set_timezone(telegram_id, "Europe/Lisbon")

    update = MagicMock()
    update.effective_user.id = telegram_id
    update.effective_chat.id = telegram_id
    update.callback_query = None
    update.effective_message.reply_text = AsyncMock()
    update.effective_message.voice.duration = 3
    file = MagicMock()
    file.download_as_bytearray = AsyncMock(return_value=bytearray(b"OggS..."))
    update.effective_message.voice.get_file = AsyncMock(return_value=file)

    context = MagicMock(user_data={}, chat_data={})
    context.bot.send_chat_action = AsyncMock()
    return update, context


def _replies(update):
    return [c.args[0] for c in update.effective_message.reply_text.call_args_list]


def _on_voice(update, context):
    from handlers.voice import on_voice
    asyncio.run(on_voice(update, context))


def test_voice_creates_a_reminder(speech_server, voice_update):
    update, context = voice_update
    _on_voice(update, context)
    replies = _replies(update)
    assert replies[0] == "🎙 “remind me tomorrow at nine to call mom”"
    assert replies[1].startswith("⏰ Got it: call mom")


def test_voice_reminder_remembers_it_came_by_voice(speech_server, voice_update):
    from db.repositories.reminder import ReminderRepository

    update, context = voice_update
    _on_voice(update, context)
    reminder = ReminderRepository().latest_created(update.effective_user.id)
    assert (reminder.request, reminder.source) == ("tomorrow at nine to call mom", "voice")


def test_voice_not_understood_is_saved(speech_server, voice_update):
    from db.repositories.failed_message import FailedMessageRepository

    update, context = voice_update
    speech_server.body = {"text": "what's the weather"}
    _on_voice(update, context)
    entry = next(f for f in FailedMessageRepository().list_open(10_000) if f.text == "what's the weather")
    assert (entry.source, entry.reason) == ("voice", "not_understood")


def test_voice_answers_a_question(speech_server, voice_update):
    from enums import Awaiting
    from handlers.ui import AWAITING

    update, context = voice_update
    context.user_data[AWAITING] = Awaiting.QUIET_HOURS
    speech_server.body = {"text": "twenty three to seven"}
    _on_voice(update, context)
    assert _replies(update)[1] == "🌙 Quiet hours set to 23:00–07:00."


def test_voice_not_set_up(voice_update, monkeypatch):
    from handlers.voice import NOT_SET_UP

    monkeypatch.setattr(config, "SPEECH_URL", None)
    update, context = voice_update
    _on_voice(update, context)
    assert _replies(update) == [NOT_SET_UP]


def test_voice_unavailable(speech_server, voice_update):
    from handlers.voice import UNAVAILABLE

    speech_server.status = 503
    update, context = voice_update
    _on_voice(update, context)
    assert _replies(update) == [UNAVAILABLE]


@pytest.mark.parametrize("status, body", [(200, {"text": ""}), (400, {"detail": "bad"})])
def test_voice_no_words(speech_server, voice_update, status, body):
    from handlers.voice import NO_WORDS

    speech_server.status, speech_server.body = status, body
    update, context = voice_update
    _on_voice(update, context)
    assert _replies(update) == [NO_WORDS]


def test_voice_too_long(speech_server, voice_update):
    from handlers.voice import TOO_LONG

    update, context = voice_update
    update.effective_message.voice.duration = 600
    _on_voice(update, context)
    assert _replies(update) == [TOO_LONG]
    assert speech_server.requests == []
