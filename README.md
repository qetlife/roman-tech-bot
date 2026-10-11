# Roman Tech Bot

A personal assistant Telegram bot built with `python-telegram-bot`,
SQLAlchemy and PostgreSQL, running on a Raspberry Pi.

- **[User guide](docs/user-guide.md)**: everything the bot can do and how to
  use every setting.
- **[Development guide](docs/development.md)**: how it works and how to
  extend it.
- **[Plan](plan.md)**: what's done and what's next.

## Features

- **Menus**: `/start` and `/menu` open an inline-button menu that updates in
  place: `⏰ Reminders` and `⚙️ Settings`.
- **Reminders by typing or voice**: “remind me in 2 hours to call mom”,
  “remind me tomorrow at 9 to pay rent”, or `⏰ Reminders → ➕ New`. Natural
  English times: relative, clock times, weekdays, dates, parts of the day,
  numbers as words (“at half past six”, “in twenty five minutes”).
- **Voice messages**: say anything you could type; transcribed offline by
  [speech-service](https://github.com/qetlife/speech-service) (Vosk) on the
  Pi, never sent to a third party.
- **Recurring reminders**: daily, weekdays/weekends, certain weekdays
  (“every mon and thu”), every N minutes/hours/days/weeks (“every 2 hours”),
  and monthly (“on the 1st of every month”).
- **Delivery until acknowledged**: `✅ OK` and snooze buttons; unanswered
  reminders are re-sent until OK, and marked missed after 24 hours.
- **Manage reminders**: list upcoming ones (“my reminders”), `↩️ Undo`,
  `✏️ Edit` and `❌` cancel.
- **Settings**: `🆔 My ID`, `🌍 Timezone`, and reminder settings (also under
  `⏰ Reminders → ⚙️ Settings`): `💤 Snooze options`, `🔁 Repeat interval`,
  `🌙 Quiet hours` (default 00:00–07:00).
- **Reliable**: reminders are stored in the database and survive restarts;
  anything due while the bot was down is sent when it is back.

See the [user guide](docs/user-guide.md) for details and all supported
phrases.

## Tech Stack

- Python 3
- `python-telegram-bot`
- SQLAlchemy
- PostgreSQL (via psycopg 3)
- `python-dotenv`

## Project Structure

```
bot.py          entry point: handlers, delivery job, polling
config.py       environment variables
enums.py        every enum
handlers/       everything that talks to Telegram (commands, menus, reminders, settings, typed text)
core/           the logic, no Telegram or database (parser, recurrence, quiet hours, timezones, settings)
jobs/           the reminder delivery job
services/       clients for other services (speech-service for voice messages)
db/             session, migrations runner, models/, repositories/
alembic/        schema migrations (alembic.ini at the repo root)
docs/           user guide and development guide
scripts/        one-off scripts (migrate_sqlite_to_postgres.py)
tests/          pytest (pip install -r requirements-dev.txt && pytest; throwaway SQLite database)
```

See the [development guide](docs/development.md#architecture) for what each
file does.

## Environment Variables

Copy `.env.example` to `.env` (gitignored, never commit it) and fill it in:

```env
BOT_TOKEN=<your telegram bot token>
DB_CONNECTION=postgresql+psycopg://<user>:<password>@<host>:<port>/<database>
# Optional: voice messages (https://github.com/qetlife/speech-service)
SPEECH_URL=http://speech:8000
# SPEECH_TOKEN=<only if the speech-service has API_TOKEN set>
```

Without `SPEECH_URL`, voice messages are off (the bot replies that they
aren't set up); everything else works.

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

The schema lives in the SQLAlchemy models (`db/models/`) and in versioned
migrations under `alembic/versions/`. On every startup the bot runs
`alembic upgrade head`, so merging a migration to `master` applies it on the
next deploy.

To change the schema:

1. Edit or add a model in `db/models/`. New model modules must also be imported
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

1. `test` runs `pyflakes` and `pytest` on a GitHub-hosted runner (`.github/workflows/tests.yml`).
2. `deploy` runs only if the tests pass, on a self-hosted runner (label
   `roman-tech-bot`) on the Pi. It resets `/home/apps/roman-tech-bot` to the
   tested commit, runs `docker compose up -d --build`, and fails if the `bot`
   container is not running afterwards. The untracked `.env` there is left
   untouched.

If the tests fail, nothing is deployed and the previous version keeps running.
The same tests also run on every pull request, so failures show up before
merging.

To redeploy manually: **Actions → Deploy → Run workflow**.
