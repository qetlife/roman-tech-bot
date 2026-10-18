# Setup and deployment

How to run the bot locally, configure it, change the database schema and
deploy it. For what the bot does, see the [user guide](user-guide.md); for
how the code works, see the [development guide](development.md).

- [Requirements](#requirements)
- [Environment variables](#environment-variables)
- [Running locally](#running-locally)
- [Docker](#docker)
- [Database migrations](#database-migrations)
- [Deployment](#deployment)
- [Migrating from SQLite](#migrating-from-sqlite)

## Requirements

- Python 3.12 (same as the Docker image)
- PostgreSQL (SQLite works for local experiments and is what the tests use)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Optional: [speech-service](https://github.com/qetlife/speech-service) for
  voice messages

## Environment variables

Copy `.env.example` to `.env` (gitignored, never commit it) and fill it in:

```env
BOT_TOKEN=<your telegram bot token>
DB_CONNECTION=postgresql+psycopg://<user>:<password>@<host>:<port>/<database>
# Optional: voice messages (https://github.com/qetlife/speech-service)
SPEECH_URL=http://speech:8000
# SPEECH_TOKEN=<only if the speech-service has API_TOKEN set>
# Optional: your Telegram user ID; only this user can use /failed
ADMIN_TELEGRAM_ID=<your telegram user id>
```

| Variable            | Required | What it does |
| ------------------- | -------- | ------------ |
| `BOT_TOKEN`         | yes      | Telegram bot token |
| `DB_CONNECTION`     | yes      | SQLAlchemy URL. Must use `postgresql+psycopg://` (psycopg 3); plain `postgresql://` makes SQLAlchemy look for psycopg2, which isn't installed |
| `SPEECH_URL`        | no       | speech-service URL. Unset: voice messages are off (the bot says they aren't set up) |
| `SPEECH_TOKEN`      | no       | Only if the speech-service has `API_TOKEN` set |
| `ADMIN_TELEGRAM_ID` | no       | The only user who can list [failed messages](user-guide.md#when-the-bot-gets-it-wrong) with `/failed`. Unset: `/failed` is off |

Everything else works without the optional ones.

> [!IMPORTANT]
> A container only reads `.env` when it is created. After changing `.env`,
> run `docker compose up -d` so the bot picks up the new values; a restart
> isn't enough.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python bot.py
```

Migrations run automatically on startup. To run the checks CI runs:

```bash
python -m pyflakes bot.py config.py enums.py core db handlers jobs scripts services tests
pytest
```

Tests use a throwaway SQLite database, never the one in `.env`.

## Docker

Build and run the image:

```bash
docker build -t roman-tech-bot .
docker run --rm --env-file .env roman-tech-bot
```

`docker-compose.yml` runs the bot with the variables from the shell or from
`.env` next to the compose file. The bot joins the external Docker network
`shared-network`, where the PostgreSQL container `postgres` runs, so the
production URL is:

```env
DB_CONNECTION=postgresql+psycopg://roman_tech_bot:<password>@postgres:5432/roman_tech_bot
```

The network must already exist (`docker network create shared-network` if
not). Then:

```bash
docker compose up -d --build
```

## Database migrations

The schema lives in the SQLAlchemy models (`db/models/`) and in versioned
migrations under `alembic/versions/`. On every startup the bot runs
`alembic upgrade head`, so merging a migration to `master` applies it on the
next deploy.

To change the schema:

1. Edit or add a model in `db/models/`. New model modules must also be
   imported in `alembic/env.py` so autogenerate sees them.
2. Generate a migration against a database that is at the latest revision:

   ```bash
   alembic revision --autogenerate -m "add reminders table"
   ```

3. Review the generated file in `alembic/versions/`. Autogenerate doesn't
   detect everything (e.g. column renames show up as drop + add, which loses
   data), so fix it by hand where needed.
4. Commit it together with the model change.

Other useful commands (they read `DB_CONNECTION` from the environment or
`.env`):

```bash
alembic current        # revision the database is at
alembic history        # list migrations
alembic check          # fail if the models differ from the database
alembic downgrade -1   # undo the last migration
```

On the server, run them inside the container, e.g.
`docker compose exec bot alembic current`.

Databases created before Alembic was added (which already have the `users`
table but no `alembic_version` table) are stamped at the baseline revision
`0001` on first startup rather than recreated.

## Deployment

Every push to `master` runs the tests and, if they pass, deploys to the
Raspberry Pi (`.github/workflows/deploy.yml`):

1. `test` runs pyflakes and pytest on a GitHub-hosted runner
   (`.github/workflows/tests.yml`).
2. `deploy` runs only if the tests pass, on a self-hosted runner (label
   `roman-tech-bot`) on the Pi. It resets `/home/apps/roman-tech-bot` to the
   tested commit, runs `docker compose up -d --build`, and fails if the `bot`
   container isn't running afterwards. The untracked `.env` there is left
   untouched.

If the tests fail, nothing is deployed and the previous version keeps
running. The same tests run on every pull request, so failures show up
before merging.

To redeploy manually: **Actions → Deploy → Run workflow**.

### Code review

Claude reviews every pull request (`.github/workflows/review.yml`) and
leaves inline comments on problems it finds, plus a one-line summary. It
runs on a GitHub-hosted runner, re-reviews on each push, and skips drafts
and pull requests from forks. It needs the repository secret
`CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, which uses a Claude
subscription). The review is advice, not a required check.

### Auto-fix job

Every day at 03:00 UTC, `.github/workflows/autofix.yml` runs
`autofix/run.py` on the Pi's runner (also **Actions → Auto-fix failed
messages → Run workflow**). If the admin has new open
[failed messages](development.md#failed-messages), it runs Claude Code in a
sandbox container (`autofix/Dockerfile`: no Docker socket, only a temporary
folder) with `autofix/prompt.md`. Claude opens one pull request (label
`autofix`) with parser fixes and tests, answers the automatic review, and
ignores messages that can't be learned. Merging is the only manual step;
after the deploy the bot closes the messages it now understands.

It needs two repository secrets:

| Secret | What |
| --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | the same as the review |
| `AUTOFIX_GH_TOKEN` | a fine-grained personal access token for this repository only: **Contents** and **Pull requests** read and write. Without the Workflows permission it can't change `.github/workflows/` |

Protect `master` with a ruleset that requires a pull request (Settings →
Rules), so the token can push branches but never deploy by itself.

The failed messages are private and the repository is public: the job never
prints them to the Actions log (Claude's output goes to `~/autofix-logs/`
on the Pi), and the prompt forbids putting their text in code, tests,
commits or pull requests. Only the admin's messages are used (anyone can
message the bot, and their text reaches Claude).

## Migrating from SQLite

The bot originally stored its data in a SQLite file. That data has been
migrated to PostgreSQL. `scripts/migrate_sqlite_to_postgres.py` is kept for
reference: it copies every model table from a SQLite file into PostgreSQL
(refusing if the target already has rows):

```bash
python scripts/migrate_sqlite_to_postgres.py sqlite:////path/to/bot.db "$DB_CONNECTION"
```
