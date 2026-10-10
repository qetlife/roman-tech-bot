# Roman Tech Bot

A Telegram bot built with `python-telegram-bot` and SQLAlchemy.

The bot currently provides an inline-button menu UI, basic settings actions, and creates/loads a user record in a PostgreSQL database when `/start` is used.

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
- PostgreSQL (via psycopg 3)
- `python-dotenv`

## Project Structure

- `bot.py` - app entrypoint, handlers, polling
- `commands/` - slash command handlers
- `menu/` - callback action handlers and inline submenu builders
- `helpers/chat_helper.py` - `render_menu` in-place message edit/send helper
- `models/user.py` - SQLAlchemy models
- `db/db.py` - DB engine/session setup
- `db/repository/user_repository.py` - user repository methods
- `scripts/migrate_sqlite_to_postgres.py` - one-off copy of legacy SQLite data into PostgreSQL

## Environment Variables

Copy `.env.example` to `.env` (gitignored, never commit it) and fill it in:

```env
BOT_TOKEN=<your telegram bot token>
DB_CONNECTION=postgresql+psycopg://<user>:<password>@<host>:<port>/<database>
```

`DB_CONNECTION` is a SQLAlchemy URL and must use the `postgresql+psycopg://`
scheme. Plain `postgresql://` makes SQLAlchemy look for psycopg2, which is not
installed. UUID primary keys are generated in Python, so no PostgreSQL
extensions are required. (A `sqlite:///...` URL still works for quick local
experiments.)

## Database Prerequisites

The database and its user must exist already, e.g.:

```sql
CREATE USER roman_tech_bot WITH PASSWORD '<password>';
CREATE DATABASE roman_tech_bot OWNER roman_tech_bot;
```

Tables are created automatically on startup via `init_db()` in `bot.py`.

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

`docker-compose.yml` runs the bot and reads `BOT_TOKEN` and `DB_CONNECTION`
from the shell or from `.env` next to the compose file. The bot joins the
external Docker network `shared-network`, where the PostgreSQL container
`postgres` runs, so the production URL is:

```env
DB_CONNECTION=postgresql+psycopg://roman_tech_bot:<password>@postgres:5432/roman_tech_bot
```

The network must already exist (`docker network create shared-network` if
not). Then:

```bash
docker compose up -d --build
```

The `bot-data` volume (mounted at `/app/data`) is still attached so the legacy
SQLite file `/app/data/bot.db` stays available for the migration below.

## Deploying / Migrating from SQLite

On the Raspberry Pi:

```bash
cd /home/apps/roman-tech-bot && git pull
echo 'DB_CONNECTION=postgresql+psycopg://roman_tech_bot:<password>@postgres:5432/roman_tech_bot' >> .env
docker compose up -d --build
docker compose exec bot python scripts/migrate_sqlite_to_postgres.py sqlite:////app/data/bot.db "$DB_CONNECTION"
```

The script creates the tables, copies every model table with its primary keys,
resets integer id sequences, and prints source/target row counts. If the target
URL argument is empty (on the host, `"$DB_CONNECTION"` usually is, since `.env`
is not exported), it uses `DB_CONNECTION` from the container's environment.

It is safe to re-run: if any target table already has rows, it copies nothing
and exits with an error. Note that a user who sends `/start` between
`docker compose up` and the migration creates a row, which makes the migration
refuse. To avoid that, run the migration before starting the bot:

```bash
docker compose build
docker compose run --rm bot python scripts/migrate_sqlite_to_postgres.py sqlite:////app/data/bot.db
docker compose up -d
```

## Deployment

Every push to `master` auto-deploys to the Raspberry Pi via the
`.github/workflows/deploy.yml` workflow, which runs on a self-hosted runner
(label `roman-tech-bot`) on the Pi. It resets `/home/apps/roman-tech-bot` to
`origin/master`, runs `docker compose up -d --build`, and fails if the `bot`
container is not running afterwards. The untracked `.env` there is left
untouched.

To redeploy manually: **Actions → Deploy → Run workflow**.

## Notes

- The reminders flow is currently a placeholder text response.
- Error handling/logging is minimal in some paths (for example in `/start`).
- There is no schema migration tool configured yet; tables are created on startup via `init_db()` (suitable for the current simple schema). `init_db()` does not alter existing tables.
- Once the SQLite data is migrated and verified, the `bot-data` volume can be dropped from `docker-compose.yml`.
