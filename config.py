"""Settings from the environment (or a .env file next to the code)."""

import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
# SQLAlchemy URL, e.g. postgresql+psycopg://user:password@host:5432/db
DB_CONNECTION = os.environ.get("DB_CONNECTION")
# speech-service for voice messages, e.g. http://speech:8000 (unset: voice is off)
SPEECH_URL = os.environ.get("SPEECH_URL") or None
# Only if the speech-service has API_TOKEN set
SPEECH_TOKEN = os.environ.get("SPEECH_TOKEN") or None
