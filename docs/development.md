# Development guide

How the bot works and how to extend it. For what it does from a user's point
of view, see [user-guide.md](user-guide.md). For setup and deployment, see
[setup.md](setup.md).

- [Architecture](#architecture)
- [Design decisions](#design-decisions)
- [Messages and buttons](#messages-and-buttons)
- [Reminders](#reminders)
- [Typos](#typos)
- [Settings](#settings)
- [Failed messages](#failed-messages)
- [Enums](#enums)
- [Database](#database)
- [Tests](#tests)
- [How to…](#how-to)
- [Keeping docs up to date](#keeping-docs-up-to-date)

## Architecture

```
bot.py              entry point: registers handlers and the delivery job, starts polling
config.py           BOT_TOKEN, DB_CONNECTION, SPEECH_URL, SPEECH_TOKEN, ADMIN_TELEGRAM_ID from the environment (.env)
enums.py            every enum

handlers/           everything that talks to Telegram (messages, buttons)
    commands.py     /start, /menu
    failed.py       saving failed messages; /failed list (admin only)
    menus.py        main, ⏰ Reminders and ⚙️ Settings menu screens
    reminders.py    create, edit, list; OK / snooze / undo / edit / delete / 👎 wrong buttons
    settings.py     🌍 timezone and ⏰ reminder settings screens
    text.py         typed messages: trigger phrases, answers to questions
    voice.py        voice messages: transcribe, then handle like text
    intents.py      trigger phrase → handler table
    ui.py           render_menu, callback data helpers, user_data keys

core/               the logic: no Telegram, no database sessions
    parser.py       "in 2 hours to call mom" → time + text
    numbers.py      spoken numbers → digits ("nine thirty" → 9:30), used by the parser
    typos.py        fixing typos of known words ("tomorow", "remid me"), a second try for parser and intents
    recurrence.py   Weekly / Monthly / Interval
    quiet.py        quiet hours
    timezones.py    resolving and formatting timezones
    settings.py     setting definitions and validation
    intents.py      trigger phrase matching

jobs/
    delivery.py     sends due reminders every 20 seconds
    failed.py       on startup: marks failed messages the bot now understands as fixed

services/           clients for other services (no Telegram)
    speech.py       speech-service: audio → text

db/
    session.py      engine, sessions, init_db
    migrations.py   runs Alembic on startup
    models/         user, reminder, user_setting, failed_message, types (UTCDateTime)
    repositories/   user, reminder, settings, failed_message: the only code that opens sessions

alembic/            schema migrations
autofix/            the daily auto-fix job: sandbox image, prompt, runner script
docs/               this guide and the user guide
scripts/            command line: failed.py (failed messages), the one-off SQLite migration
tests/              pytest, throwaway SQLite database
```

**Dependencies go one way**: `handlers/` and `jobs/` use `core/`, `db/` and
`services/`;
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
- **Voice messages in private chats** → `handlers/voice.on_voice`, which
  transcribes them and passes the words to `handlers/text.handle_text`
  (see [Voice messages](#voice-messages)).
- **Delivery job** → `jobs/delivery.deliver_due`, every 20 seconds via
  the job queue.

Repositories in `db/repositories/` are the only code that opens database
sessions. They return detached model objects (`expire_on_commit=False`).

## Design decisions

Choices that shape the behaviour, and why. Add one when a decision isn't
obvious from the code.

- **A small, predictable parser instead of guessing.** It understands a
  fixed set of English expressions and asks the user to rephrase otherwise,
  so a reminder is never silently set for the wrong time. Gaps are found
  through [failed messages](#failed-messages), not by making the parser
  looser. Typos are fixed only as a second try, for words the bot knows,
  and never in the reminder text.
- **“at 9” means the next 09:00 or 21:00**, whichever comes first; typed
  “9:30” and “18:00” are taken as written. A day without a time means 09:00.
- **A dot works like a colon in times** (“21.20”), unless the number is a
  valid date and doesn't follow “at” (“10.11” is 10 November).
- **Times are stored in UTC** and shown in the user's timezone. Daily,
  weekly and monthly repeats keep their local clock time across daylight
  saving and timezone changes (on a change, `handlers/reminders.keep_clock_times`
  moves their next occurrence; one-offs, intervals and snoozes keep their
  moment in time).
- **Reminders are re-sent until acknowledged**, and given up on after 24
  hours (`missed`). Quiet hours pause the re-sending, but reminders set for a
  specific time still go off.
- **Voice is transcribed offline** by a separate service (Vosk), so audio
  never leaves the server and the bot's image stays small.
- **Settings store only non-default values**, so adding a setting needs no
  migration.
- **Failed messages aren't tied to reminders** (an intent plus a JSON
  snapshot), so events can use the same table. Fixed entries are kept; the
  lasting record of a fix is a parser test.
- **Callback data never changes**: buttons already in users' chats still send
  the old values.

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
   like “please” allowed in front). This always wins. If no phrase matches
   as written, it's tried again with typos of the phrases' words fixed
   (“remid me”, see [Typos](#typos)); the rest keeps the original words.
2. Otherwise, if the bot asked a question, `context.user_data["awaiting"]`
   holds an `Awaiting` value (`enums.py`; keys in `handlers/ui.py`) and the message is the
   answer. For `Awaiting.EDIT`, the reminder id is in
   `user_data["edit_reminder_id"]`.
3. Otherwise the bot replies with a help text (and saves the message as
   failed, see [Failed messages](#failed-messages)).

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

## Typos

`core/typos.py` fixes typos of known words, as a **second try** only: the
parser and the intent matcher first read a message as written, and only if
that fails try again with typos fixed. So nothing that worked before can
change.

- `distance()` counts edits (insert, delete, replace, swap two neighbours).
  A word of 4–7 letters may be 1 edit off; 2 if it or the known word has 8
  or more (“wensday” → “wednesday”). Shorter words are never guessed.
- A `Vocabulary` maps each known word to a meaning. A word that is itself
  known is never changed (“reminders” stays, even though it's 1 edit from
  “reminder”), and a typo equally close to two meanings isn't guessed; a tie
  within one meaning (“minuts”: “minute” / “minutes”) is fine. `ALIASES`
  covers shorthand that's too far for distance (“tonite”, “tmrw”).
- `parser.TIME_VOCABULARY` is built from the parser's own tables (weekdays,
  months, units, number words, day parts, repeat words). `parse_reminder`
  fixes the words word for word, reads the time from the fixed words and
  takes the text from the original ones, so the text keeps the user's
  spelling. The leftover is checked with fixed words on both tries, so
  “tomorow at 9” asks for a text instead of creating a reminder called
  “tomorow”.
- The intent vocabulary is the words of all trigger phrases.

## Voice messages

Transcription runs in a separate service,
[speech-service](https://github.com/qetlife/speech-service) (Vosk + ffmpeg,
offline), so other projects can use it and this bot's image stays small. It
runs on the Pi's `shared-network` as `http://speech:8000`.

1. `handlers/voice.on_voice` refuses messages over 2 minutes, downloads the
   voice message (OGG/Opus) and calls `services/speech.transcribe`.
2. `services/speech.py` POSTs the audio as it is to `SPEECH_URL/transcribe`
   (with `Authorization: Bearer SPEECH_TOKEN` if set) and returns the text.
   It raises `SpeechUnavailable` (not configured, unreachable, server error)
   or `InvalidAudio` (400), which the handler turns into short replies.
3. The handler replies `🎙 “<text>”` so misheard words are visible, then
   calls `handlers/text.handle_text`, the same path as typed text.

Vosk returns lowercase words without punctuation and spells numbers out
(“nine thirty”, “twenty five”). `core/numbers.normalize_numbers` runs at
the end of the parser's tokenizer and turns them into digits and clock
times (“9:30”, “25”, “6:30” from “half past six”, “15th” from “the
fifteenth”). Spoken clock times are marked (`"9:30~"`) so they are
ambiguous like “at 9” (the next 09:30 or 21:30), unlike typed “9:30”. The
reminder text keeps the original words. The settings parsers (snooze
options, quiet hours) normalize spoken numbers too.

Without `SPEECH_URL`, voice is off and the bot replies that it isn't set up.
Tests fake the service with an `httpx.MockTransport` (`services.speech.transport`).

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

## Failed messages

Messages the bot didn't handle well, kept to improve the parser
(`handlers/failed.py`, table `failed_messages`). Two `FailureReason`s:

- `NOT_UNDERSTOOD`, saved by `record_not_understood()` wherever the bot says
  it didn't understand: the help text in `handlers/text.py`, and a
  `ParseError` in `create_reminder` / `edit_reminder` (with `intent` and
  `bot_understood = {"error": <message>}`).
- `WRONG_RESULT`, saved by `handlers/reminders.flag_wrong()` from the
  `👎 Wrong` button (`ReminderAction.WRONG`) or the `IntentName.FLAG_FAILED`
  phrases (“that's wrong”, `flag_last_reminder`). It stores the reminder's
  `request` (the message as the parser got it, saved on the reminder with its
  `source` when created or edited), a snapshot of what the bot made of it
  (`{"text", "remind_at", "recurrence"}`) and `reminder_id`, then cancels
  the reminder (retiring its delivered message if it was firing). The
  button replaces the confirmation's text, like ↩️ Undo; the phrases reply.
  One open entry per reminder, and afterwards “that's wrong” refers to
  nothing new (`last_reminder_id` is `None`), so saying it twice doesn't
  delete the reminder before.

“The last one” is `user_data["last_reminder_id"]`: set when a reminder is
created or edited, set to `None` when a message isn't understood (already
saved). After a restart it falls back to the newest reminder.

The table isn't tied to reminders: `intent` (an `IntentName`) says what the
bot thought was asked and `bot_understood` is a JSON snapshot, so other
features (events) add their own optional link column next to `reminder_id`.

`/failed` is only answered for `ADMIN_TELEGRAM_ID` (silently ignored for
everyone else); it lists the newest open entries. `✅ <n>`
(`CallbackPrefix.FAILED_FIXED`) sets `status = fixed`, `🗑 <n>`
(`CallbackPrefix.FAILED_IGNORED`) sets `status = ignored` (for messages that
can't be learned, like a garbled transcript); both set `fixed_at` and a
`note` saying why. Closed entries are not deleted. Saving never breaks the
reply: database errors are logged.

### Closing them automatically

- **On startup** (so after every deploy), `jobs/failed.resolve_understood()`
  replays each open `NOT_UNDERSTOOD` entry through the intents and the parser,
  at the moment it was sent in the user's timezone, and marks the ones that
  now work fixed (`note = "understood after an update"`). Wrong results stay
  open: the bot did understand something, so only a person (or the auto-fix
  job) can tell whether it's right now. A failure here is logged and the bot
  starts anyway.
- **`scripts/failed.py`** is the command line for the auto-fix job on the Pi:
  `list` (open entries as JSON lines), `check` (the startup re-check),
  `fixed` / `ignore <id> <note>`, and `pr <id> <number>`, which sets `fix_pr`:
  the pull request that teaches the parser that message, shown on `/failed`
  as “🔧 Fix waiting in pull request #n” so it isn't fixed twice;
  `wait <id> <note>`, which keeps an entry open with a `note` naming the
  feature it needs (a request without a time needs the bot to ask “when?”),
  shown as “⏳ Waiting for: …”; and `reopen <id>` for one closed by mistake.
- **The auto-fix job** (`autofix/`, daily on the Pi) opens a pull
  request teaching the parser the admin's open messages, then links them
  with `pr`, marks the ones needing a feature with `wait`, and ignores the
  unfixable ones. A fix the privacy check refuses isn't pushed: it's kept
  in `~/autofix-logs/blocked-*.diff` on the Pi with what matched, and its
  entries wait (`BLOCKED_NOTE`) instead of being retried every day. It
  skips open entries with a `fix_pr` or a `note`.
  Waiting entries are closed by hand (✅ on `/failed`, or `fixed <id>`) by the
  change that adds the feature: the startup re-check only replays the parser
  and intents, and features like asking “when?” live in the handlers. When that pull request is merged
  the not-understood entries close on startup; wrong results are marked
  fixed by the next run. See [setup](setup.md#auto-fix-job).
- **Privacy:** the entries are the user's own words and stay in the database.
  The repository is public, so fixes are tested with made-up messages of the
  same shape (“remind to call the bank”), never the saved text.

## Enums

Use an enum instead of loose strings for any fixed set of values. **All
enums live in `enums.py`**, so they are easy to find and change; add new
ones there too.

| Enum                                    | For |
| --------------------------------------- | --- |
| `ReminderStatus` (+ `ACTIVE_STATUSES`)  | reminder lifecycle; stored as its value in `reminders.status`, a `VARCHAR(16)` (non-native SQLAlchemy `Enum` in `db/models/reminder.py`) |
| `RepeatKind`                            | the kind of repeat the parser found |
| `Awaiting`                              | what the next typed message answers |
| `IntentName`                            | free-text intents; stored in `failed_messages.intent` |
| `MessageSource`                         | typed or voice; in `reminders.source` and `failed_messages.source` |
| `FailureReason`, `FailureStatus`        | `failed_messages.reason` and `.status` (open, fixed, ignored) |
| `Callback`, `CallbackPrefix`, `ReminderAction`, `OptionAction` | callback data of every button |

Weekdays use the standard library's `calendar.Day` (in the parser and
`Weekly`).

`StrEnum` members compare equal to their string values, which keeps stored
data and callback data compatible.

## Database

PostgreSQL in production, SQLite in tests. Times are `UTCDateTime`
(`db/models/types.py`): timezone-aware, stored and returned in UTC. Schema
changes go through Alembic; see [Database migrations](setup.md#database-migrations).

| Table           | Holds |
| --------------- | ----- |
| `users`         | `telegram_id`, `timezone` |
| `reminders`     | creator/target user, chat, text, `remind_at`, `next_fire_at`, `status`, `fire_count`, `last_message_id`, `recurrence`, `request` and `source` (the message it was made from) |
| `user_settings` | `(user_id, key)` → JSON value, only non-defaults |
| `failed_messages` | user, `text`, `source`, `reason`, `intent`, `bot_understood` (JSON), optional `reminder_id`, `status`, `created_at`, `fixed_at`, `note`, `fix_pr` |

## Tests

```bash
pip install -r requirements-dev.txt
python -m pyflakes bot.py config.py enums.py core db handlers jobs scripts services tests autofix
pytest
```

pyflakes catches undefined names and unused imports, which tests can miss.

Tests use a throwaway SQLite database (`tests/conftest.py`) with all
migrations applied. CI runs pyflakes and the tests on every pull request
and before every deploy. Parser, recurrence, quiet hours and settings tests are pure;
delivery tests use a fake bot (`tests/test_recurrence.FakeBot`);
`tests/test_handlers.py` and `tests/test_voice.py` drive the handlers with
mocked Telegram objects; `tests/test_numbers.py` covers spoken phrases.

## How to…

**Add a feature** (say, notes): `handlers/notes.py` for its screens and
buttons, `core/notes.py` if it has logic worth testing on its own, a model
in `db/models/` (imported in `alembic/env.py`) with a migration, and a
repository in `db/repositories/`. Register its handlers in `bot.py`.

**Use another service**: add a client in `services/` (plain Python: no
Telegram, configured through `config.py`), with its own exceptions for
"unavailable" and "bad input", and fake it in tests with
`httpx.MockTransport`.

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
[Database migrations](setup.md#database-migrations)).

## Keeping docs up to date

Every change to what the bot does updates, in the same pull request:

- [user-guide.md](user-guide.md) — what users see and can do,
- this file — how it works (and [Design decisions](#design-decisions) for
  choices worth remembering),
- [setup.md](setup.md) — new environment variables, setup or deployment steps,
- the feature list in the [README](../README.md), if it's a headline feature.

Plans and ideas are [GitHub issues](https://github.com/qetlife/roman-tech-bot/issues),
not a file: reference the issue in the pull request (“Fixes #23”) so it
closes when merged.
