"""Client for the speech-service (https://github.com/qetlife/speech-service).

POST the voice message as it is (Telegram's OGG/Opus), get the text back.
Spoken numbers come back as words ("nine thirty"); core/numbers.py handles them.
"""

import httpx

import config


# Seconds to wait for a transcription (the service cuts audio at 2 minutes).
TIMEOUT = 60

# Set by tests to fake the HTTP server (an httpx.MockTransport).
transport = None


class SpeechUnavailable(Exception):
    """Voice isn't configured, or the service can't be reached or failed."""


class InvalidAudio(Exception):
    """The service couldn't decode the audio."""


def is_configured() -> bool:
    return config.SPEECH_URL is not None


async def transcribe(audio: bytes) -> str:
    """The words in the audio, lowercase; "" if none were understood."""
    if not is_configured():
        raise SpeechUnavailable("SPEECH_URL is not set")

    headers = {"Authorization": f"Bearer {config.SPEECH_TOKEN}"} if config.SPEECH_TOKEN else {}
    url = config.SPEECH_URL.rstrip("/") + "/transcribe"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            response = await client.post(url, content=audio, headers=headers)
    except httpx.HTTPError as e:
        raise SpeechUnavailable(f"{type(e).__name__}: {e}") from e

    if response.status_code == 400:
        raise InvalidAudio(response.json().get("detail", "Invalid audio"))
    if response.status_code != 200:
        raise SpeechUnavailable(f"HTTP {response.status_code}: {response.text[:200]}")
    return response.json().get("text", "").strip()
