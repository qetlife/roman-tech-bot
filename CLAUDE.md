# roman-tech-bot

Telegram bot (python-telegram-bot, SQLAlchemy, PostgreSQL, Alembic). Start with
`docs/development.md` for how it works.

## Rules

- **Keep the docs up to date in the same change.** Any change to what the bot
  does or how it works updates `docs/user-guide.md` (user-facing behaviour,
  phrases, settings with defaults and options), `docs/development.md`
  (internals; non-obvious choices go in its Design decisions), and
  `docs/setup.md` (environment variables, setup, deployment). The README is
  a short public landing page: only touch its feature list for headline
  features, and keep details in `docs/`.
- **Plans live in GitHub issues**, not in a file. Reference the issue in the
  pull request (“Fixes #23”) so it closes on merge; new ideas become issues.
- **Use enums instead of loose strings** for any fixed set of values (statuses,
  callback data, conversation state, kinds). **All enums go in `enums.py`.**
- **Never change existing callback data values** (`Callback`, `CallbackPrefix`,
  `ReminderAction`, `OptionAction` in `enums.py`):
  buttons already in users' chats still send them.
- **Keep the structure**: Telegram code in `handlers/` (and `jobs/`), logic in
  `core/` (no Telegram, no database), models and queries in `db/`, clients for
  other services in `services/`. See Architecture in `docs/development.md`.
- **Voice and text share one path**: voice messages are transcribed and passed
  to `handlers/text.handle_text`. New text features work by voice for free;
  spoken numbers are handled by `core/numbers.py`.
- Schema changes need an Alembic migration; settings don't (see
  `core/settings.py`).
- Run pyflakes and `pytest` before pushing (commands in `docs/development.md`,
  Tests); every push to `master` deploys.
