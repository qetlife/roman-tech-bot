"""Settings from the environment (or a .env file next to the code)."""

import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
# SQLAlchemy URL, e.g. postgresql+psycopg://user:password@host:5432/db
DB_CONNECTION = os.environ.get("DB_CONNECTION")
