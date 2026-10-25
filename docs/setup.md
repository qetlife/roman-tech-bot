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
- [Google Calendar](#google-calendar)
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
# Optional: Google Calendar sync, all four (see Google Calendar below)
GOOGLE_CLIENT_ID=<…>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<…>
GOOGLE_REDIRECT_URI=https://calendar.romanis.xyz/oauth/callback
CALENDAR_KEY=<a Fernet key>
```

| Variable            | Required | What it does |
| ------------------- | -------- | ------------ |
| `BOT_TOKEN`         | yes      | Telegram bot token |
| `DB_CONNECTION`     | yes      | SQLAlchemy URL. Must use `postgresql+psycopg://` (psycopg 3); plain `postgresql://` makes SQLAlchemy look for psycopg2, which isn't installed |
| `SPEECH_URL`        | no       | speech-service URL. Unset: voice messages are off (the bot says they aren't set up) |
| `SPEECH_TOKEN`      | no       | Only if the speech-service has `API_TOKEN` set |
| `ADMIN_TELEGRAM_ID` | no       | The only user who can list [failed messages](user-guide.md#when-the-bot-gets-it-wrong) with `/failed`. Unset: `/failed` is off |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | no | The OAuth client of the Google Cloud project ([Google Calendar](#google-calendar)). Unset: no 📅 Calendar sync, no web server |
| `GOOGLE_REDIRECT_URI` | no     | Where Google sends the user back after linking, e.g. `https://calendar.romanis.xyz/oauth/callback`. Push notifications go to `/google/push` on the same host (HTTPS only) |
| `CALENDAR_KEY`      | no       | Encrypts the Google logins in the database and signs the link. A Fernet key; changing it unlinks everyone |
| `WEB_PORT`          | no       | Port of the bot's web server inside the container (default `8080`) |

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
python -m pyflakes bot.py config.py enums.py core db handlers jobs scripts services tests autofix
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
[failed messages](development.md#failed-messages), Claude Code fixes the
ones it can, following `autofix/prompt.md`. The job then opens one pull
request (label `autofix`), has Claude answer the automatic review (up to
two rounds), marks the ones that need a new feature as waiting for it,
and ignores the ones that can't be learned. Comments you
leave on an auto-fix pull request are answered on the next run. Merging is
the only manual step; after the deploy the bot closes the messages it now
understands.

It needs two repository secrets:

| Secret | What |
| --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | the same as the review |
| `AUTOFIX_GH_TOKEN` | a fine-grained personal access token for this repository only: **Contents** and **Pull requests** read and write. Without the Workflows permission it can't change `.github/workflows/` |

**Claude never has the GitHub token.** It runs in a sandbox container
(`autofix/Dockerfile`: no Docker socket, only a temporary folder) on an
anonymous clone of this public repository, and hands back its commits as a
git bundle. A separate container with the token, which runs neither Claude
nor any code from the repository, fetches the bundle into a fresh clone,
pushes the branch and opens the pull request. So nothing Claude writes or
runs (its tests, say) can push or merge. Protect `master` with
a ruleset that requires a pull request anyway (Settings → Rules).

Create the `autofix` label once (`gh label create autofix`): the job finds
its pull requests by it.

Only the admin's failed messages are used (anyone can message the bot), and
only comments from the owner and the automatic review: anyone can comment
on a public repository.

**What's left, accepted:** the sandbox has network access (Claude needs its
API), and it holds the failed messages and the Claude token. Code Claude
runs there, like its tests, could send them somewhere. For that, Claude
would have to be talked into it through its input. The only inputs are the
admin's own messages, the owner's comments and the automatic review, so the
risk is accepted. Closing it entirely would need the sandbox offline behind
a proxy that only reaches the Claude API.

The failed messages are private and the repository is public: the job never
prints them to the Actions log (Claude's output goes to `~/autofix-logs/`
on the Pi), and the prompt forbids putting their text in code, tests,
commits or pull requests. The job checks too, before anything goes public: commits
that contain four words in a row from an open failed message, two of them
not common words (the phrasing, “remind me to … at 9”, is fine to copy), aren't
pushed, and a title, description, reply or note like that is replaced
with a generic one (`leaks()` in `autofix/run.py`). Blocked commits are kept on the
Pi (`~/autofix-logs/blocked-*.diff`, with what matched; the folder is
readable by the job's user only, and the last 30 of each kind are kept), and their messages
wait (“a fix was blocked by the privacy check”) until a person looks.

## Google Calendar

Optional: syncs events both ways with Google Calendar
([user guide](user-guide.md#-google-calendar),
[how it works](development.md#google-calendar)). It needs a Google Cloud
project, four environment variables, and a public HTTPS address for the
bot's small web server (Google sends users back to it after linking, and
pushes changes to it): on the Pi, a route in the Cloudflare Tunnel. Until all four variables are set, it's off and the
web server doesn't start.

### 1. Google Cloud

In [console.cloud.google.com](https://console.cloud.google.com), with the
Google account that will own the project:

1. **New project** (e.g. `roman-tech-bot`), and select it.
2. **APIs & Services → Library → Google Calendar API → Enable**.
3. **Google Auth Platform** (formerly *OAuth consent screen*) → **Get
   started**: app name, support email, audience **External**, contact email.
4. **Audience → Test users**: add the Google accounts that may link. The app
   stays in **Testing** until it's published (privacy policy, verification).
   While in testing, only test users can link, and Google expires a login
   after 7 days: the bot then warns the user and asks them to link again.
5. **Data access → Add or remove scopes**: exactly these two:
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
6. **Clients → Create client → Web application**, with the authorized
   redirect URI `https://calendar.romanis.xyz/oauth/callback`. Keep the client
   ID and secret (never in the repository: it's public).

### 2. The environment

In `/home/apps/roman-tech-bot/.env` on the Pi:

```env
GOOGLE_CLIENT_ID=<…>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<…>
GOOGLE_REDIRECT_URI=https://calendar.romanis.xyz/oauth/callback
CALENDAR_KEY=<output of the command below>
```

```bash
# 32 random bytes, URL-safe base64: what Fernet.generate_key() makes
openssl rand -base64 32 | tr '+/' '-_'
```

Generate `CALENDAR_KEY` once and keep it: the stored Google logins can only
be read with it (a new key means everyone links again). If it isn't a valid
key, the log says `CALENDAR_KEY isn't a valid key` and Google Calendar stays
off. Then
`docker compose up -d` (a restart doesn't read `.env`). The log says
`Web server for Google Calendar on port 8080`.

### 3. `calendar.romanis.xyz` → the bot

The bot's web server listens on port 8080 in its container, which answers
to `roman-tech-bot` on `shared-network` (an alias in `docker-compose.yml`).
It isn't published on the Pi. Only three paths are served:
`GET /oauth/callback`, `POST /google/push` and `GET /health`; everything
else on the host should be a 404.

**Cloudflare Tunnel** (how `romanis.xyz` is served): the `cloudflared`
container is on `shared-network` and sends traffic straight to containers.
The tunnel is managed remotely, so its rules are in the Cloudflare dashboard
(Zero Trust → Networks → Tunnels → the tunnel → Published application
routes / Public hostnames), not in a file. Add two routes:

| Hostname | Path | Service |
| --- | --- | --- |
| `calendar.romanis.xyz` | `^/(oauth/callback\|google/push\|health)$` | `http://roman-tech-bot:8080` |
| `calendar.romanis.xyz` | (none) | `http_status:404` |

- The dashboard has no separate service-type field: the protocol is part
  of the URL (`http://`), and `http_status:404` is a service of its own.
- New routes are added at the bottom, and the first matching one wins: move
  both above any `*.romanis.xyz` wildcard, or the wildcard catches them.
- The tunnel creates the DNS record, and HTTPS comes from Cloudflare's edge.
- Nothing to restart: a remotely managed tunnel picks up the change.

**Without a tunnel** (Nginx in front, e.g. on another server): a server block
for `calendar.romanis.xyz` that sends only those three paths to the bot and
404s the rest. If Nginx runs in a container on `shared-network`, it reaches
`http://roman-tech-bot:8080`; if it runs on the host, publish the port in
`docker-compose.yml` first (`ports: ["127.0.0.1:8095:8080"]`) and use
`http://127.0.0.1:8095`. Google's push notifications need valid HTTPS
(Cloudflare's proxy, with an origin certificate under **Full (strict)**).

```nginx
server {
    listen 80;
    server_name calendar.romanis.xyz;

    location ~ ^/(oauth/callback|google/push|health)$ {
        proxy_pass http://roman-tech-bot:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    location / {
        return 404;
    }
}
```

**Check it**, once the bot runs with the four variables (before that, the
three paths give a 502):

- The bot's log says `Web server for Google Calendar on port 8080`.
- `curl -s https://calendar.romanis.xyz/health` prints `ok`; `/` and other
  paths give a 404.
- `https://calendar.romanis.xyz/oauth/callback` in a browser shows "This
  page is for linking Google Calendar from the bot."
- In Telegram: ⚙️ Settings → 📅 Calendar → 🔗 Link Google Calendar, as a
  test user. The bot says "✅ Google Calendar linked."

## Migrating from SQLite

The bot originally stored its data in a SQLite file. That data has been
migrated to PostgreSQL. `scripts/migrate_sqlite_to_postgres.py` is kept for
reference: it copies every model table from a SQLite file into PostgreSQL
(refusing if the target already has rows):

```bash
python scripts/migrate_sqlite_to_postgres.py sqlite:////path/to/bot.db "$DB_CONNECTION"
```
