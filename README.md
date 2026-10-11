# Roman Tech Bot

A Telegram bot built with `python-telegram-bot` and SQLAlchemy.

The bot currently provides an inline-button menu UI, basic settings actions, and creates/loads a user record in a PostgreSQL database when `/start` is used.

## Current Features

- `/start`, `/menu`
- Inline main menu: `⏰ Reminders`, `⚙️ Settings` (`🆔 My ID`, `🌍 Timezone`, `⏰ Reminders` → `💤 Snooze options`, `🔁 Repeat interval`)
- Reminder settings are also reachable from `⏰ Reminders → ⚙️ Settings`
- Persistent user registration by `telegram_id` on first `/start`
- Single-message menu UX (the menu message is edited in place as you navigate)
- Reminders (see below)

## Reminders

Create a reminder by typing in a private chat with the bot, or via
`⏰ Reminders → ➕ New`:

- “remind me in 2 hours to call mom”
- “set a reminder for tomorrow at 9: pay rent”
- “remind me to stretch at 18:30”
- “remind me every day at 9 to take pills”
- “remind me on weekdays at 8:30: standup” (also “every monday and
  thursday”, “every weekend”, “mondays”, “every evening at 7”)

The bot confirms with the parsed time and `↩️ Undo` / `✏️ Edit` buttons.
“my reminders” (or `📋 My reminders`) lists upcoming reminders with `❌` to
cancel. The first reminder asks for your timezone (changeable under
`⚙️ Settings → 🌍 Timezone`).

When a reminder is due the bot sends it with `✅ OK` and snooze buttons
(`💤 10 min`, `💤 1 h` by default; up to 3 options of your choice under
`⚙️ Settings → ⏰ Reminders → 💤 Snooze options`). Until OK is pressed it is re-sent every 5 minutes (changeable under
`⚙️ Settings → ⏰ Reminders → 🔁 Repeat interval`; the previous copy is deleted), and after 24 hours without a response it is marked missed.
Only the reminder's owner can press its buttons.

Recurring reminders work the same way; pressing OK (or not answering before
the next occurrence or within 24 hours) moves them on to the next occurrence.
Cancelling one cancels the whole series. Their time stays in local time, so
“every day at 9” is 09:00 across DST changes.

How it works:

- `intents/registry.py` maps trigger phrases (“remind me”, “set a reminder”,
  “my reminders”, …) to actions. A message that starts with a phrase runs
  that action with the rest of the message. Add phrases or new actions there.
- `reminders/parser.py` turns the rest (“in 2 hours to call mom”) into a time
  and a text. It understands a fixed set of English time expressions (see the
  module docstring) and asks the user to rephrase anything else.
- Reminders are stored in the `reminders` table (times in UTC). A job runs
  every 20 seconds (`reminders/delivery.py`) and sends whatever is due, so
  reminders survive restarts and deploys; anything that came due while the
  bot was down is sent on startup.

## Settings

Per-user settings are defined in code in `settings/registry.py` (key,
default, validation, label). The `user_settings` table stores only the values
a user changed, so adding a setting needs a registry entry and a Settings
screen, but no migration. `SettingsRepository` returns the user's value or the
default.

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
- `models/` - SQLAlchemy models
- `db/db.py` - DB engine/session setup
- `db/migrations.py` - runs Alembic migrations on startup
- `alembic/` - schema migrations (`alembic.ini` at the repo root)
- `db/repository/user_repository.py` - user repository methods
- `db/repository/reminder_repository.py` - reminder repository methods
- `db/repository/settings_repository.py` - per-user settings (value or default)
- `settings/` - settings registry and Settings screens
- `intents/` - trigger phrase → action mapping for free-text messages
- `reminders/` - reminder parsing, handlers and the delivery job
- `tests/` - tests (`pip install -r requirements-dev.txt && pytest`; they use a throwaway SQLite database)
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

The schema is managed by Alembic migrations, which run automatically on
startup (`init_db()` in `bot.py`). See [Database Migrations](#database-migrations).

## Database Migrations

The schema lives in the SQLAlchemy models (`models/`) and in versioned
migrations under `alembic/versions/`. On every startup the bot runs
`alembic upgrade head`, so merging a migration to `master` applies it on the
next deploy.

To change the schema:

1. Edit or add a model in `models/`. New model modules must also be imported
   in `alembic/env.py` so autogenerate sees them.
2. Generate a migration against a database that is at the latest revision:

   ```bash
   alembic revision --autogenerate -m "add reminders table"
   ```

3. Review the generated file in `alembic/versions/`. Autogenerate does not
   detect everything (e.g. column renames show up as drop + add, which loses
   data), so fix it by hand where needed.
4. Commit it together with the model change.

Other useful commands (they read `DB_CONNECTION` from the environment / `.env`):

```bash
alembic current        # revision the database is at
alembic history        # list migrations
alembic check          # fail if the models differ from the database
alembic downgrade -1   # undo the last migration
```

On the Pi, run them inside the container, e.g.
`docker compose exec bot alembic current`.

Databases created before Alembic was added (which already have the `users`
table but no `alembic_version` table) are stamped at the baseline revision
`0001` on first startup rather than recreated.

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

## Migrating from SQLite

The bot originally stored its data in a SQLite file. That data has been
migrated to PostgreSQL and the SQLite volume removed.
`scripts/migrate_sqlite_to_postgres.py` is kept for reference: it copies every
model table from a SQLite file into PostgreSQL (refusing if the target already
has rows), e.g.

```bash
python scripts/migrate_sqlite_to_postgres.py sqlite:////path/to/bot.db "$DB_CONNECTION"
```

## Deployment

Every push to `master` runs the tests and, if they pass, auto-deploys to the
Raspberry Pi via the `.github/workflows/deploy.yml` workflow:

1. `test` runs `pytest` on a GitHub-hosted runner (`.github/workflows/tests.yml`).
2. `deploy` runs only if the tests pass, on a self-hosted runner (label
   `roman-tech-bot`) on the Pi. It resets `/home/apps/roman-tech-bot` to the
   tested commit, runs `docker compose up -d --build`, and fails if the `bot`
   container is not running afterwards. The untracked `.env` there is left
   untouched.

If the tests fail, nothing is deployed and the previous version keeps running.
The same tests also run on every pull request, so failures show up before
merging.

To redeploy manually: **Actions → Deploy → Run workflow**.

## Notes

- Error handling/logging is minimal in some paths (for example in `/start`).
