# roman-tech-bot

Telegram bot (python-telegram-bot, SQLAlchemy, PostgreSQL, Alembic). Start with
`docs/development.md` for how it works.

## Rules

- **Keep the docs up to date in the same change.** Any change to what the bot
  does or how it works updates `docs/user-guide.md` (user-facing behaviour,
  phrases, settings with defaults and options), `docs/development.md`
  (internals), the feature list in `README.md`, and `plan.md` (done / next).
- **Use enums instead of loose strings** for any fixed set of values (statuses,
  callback data, conversation state, kinds). See the Enums section in
  `docs/development.md`.
- **Never change existing callback data values** in `helpers/callbacks.py`:
  buttons already in users' chats still send them.
- Schema changes need an Alembic migration; settings don't (see
  `settings/registry.py`).
- Run `pytest` before pushing; every push to `master` deploys.
