# Development guide

How the bot works and how to extend it. For what it does from a user's point
of view, see [user-guide.md](user-guide.md). For setup and deployment, see the
[README](../README.md).

- [Architecture](#architecture)
- [Messages and buttons](#messages-and-buttons)
- [Reminders](#reminders)
- [Settings](#settings)
- [Enums](#enums)
- [Database](#database)
- [Tests](#tests)
- [How to…](#how-to)
- [Keeping docs up to date](#keeping-docs-up-to-date)

## Architecture

```
bot.py              entry point: registers handlers and the delivery job, starts polling
config.py           BOT_TOKEN / DB_CONNECTION from the environment (.env)
enums.py            every enum

handlers/           everything that talks to Telegram (messages, buttons)
    commands.py     /start, /menu
    menus.py        main, ⏰ Reminders and ⚙️ Settings menu screens
    reminders.py    create, edit, list; OK / snooze / undo / edit / delete buttons
    settings.py     🌍 timezone and ⏰ reminder settings screens
    text.py         typed messages: trigger phrases, answers to questions
    intents.py      trigger phrase → handler table
    ui.py           render_menu, callback data helpers, user_data keys

core/               the logic: no Telegram, no database sessions
    parser.py       "in 2 hours to call mom" → time + text
    recurrence.py   Weekly / Monthly / Interval
    quiet.py        quiet hours
    timezones.py    resolving and formatting timezones
    settings.py     setting definitions and validation
    intents.py      trigger phrase matching

jobs/
    delivery.py     sends due reminders every 20 seconds

db/
    session.py      engine, sessions, init_db
    migrations.py   runs Alembic on startup
    models/         user, reminder, user_setting, types (UTCDateTime)
    repositories/   user, reminder, settings: the only code that opens sessions

alembic/            schema migrations
docs/               this guide and the user guide
scripts/            one-off scripts
tests/              pytest, throwaway SQLite database
```

**Dependencies go one way**: `handlers/` and `jobs/` use `core/` and `db/`;
`core/` imports neither Telegram nor the database (it's plain Python, tested
without mocks); `db/` uses only `enums` and the `Setting` type from `core/`.
The one exception is `handlers/settings.py`, which imports
`handlers.reminders.create_reminder` inside a function to resume a reminder
after the user picks a timezone (a module-level import would be circular).

`python-telegram-bot` delivers updates to the handlers registered in
`bot.py`:

- **Commands** → `handlers/commands.py`.
- **Button presses** (callback queries) → handlers matched by callback data
  (see [Messages and buttons](#messages-and-buttons)).
- **Text in private chats** → `handlers/text.on_text`.
- **Delivery job** → `jobs/delivery.deliver_due`, every 20 seconds via
  the job queue.

Repositories in `db/repositories/` are the only code that opens database
sessions. They return detached model objects (`expire_on_commit=False`).

## Messages and buttons

**Menus** are a single long-lived message: `handlers/ui.render_menu`
edits it in place, or replaces it if it can't be edited.

**Callback data** for every button is defined as enums in `enums.py`:

| Enum             | For                                    | Example                 |
| ---------------- | -------------------------------------- | ----------------------- |
| `Callback`       | buttons with fixed data                | `menu:main`, `rset:show` |
| `CallbackPrefix` | buttons that carry a value             | `tz:Europe/Kyiv`        |
| `ReminderAction` | buttons on a reminder (`rem:<action>:<id>`) | `rem:snz:5:10`     |
| `OptionAction`   | buttons on a setting screen            | `qhopt:set:23:00-07:00` |

Build data with `reminder_callback()` / `option_callback()`, read it with
`split_option()`, and register handlers with `exact(...)` / `prefixed(...)`
(all in `handlers/ui.py`).
**Never change an existing value**: buttons on messages already in users'
chats still carry it. `tests/test_callbacks.py` pins them.

**Free text** (`handlers/text.py`):

1. A message starting with a trigger phrase runs that intent's action with
   the rest of the message (`handlers/intents.py`, matched by
   `core/intents.py`; longest phrase wins, whole words only, polite filler
   like “please” allowed in front). This always wins.
2. Otherwise, if the bot asked a question, `context.user_data["awaiting"]`
   holds an `Awaiting` value (`enums.py`; keys in `handlers/ui.py`) and the message is the
   answer. For `Awaiting.EDIT`, the reminder id is in
   `user_data["edit_reminder_id"]`.
3. Otherwise the bot replies with a help text.

`user_data` lives in memory, so a restart forgets pending questions.

## Reminders

**Parsing** (`core/parser.py`): `parse_reminder(request, now)` splits
the text after the trigger phrase into a time and a text. It tries the
longest time expression at the start or the end of the message
(`parse_when` for one-offs, `parse_recurrence` for repeats) whose leftover is
not itself a time. It understands a fixed set of English expressions (module
docstring and [user guide](user-guide.md#time-expressions)) and raises
`ParseError` with a user-facing message otherwise. `now` is timezone-aware
in the user's timezone.

**Recurrence** (`core/recurrence.py`): three types, stored as a string
in `reminders.recurrence` (`NULL` = one-off):

| Type       | Stored as                       | Meaning |
| ---------- | ------------------------------- | ------- |
| `Weekly`   | `mon,tue,wed,thu,fri@08:30`     | these weekdays (`calendar.Day`) at a local time |
| `Monthly`  | `month:15@09:00`                | this day of the month (last day in shorter months) at a local time |
| `Interval` | `every:120m@2026-10-11T07:00Z`  | every N minutes from a start (UTC); whole days keep the local time |

Each has `serialize()`, `next_after(after, tz)` (first occurrence strictly
after `after`) and `describe(tz)`; `recurrence.parse()` reads a stored value.

**Lifecycle** (`ReminderStatus` in `enums.py`):

```
PENDING ──due──▶ FIRING ──OK──▶ DONE          (recurring: back to PENDING at the next occurrence)
   ▲               │  └──24 h──▶ MISSED       (recurring: back to PENDING)
   └───snooze──────┘
any active ──cancel──▶ CANCELLED      blocked by user ──▶ FAILED
```

`remind_at` is when the reminder is due (moved by snooze), `next_fire_at` is
when the delivery job should send it next (moved by repeats and quiet
hours). Both are UTC.

**Delivery** (`jobs/delivery.py`), for each active reminder whose
`next_fire_at` has passed:

1. Recurring: if a later occurrence is already due (or it has been firing
   for 24 h), mark the old message missed and advance to the latest due
   occurrence; it is sent on the next poll.
2. One-off firing for 24 h: mark `MISSED`.
3. In quiet hours: postpone repeats to the end of the window; skip
   “every N minutes/hours” occurrences to the first one after.
4. Otherwise send it with ✅ OK and snooze buttons, delete the previous copy,
   and set the next repeat (`now + repeat interval`).

**Quiet hours** (`core/quiet.py`): `is_quiet`, `quiet_end` and
`skip_quiet`. Only sub-day `Interval`s are skipped; other reminders have an
explicit time and always fire. `skip_quiet` is also applied when creating,
editing and acknowledging, so the shown next time is right.

## Settings

Each setting is a `Setting` in `core/settings.py`: a key, a default, a
`validate` function (returns the normalized value or raises `ValueError` with
a user-facing message) and a label. `SettingsRepository` returns the user's
value or the default, and falls back to the default if a stored value no
longer validates. `user_settings` stores only values that differ from the
default, as JSON, so adding a setting needs no migration.

| Key                         | Default            | Stored as           |
| --------------------------- | ------------------ | ------------------- |
| `reminders.snooze_options`  | `[10, 60]`         | sorted minutes, 1–3 values, 1–1440 |
| `reminders.repeat_minutes`  | `5`                | minutes, 1–60       |
| `reminders.quiet_hours`     | `["00:00", "07:00"]` | `[start, end]` local, `[]` = off |

The timezone is a column on `users`, not a setting.

Screens live in `handlers/settings.py`. The ⏰ Reminder settings screen
remembers where it was opened from (`user_data["reminder_settings_back"]`)
so `↩️ Back` returns there.

## Enums

Use an enum instead of loose strings for any fixed set of values. **All
enums live in `enums.py`**, so they are easy to find and change; add new
ones there too.

| Enum                                    | For |
| --------------------------------------- | --- |
| `ReminderStatus` (+ `ACTIVE_STATUSES`)  | reminder lifecycle; stored as its value in `reminders.status`, a `VARCHAR(16)` (non-native SQLAlchemy `Enum` in `db/models/reminder.py`) |
| `RepeatKind`                            | the kind of repeat the parser found |
| `Awaiting`                              | what the next typed message answers |
| `Callback`, `CallbackPrefix`, `ReminderAction`, `OptionAction` | callback data of every button |

Weekdays use the standard library's `calendar.Day` (in the parser and
`Weekly`).

`StrEnum` members compare equal to their string values, which keeps stored
data and callback data compatible.

## Database

PostgreSQL in production, SQLite in tests. Times are `UTCDateTime`
(`db/models/types.py`): timezone-aware, stored and returned in UTC. Schema
changes go through Alembic; see [Database Migrations](../README.md#database-migrations).

| Table           | Holds |
| --------------- | ----- |
| `users`         | `telegram_id`, `timezone` |
| `reminders`     | creator/target user, chat, text, `remind_at`, `next_fire_at`, `status`, `fire_count`, `last_message_id`, `recurrence` |
| `user_settings` | `(user_id, key)` → JSON value, only non-defaults |

## Tests

```bash
pip install -r requirements-dev.txt
python -m pyflakes bot.py config.py enums.py core db handlers jobs scripts tests
pytest
```

pyflakes catches undefined names and unused imports, which tests can miss.

Tests use a throwaway SQLite database (`tests/conftest.py`) with all
migrations applied. CI runs pyflakes and the tests on every pull request
and before every deploy. Parser, recurrence, quiet hours and settings tests are pure;
delivery tests use a fake bot (`tests/test_recurrence.FakeBot`);
`tests/test_handlers.py` drives the handlers with mocked Telegram objects.

## How to…

**Add a feature** (say, notes): `handlers/notes.py` for its screens and
buttons, `core/notes.py` if it has logic worth testing on its own, a model
in `db/models/` (imported in `alembic/env.py`) with a migration, and a
repository in `db/repositories/`. Register its handlers in `bot.py`.

**Add a trigger phrase or intent**: add it to `INTENTS` in
`handlers/intents.py`. An action takes `(update, context, rest_of_message)`.

**Add a button**: add its callback data to the enums in `enums.py`, use it in
the keyboard, register the handler in `bot.py` with `exact()` / `prefixed()`,
and add it to `tests/test_callbacks.py`.

**Ask the user a question**: add a value to `Awaiting`, set
`context.user_data[AWAITING]` when asking, handle it in
`handlers/text.py`, and pop it once answered.

**Add a setting**: add a `Setting` (and `validate`) to
`core/settings.py` and to `SETTINGS`, add a screen and handlers in
`handlers/settings.py`, a button on the right settings screen, callbacks in
`enums.py`, and handlers in `bot.py`. No migration needed.

**Change the schema**: edit `db/models/`, generate and review a migration (see
the README).

## Keeping docs up to date

Every change to what the bot does updates, in the same pull request:

- [user-guide.md](user-guide.md) — what users see and can do,
- this file — how it works,
- the feature list in the [README](../README.md),
- [plan.md](../plan.md) — done / next.
