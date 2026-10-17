# Plan

Status and next steps for `roman-tech-bot`.

## Done

### Infrastructure

- PostgreSQL on the Raspberry Pi (`postgres` container on `shared-network`),
  migrated from the original SQLite file.
- Schema managed with Alembic; migrations run automatically on startup.
- Auto-deploy: every push to `master` redeploys via the self-hosted runner
  (`.github/workflows/deploy.yml`).

### Bot UI

- Inline-keyboard menus with callback-based navigation; callback data is
  defined as enums in `enums.py`; menu messages are edited in place.
- Trigger phrases → actions for free text (`handlers/intents.py`), e.g.
  “remind me …”, “set a reminder …”, “my reminders”.

### Reminders (phase 1)

- Create by free text or `⏰ Reminders → ➕ New`, parsed by a small English
  time parser (`core/parser.py`); confirmation with Undo / Edit.
- Per-user timezone, asked on the first reminder and changeable in Settings;
  times stored in UTC.
- Delivery job every 20 s: sends due reminders with OK and snooze buttons,
  re-sends every 5 min until OK, gives up after 24 h (`missed`); blocked
  users are marked `failed`.
- List upcoming reminders with ❌ to cancel.
- Reminders only for yourself, in private chats.

### Reminders (phase 2)

- Recurring reminders: “every day at 9”, “on weekdays”, “every mon and thu”,
  “mondays”, “every evening at 7” (`core/recurrence.py`, stored in
  `reminders.recurrence` as e.g. `mon,thu@18:00`, local time). OK or a missed
  occurrence moves on to the next one; after downtime only the latest due
  occurrence is sent.
- Interval repeats (“every 2 hours”, “every other day”, at least 15 min) and
  monthly ones (“on the 1st of every month”).

### Code and docs

- Enums for reminder statuses, callback data, conversation state and repeat
  kinds, all in `enums.py`.
- Project structure by kind of code: `handlers/` (Telegram), `core/`
  (logic), `jobs/`, `db/` (models, repositories), `config.py`.
- CI runs pyflakes (undefined names, unused imports) before the tests.

### Voice

- Voice messages, transcribed offline by the separate
  [speech-service](https://github.com/qetlife/speech-service) (Vosk + ffmpeg
  on the Pi) and handled like typed text (`handlers/voice.py`,
  `services/speech.py`).
- Spoken numbers in the parser and settings (`core/numbers.py`): “at nine
  thirty”, “half past six”, “quarter to five”, “in twenty five minutes”,
  “on the fifteenth”; also “tonight at 9”, “at 7 in the evening”, “on the
  15th”.
- Documentation: `docs/user-guide.md` (features and settings for users),
  `docs/development.md` (internals), kept up to date with every change
  (`CLAUDE.md`).

### Settings

- Per-user settings: definitions and defaults in code
  (`core/settings.py`), only changed values stored in `user_settings`.
- 💤 Snooze options: presets or custom (up to 3, 1 min–24 h).
- 🔁 Repeat interval for unanswered reminders: 2 min–1 h presets (default 5 min).
- 🌙 Quiet hours (default 00:00–07:00, presets, custom or off): interval
  occurrences are skipped and repeats of unanswered reminders wait until
  morning; reminders at a specific time still fire.
- Reminder settings are grouped under ⏰ Reminders (also reachable from the
  ⏰ Reminders menu).

Decisions made along the way (from the old “Open decisions” list):

- Date/time format: natural English (“in 2 hours”, “tomorrow at 9”,
  “friday 18:00”, “dec 24”); a bare “at 9” means the next 09:00 or 21:00.
- Times are stored in UTC and shown in the user's timezone.
- Editing reminders is supported (✏️ Edit after creating).
- Recurring reminders were out of scope for phase 1 (added in phase 2).

### Failed messages

- Messages the bot didn't understand (typed and voice) are saved in
  `failed_messages`; reminders it got wrong can be flagged with `👎 Wrong`
  on the confirmation or by saying “that's wrong” / “save the last one as
  failed”, which saves what the bot made of it and opens ✏️ Edit.
- `/failed` (admin only, `ADMIN_TELEGRAM_ID`) lists the open ones; `✅ <n>`
  marks one fixed. Fixed entries are kept (they're tiny); the lasting record
  of a fix is a parser test.
- Not tied to reminders: entries have an `intent` and a snapshot of what the
  bot understood, so events can use the same table.
- First fix from it: times with a dot (“thursday at 21.20”) were read as a
  date and fell back to 09:00.

## Next

### Parser (next)

- Typo tolerance: “remid me”, “tomorow”, “wensday” (edit distance against
  the known vocabulary, only in the trigger and time words).
- More phrasings (“don't let me forget to…”, “in a fortnight”, “next month”,
  “every 2nd tuesday”), replying to a reminder (“snooze 20 min”, “move it to
  10”, “done”), plain-language commands (“cancel the dentist reminder”,
  “what do I have tomorrow?”, “set my timezone to Lisbon”), and asking
  instead of failing (“When should I remind you to call mom?”).
- Split the parser into a pipeline: tokenize → fix typos → normalize →
  intent → time.

### Reminders (phase 3)

- Reminders for other users. The `reminders` table already has
  `creator_user_id` and `target_user_id`. Open questions:
  - how to pick the target (Telegram username, forwarded message, contact
    list of registered users)
  - the target must have pressed `/start`, since bots can't message users
    first
  - whether the target can decline / mute reminders from someone
- Group chats: deliver to `chat_id`, only the target can press the buttons
  (already enforced).
- Optional AI fallback for phrasing the parser doesn't understand.

### Events

- Fixed events (“padel on thursday at 21:00”) with reminders relative to
  them (“30 min before padel, pack the racket”): the reminder moves when the
  event moves. A reminder would get an `event_id` and an offset;
  `failed_messages` gets an `event_id` column the same way it has
  `reminder_id`.

### General

- More handler tests (`tests/test_handlers.py` covers the main flows).
