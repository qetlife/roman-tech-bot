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

- Inline-keyboard menus with callback-based navigation (`menu:*`,
  `settings:*`, `rem:*`, `tz:*`); menu messages are edited in place.
- Trigger phrases → actions for free text (`intents/registry.py`), e.g.
  “remind me …”, “set a reminder …”, “my reminders”.

### Reminders (phase 1)

- Create by free text or `⏰ Reminders → ➕ New`, parsed by a small English
  time parser (`reminders/parser.py`); confirmation with Undo / Edit.
- Per-user timezone, asked on the first reminder and changeable in Settings;
  times stored in UTC.
- Delivery job every 20 s: sends due reminders with OK / 💤 10 min / 💤 1 h,
  re-sends every 5 min until OK, gives up after 24 h (`missed`); blocked
  users are marked `failed`.
- List upcoming reminders with ❌ to cancel.
- Reminders only for yourself, in private chats.

Decisions made along the way (from the old “Open decisions” list):

- Date/time format: natural English (“in 2 hours”, “tomorrow at 9”,
  “friday 18:00”, “dec 24”); a bare “at 9” means the next 09:00 or 21:00.
- Times are stored in UTC and shown in the user's timezone.
- Editing reminders is supported (✏️ Edit after creating).
- Recurring reminders were out of scope for phase 1.

## Next

### Small fixes and cleanup

- Editing a reminder that is already repeating leaves the old message's
  buttons active; remove them on edit.
- “tomorrow at 9” said shortly after midnight means the next calendar day;
  consider treating it as “this morning” before ~04:00.
- Run the tests in the deploy workflow before rebuilding.

### Reminders (phase 2)

- Configurable snooze options (and possibly repeat interval) in Settings.
- Recurring reminders (daily, weekdays, every Monday, …) via a `recurrence`
  column.
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

### General

- Error handling: `/start` still swallows exceptions silently.
- Tests for the handlers (currently covered only by manual end-to-end runs).
