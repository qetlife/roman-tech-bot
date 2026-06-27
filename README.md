# Roman Tech Bot

A Telegram bot built with `python-telegram-bot` and SQLAlchemy.

The bot currently provides an inline-button menu UI, basic settings actions, and creates/loads a user record in a SQL database (SQLite by default, PostgreSQL also supported) when `/start` is used.

## Current Features

- `/start`
- `/menu`
- Inline main menu buttons (callback-based navigation):
  - `⏰ Reminders` (placeholder response)
  - `⚙️ Settings`
- Settings submenu:
  - `🆔 My ID`
  - `↩️ Back`
- Persistent user registration by `telegram_id` on first `/start`
- Single-message menu UX (the menu message is edited in place as you navigate)

## Tech Stack

- Python 3
- `python-telegram-bot`
- SQLAlchemy
- SQLite (default) / PostgreSQL
- `python-dotenv`

## Project Structure

- `bot.py` - app entrypoint, handlers, polling
- `commands/` - slash command handlers
- `menu/` - callback action handlers and inline submenu builders
- `helpers/chat_helper.py` - `render_menu` in-place message edit/send helper
- `models/user.py` - SQLAlchemy models
- `db/db.py` - DB engine/session setup
- `db/repository/user_repository.py` - user repository methods

## Environment Variables

Create a `.env` file with:

```env
BOT_TOKEN=<your telegram bot token>

# SQLite (default) — a local file:
DB_CONNECTION=sqlite:///data/bot.db

# ...or PostgreSQL:
# DB_CONNECTION=postgresql+psycopg://<user>:<password>@<host>:<port>/<database>
```

`DB_CONNECTION` is any SQLAlchemy URL. The application is database-agnostic:
UUID primary keys are generated in Python, so no PostgreSQL-specific extensions
are required.

## Database Prerequisites

Tables are created automatically on startup via `init_db()` in `bot.py`, so no
manual schema setup is needed for either SQLite or PostgreSQL.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Stop virtualenv:

```bash
deactivate
```

## Docker

Build the image:

```bash
docker build -t roman-tech-bot .
```

Run the bot (passing the required environment variables):

```bash
docker run --rm \
  -e BOT_TOKEN=<your telegram bot token> \
  -e DB_CONNECTION=postgresql+psycopg://<user>:<password>@<host>:<port>/<database> \
  roman-tech-bot
```

You can also load the variables from a `.env` file:

```bash
docker run --rm --env-file .env roman-tech-bot
```

## Docker Compose

`docker-compose.yml` runs the bot with a SQLite database stored on a persistent
named volume (`bot-data`, mounted at `/app/data`). The SQLite file lives at
`/app/data/bot.db` inside the container and survives restarts and rebuilds.

Provide the bot token (via your shell or a `.env` file) and start it:

```bash
BOT_TOKEN=<your telegram bot token> docker compose up --build
```

`DB_CONNECTION` is already set to `sqlite:///data/bot.db` in the compose file,
so only `BOT_TOKEN` is required. The SQLite file is the only state, so there is
no separate database container to manage. To wipe the database, remove the
volume with `docker compose down -v`.

## Notes

- The reminders flow is currently a placeholder text response.
- Error handling/logging is minimal in some paths (for example in `/start`).
- There is no migration tool configured yet; tables are created on startup via `init_db()` (suitable for the current simple schema).
