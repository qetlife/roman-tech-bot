# Roman Tech Bot

A Telegram bot built with `python-telegram-bot` and SQLAlchemy.

The bot currently provides an inline-button menu UI, basic settings actions, and creates/loads a user record in PostgreSQL when `/start` is used.

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
- PostgreSQL
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
DB_CONNECTION=postgresql+psycopg://<user>:<password>@<host>:<port>/<database>
```

## Database Prerequisites

The `users.id` column uses `gen_random_uuid()`, so PostgreSQL needs `pgcrypto` enabled.

Example SQL:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_id BIGINT UNIQUE NOT NULL
);
```

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

## Notes

- The reminders flow is currently a placeholder text response.
- Error handling/logging is minimal in some paths (for example in `/start`).
- There is no migration tool configured yet (table creation is expected outside the app).
