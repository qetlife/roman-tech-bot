"""Settings from the environment (or a .env file next to the code)."""

import logging
import os

from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
# SQLAlchemy URL, e.g. postgresql+psycopg://user:password@host:5432/db
DB_CONNECTION = os.environ.get("DB_CONNECTION")
# speech-service for voice messages, e.g. http://speech:8000 (unset: voice is off)
SPEECH_URL = os.environ.get("SPEECH_URL") or None
# Only if the speech-service has API_TOKEN set
SPEECH_TOKEN = os.environ.get("SPEECH_TOKEN") or None
# Telegram user ID of the admin, who can see /failed (unset: nobody)
ADMIN_TELEGRAM_ID = int(os.environ.get("ADMIN_TELEGRAM_ID") or 0) or None

# Google Calendar sync (unset GOOGLE_CLIENT_ID: off). The OAuth client of the
# Google Cloud project, and where Google sends the user back after linking.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID") or None
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET") or None
# e.g. https://calendar.romanis.xyz/oauth/callback; push notifications go to /google/push on the same host
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI") or None
# Encrypts the Google logins in the database and signs the link state
# (a Fernet key; generate with: openssl rand -base64 32 | tr '+/' '-_')
CALENDAR_KEY = os.environ.get("CALENDAR_KEY") or None
# Port of the bot's small web server (OAuth callback, push notifications), inside the container
WEB_PORT = int(os.environ.get("WEB_PORT") or 8080)


def calendar_configured() -> bool:
    """Whether Google Calendar sync is set up: all four settings, and CALENDAR_KEY a valid key."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI and CALENDAR_KEY) \
        and _valid_key(CALENDAR_KEY)


@lru_cache(maxsize=4)
def _valid_key(key: str) -> bool:
    # A wrong key would make every stored login unreadable (all "expired"): rather off, and said once
    from cryptography.fernet import Fernet
    try:
        Fernet(key.encode())
    except ValueError:
        logging.getLogger(__name__).error("CALENDAR_KEY isn't a valid key (32 bytes, URL-safe base64): "
                                          "Google Calendar is off")
        return False
    return True
