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
- [Unexpected errors](#unexpected-errors)
- [People](#people)
- [Events](#events)
- [Google Calendar](#google-calendar)
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
    events.py       📅 Events: create, list, move, cancel; reminders relative to an event; "event or reminder?"
    calendar.py     📅 Google Calendar: linking, ⚙️ Settings → 📅 Calendar, syncing both ways
    web.py          the small web server for Google: OAuth callback, push notifications
    errors.py       the catch-all for unexpected errors: recorded, and “Sorry, something went wrong”
    failed.py       saving failed messages; /failed list (admin only)
    people.py       👥 People: invite links, requests by @username, rename, remove
    menus.py        main, ⏰ Reminders and ⚙️ Settings menu screens
    reminders.py    create, edit, list; OK / snooze / undo / edit / delete / 👎 wrong buttons
    replies.py      replies to a reminder message: “done”, “snooze 20 min”, “move it to 10”, “cancel”
    settings.py     🌍 timezone and ⏰ reminder settings screens
    text.py         typed messages: trigger phrases, answers to questions
    voice.py        voice messages: transcribe, then handle like text
    intents.py      trigger phrase → handler table
    ui.py           render_menu, callback data helpers, user_data keys

core/               the logic: no Telegram, no database sessions
    parser.py       "in 2 hours to call mom" → time + text
    numbers.py      spoken numbers → digits ("nine thirty" → 9:30), used by the parser
    typos.py        fixing typos of known words ("tomorow", "remid me"), a second try for parser and intents
    recurrence.py   Weekly / Monthly / MonthlyWeekday / Interval
    quiet.py        quiet hours
    timezones.py    resolving and formatting timezones
    settings.py     setting definitions and validation
    intents.py      trigger phrase matching
    replies.py      reading replies to a reminder message (“snooze 20 min” → ReplyCommand)
    contacts.py     contact names: valid ones, unique ones (“Anna 2”), the default
    commands.py     plain-language commands: which reminder “cancel the dentist reminder” means, which day “what do I have tomorrow?” is
    events.py       events: parsing (all-day too), occurrences, "30 min before padel", which event a message names
    gcal.py         Google Calendar's JSON ↔ the bot's events
    secrets.py      encrypting Google logins, signing the OAuth state
    errors.py       recording unexpected errors to a rotating file (no Telegram, no database), reading them back

jobs/
    delivery.py     sends due reminders every 20 seconds
    failed.py       on startup: marks failed messages the bot now understands as fixed
    calendar.py     daily: renew Google push channels, sync every linked user

services/           clients for other services (no Telegram)
    speech.py       speech-service: audio → text
    google_calendar.py  Google OAuth and the Calendar API

db/
    session.py      engine, sessions, init_db
    migrations.py   runs Alembic on startup
    models/         user, reminder, user_setting, failed_message, contact (+ invite), event, google, types (UTCDateTime)
    repositories/   user, reminder, settings, failed_message, contact, event, google: the only code that opens sessions

alembic/            schema migrations
autofix/            the daily auto-fix job: sandbox image, prompt, runner script
docs/               this guide and the user guide
scripts/            command line: failed.py (failed messages), errors.py (unexpected errors), the one-off SQLite migration
tests/              pytest, throwaway SQLite database
```

**Dependencies go one way**: `handlers/` and `jobs/` use `core/`, `db/` and
`services/`;
`core/` imports neither Telegram nor the database (it's plain Python, tested
without mocks); `db/` uses only `enums` and the `Setting` type from `core/`.
`handlers/events.py` uses `handlers/reminders.py`, not the other way
round. The exceptions import inside a function (a module-level import would
be circular): `handlers/settings.py` resumes a reminder or an event after the
user picks a timezone, `handlers/reminders.py` hands “30 min before
padel …” and “that's wrong” after an event to `handlers/events.py`, and
`handlers/events.py` / `handlers/reminders.py` call `handlers/calendar.py`
(which uses `handlers/events.py`) to sync.

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

- **Contacts opt in, one direction at a time.** A bot can only message
  people who started it, and nobody should get reminders they didn't agree
  to. So a contact exists only after the other person taps ✅ Allow on a
  single-use invite link (7 days) or on a request to their @username, which
  only works if they already use the bot. A `contacts` row means “owner may
  remind contact”; the other direction is another row. Either side can end
  it, which **deletes** the row (consent withdrawn, nothing kept) and
  cancels the owner's waiting reminders for them.
- **A reminder for someone else is in the sender's time.** “remind anna
  tomorrow at 9” is parsed in the creator's timezone (they said it), and a
  repeat keeps the creator's clock: `next_after` gets the creator's
  timezone everywhere (delivery, ✅ OK, the agenda, `keep_clock_times`,
  which moves what a user *made*). The target sees the time converted, plus
  “(Roman's time)” on the repeat. Everything about receiving it (snooze
  buttons, repeat interval, quiet hours) is the target's.
- **“remind <word>” is never a guess.** After the bare trigger “remind”,
  a contact's name (or @username) makes it theirs; a word that looks like
  a name but isn't a contact (“bob to …”, “bob tomorrow at 9 to …”) gets
  “Who's “bob”?” and nothing is made, rather than a reminder for yourself
  called “bob to …”. A message that is already a reminder as written
  (“remind call mom tomorrow”) stays one.

- **A small, predictable parser instead of guessing.** It understands a
  fixed set of English expressions and asks the user to rephrase otherwise,
  so a reminder is never silently set for the wrong time. Gaps are found
  through [failed messages](#failed-messages), not by making the parser
  looser. Typos are fixed only as a second try, for words the bot knows,
  and never in the reminder text.
- **A leftover of joining words is part of the time, not a text.** When
  the parser splits a message into a time and a text, a leftover made only
  of `TIME_FRAGMENTS` (“at”, “on”, “by”, “yesterday”, …) isn't a text, so
  “today at 00:00” isn't tomorrow's reminder called “today at”. A time on
  its own then says “That time has already passed.” if it has (also
  “yesterday …”), and raises `MissingText` otherwise, so the bot asks what
  for (#45).
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
- **A reminder relative to an event follows it** instead of being a copy of
  its time: `reminders.event_id` + `event_offset` (minutes from the start),
  and “every time” is an `Offset` repeat that holds the event's repeat,
  timezone and skipped days, so delivery, ✅ OK, the agenda and quiet hours
  treat it like any repeat. Whenever the event changes, `follow` recomputes
  its reminders; editing a reminder unlinks it.
- **Events keep their own timezone** (`events.timezone`, the creator's when
  made): “padel at 21:00” stays 21:00 there if the user moves, and Google
  Calendar (#22) stores events the same way. `keep_clock_times` leaves
  `Offset` reminders alone for that reason.
- **A day without a time is an all-day event** (it starts at the day's
  midnight), unlike a reminder, where it means 09:00: “dentist on friday”
  is about the day. `ParsedReminder.timed` tells the two apart.
- **Ask, don't guess, between an event and a reminder**: a time and a text
  without a trigger phrase (“padel on thursday at 21:00”) gets
  `📅 Event / ⏰ Reminder` buttons rather than the help text. With an event
  of that name, “cancel padel” is the event (its reminders go with it).
- **“move” has no typo fixing** (`Intent.typos`): “movie tonight at 8” is
  one letter from it.
- **Events repeat as RFC 5545 RRULEs**, what Google Calendar uses, so any
  repeat from Google works (“every 2nd and 4th Tuesday”, “until December”)
  and nothing is lost on the way back. The bot's own repeats convert
  (`to_rrule`); older events keep their format until they change. Reminders
  keep the bot's formats.
- **Google pushes, the bot also asks**: push notifications make changes show
  up at once, and an incremental sync when the user asks about reminders or
  events (at most every 5 minutes) and once a day covers a lost push. The
  sync before a reply waits at most a few seconds.
- **Last change wins**, by Google's `updated` against the event's
  `updated_at`; a change the bot couldn't send yet (`pending_push`) is sent
  on the next sync.
- **An expired login keeps everything**: the bot warns once and stops
  syncing; nothing is deleted or moved, and changes made meanwhile are sent
  after linking again.
- **Only two scopes** (`calendar.events`, `calendar.calendarlist.readonly`):
  enough for both directions and push, and not the full `calendar` scope
  that can delete calendars and change sharing.
- **Unexpected errors go to a file, not a table** (`core/errors.py`): the
  database is one of the things that breaks, and its errors would go
  unrecorded. No outside error tracker either: errors can hold bits of what
  users sent, so they stay on the Pi. Nobody is notified; they are reviewed
  now and then with `scripts/errors.py`.

## Messages and buttons

**Menus** are a single long-lived message: `handlers/ui.render_menu`
edits it in place, or replaces it if it can't be edited.

**Callback data** for every button is defined as enums in `enums.py`:

| Enum             | For                                    | Example                 |
| ---------------- | -------------------------------------- | ----------------------- |
| `Callback`       | buttons with fixed data                | `menu:main`, `rset:show` |
| `CallbackPrefix` | buttons that carry a value             | `tz:Europe/Kyiv`        |
| `ReminderAction` | buttons on a reminder (`rem:<action>:<id>`) | `rem:snz:5:10`     |
| `PeopleAction`   | 👥 People buttons (`ppl:<action>:<contact id>`), answers to an invite (`inv:<yes\|no>:<token>`) | `ppl:ren:3` |
| `EventAction`    | buttons on an event (`evt:<action>:<event id>[:<value>]`) | `evt:rem:4:-30` |
| `CalendarAction` | ⚙️ Settings → 📅 Calendar (`gcal:<action>[:<value>]`) | `gcal:tgl:6` |
| `OptionAction`   | buttons on a setting screen            | `qhopt:set:23:00-07:00` |

Build data with `reminder_callback()` / `event_callback()` / `option_callback()`, read it with
`split_option()`, and register handlers with `exact(...)` / `prefixed(...)`
(all in `handlers/ui.py`).
**Never change an existing value**: buttons on messages already in users'
chats still carry it. `tests/test_callbacks.py` pins them.

**Free text** (`handlers/text.py`):

0. A Telegram reply to a delivered reminder (`reminders.last_message_id`)
   that is a reply command (`core/replies.parse_reply`) acts on that
   reminder (`handlers/replies.py`); other replies go on below.
1. A message starting with a trigger phrase runs that intent's action with
   the rest of the message (`handlers/intents.py`, matched by
   `core/intents.py`; longest phrase wins, whole words only, polite filler
   like “please” allowed in front). This always wins. If no phrase matches
   as written, it's tried again with typos of the phrases' words fixed
   (“remid me”, see [Typos](#typos)); the rest keeps the original words.
   During a question, the command intents in `NEEDS_KEYWORD`
   (`handlers/text.py`: cancel, list, one day, timezone, new event, list
   events) count only if the message has one of their words (“reminder”,
   “timezone”, “event”, “calendar”), so “delete old photos” or “what's on
   the agenda” can be the answer to “what should I remind you about?”;
   “move” counts only if one of the user's event titles follows
   (`events.names_event`), so “move the car” is an answer too.
2. Otherwise, if the bot asked a question, `context.user_data["awaiting"]`
   holds an `Awaiting` value (`enums.py`; keys in `handlers/ui.py`) and the message is the
   answer. For `Awaiting.EDIT`, the reminder id is in
   `user_data["edit_reminder_id"]`.
3. Otherwise, a message that is only a time (“tomorrow at 12”) starts a
   reminder, which asks for its text (`is_bare_time`, below).
4. Otherwise `handlers/events.handle_untriggered`: “padel is at 20:00 now”
   (an event's title, then “is …”) moves that event, and a message with a
   time and a text asks `📅 Event / ⏰ Reminder` (`Callback.PICK_EVENT` /
   `PICK_REMINDER`; the text waits in `user_data["pending_pick"]`).
5. Otherwise the bot replies with a help text (and saves the message as
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
in the user's timezone. Two subclasses say which half is missing:
`MissingText` (a time, no text) and `MissingTime` (no time it understands;
`.text` is the request cleaned up as reminder text). A third, `TooFar`, is a
duration over `MAX_DURATION` (100 years; more would overflow dates, in
delivery too for “every 99999999 days”); `parse_duration` raises it as
well, so `parse_day`, replies and `parse_move` catch it.

**Asking for the missing half** (`handlers/reminders.py`): `create_reminder`
turns `MissingText` into `ask_what` and `MissingTime` into `ask_when`,
instead of failing. They set `Awaiting.REMINDER_TEXT` / `REMINDER_TIME` and
keep the half they have in `user_data["pending_part"]`; `answer_what` /
`answer_when` join it with the answer (“<time> to <text>”) and parse that.
A wrong answer to “when?” is saved as failed (intent
`IntentName.REMINDER_WHEN`; the re-check closes it once that answer parses
as a time) and asked again. A trigger phrase other than “that's wrong”, or
a new failure, ends the question. The message
asked about is kept in `user_data["asked_request"]`; “that's wrong” while
`awaiting` is still the question saves it as failed with `ASKED_ERROR`
(`flag_question`, called from `handlers/text.py`, the only reader). Asking isn't saved as a failure, and the startup re-check
counts it as understood, except for those flagged entries. ✏️ Edit doesn't
ask: it says what's wrong.

**For someone else** (`handlers/reminders.py`, “remind anna …”): the bare
trigger “remind” is its own intent (`remind_someone`, also
`IntentName.REMINDER_CREATE`). `core/contacts.split_name` finds the
longest of the user's contact names (and their @usernames) at the start;
`core/contacts.unknown_name` spots a name that isn't a contact. The
contact's id is kept in `user_data["pending_contact_id"]` while the bot asks
for a time, a text or the timezone, so the answer is for the same person;
`save_reminder` checks again that they're still an accepted contact. The
reminder has `creator_user_id` = the sender, `target_user_id` and `chat_id`
= the contact's.

| | Who |
| --- | --- |
| ✅ OK, 💤, replies (`TARGET_ACTIONS`) | target |
| ↩️ Undo, ✏️ Edit, 👎 Wrong (`CREATOR_ACTIONS`) | creator |
| ❌ in the list (`ReminderAction.DELETE`) | either |

`tell_creator` sends the creator “✅ did it”, “❌ missed it” (both only
with `reminders.sender_updates` on) or “🗑 cancelled” (when the target
cancels: button, list, or a “cancel” reply). The 📋 list is
`list_active` (for the user, from anyone) followed by `list_sent` under
“For others”; the agenda shows only the former. “That's wrong” refers to
the last reminder the user *made* (`latest_created`).

**Recurrence** (`core/recurrence.py`): six types, stored as a string
in `reminders.recurrence` (`NULL` = one-off):

| Type       | Stored as                       | Meaning |
| ---------- | ------------------------------- | ------- |
| `Weekly`   | `mon,tue,wed,thu,fri@08:30`     | these weekdays (`calendar.Day`) at a local time |
| `Monthly`  | `month:15@09:00`                | this day of the month (last day in shorter months) at a local time |
| `MonthlyWeekday` | `month:2tue@09:00`, `month:-1fri@09:00` | the 2nd Tuesday / last Friday of the month at a local time; months without a 5th weekday are skipped |
| `Interval` | `every:120m@2026-10-11T07:00Z`  | every N minutes from a start (UTC); whole days keep the local time |
| `Offset`   | `event:-30m;Europe/Lisbon;;rrule:…` | minutes from every occurrence of a repeating event (its repeat, in its timezone, minus skipped ones); see [Events](#events). Older ones wrap the formats above |
| `RRuleSet` | `rrule:Europe/Lisbon;20261022T210000;<exdates>;<rdates>;FREQ=WEEKLY;BYDAY=TH` | an event's RRULE from its first occurrence; only inside an `Offset` |

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

Snooze buttons, the repeat interval, quiet hours and the chat are the
target's; repeats follow the creator's timezone (`rule_tz`). A reminder
from someone else says “📨 from <them>”, and when one is missed, its
creator is told (`tell_creator`). If Telegram refuses it (`Forbidden`), it
is marked `failed`; for someone else, see Blocked in [People](#people).

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
- `parser._mishearings` is a third try for voice transcripts: “to borrow”
  becomes “tomorrow” and a “too” directly after the time becomes “to” (a “too”
  later in the text is left alone). It's a
  separate, phrase-level step (not in `Vocabulary`) because it merges two
  words, and it only runs when both earlier tries fail, so “remind me to
  borrow a book at 5” is untouched.

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
| `reminders.sender_updates`  | `true`             | whether the creator of a reminder for someone else hears ✅ done / ❌ missed |

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
bot thought was asked and `bot_understood` is a JSON snapshot; events have
their own optional link, `event_id`, next to `reminder_id`. The startup
re-check replays event messages (`EVENT_CREATE`, `EVENT_EDIT`,
`EVENT_WHEN`) through `parse_event`; `EVENT_MOVE` needs the user's events,
so those are closed by hand.

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

## Unexpected errors

What counts as unexpected: anything logged at ERROR or above **with an
exception**, i.e. `logger.exception(…)` (or `logger.error(…, exc_info=…)`).
Expected situations (Google unreachable, a login that expired, Telegram
network hiccups) are logged at INFO or WARNING and stay out. So: catch what
you expect and log it as a warning; let the rest reach `logger.exception` or
the catch-all.

- **The catch-all** `handlers/errors.on_error` gets every exception a handler
  or job didn't catch. It logs it with what the bot was doing
  (`describe`: user id, button data or command, the kind of message, **never
  the text**) and tells the user “Sorry, something went wrong on my side. Try
  again in a moment.” (an alert for a button). `NetworkError` and `Forbidden`
  (a user who blocked the bot) are only warnings.
- **The file**: `install` (in `bot.py`) adds `ErrorFileHandler` to the root
  logger, which writes to `ERRORS_DIR/errors.jsonl`, one JSON object per
  line: time, key, count, type, message, where (the innermost frame in the
  bot's own code), context (the logger, the log message, `extra={"error_context": …}`),
  traceback. Pass `extra={"error_context": {...}}` to add context to a
  `logger.exception`. If the directory can't be written the bot logs a
  warning and runs without it.
- **Size**: `RotatingFileHandler`, 5 MB per file and 4 old ones
  (`errors.jsonl.1` … `.4`), 25 MB at most; the oldest is deleted.
- **Floods**: errors are grouped by key, the exception type and the function
  it came from (`ValueError@jobs/delivery.py:deliver_due`, not the line, which
  moves). A group is written in full at most once an hour; repeats in between
  are counted and written as `{"time", "key", "count"}` at most every 10
  minutes (and on shutdown), so a bug in the 20-second delivery job takes a
  few KB a day.
- **Reading them**: `scripts/errors.py list [--since YYYY-MM-DD]` shows the
  groups, most frequent first, with their counts and first and last time
  seen, over all rotated files; `show <n>` prints one in full. See
  [setup](setup.md#unexpected-errors).
- **Privacy:** an error's message can hold what a user sent (a database error
  shows its parameters). The file stays on the Pi; a fix goes in a GitHub
  issue described without it, tested with made-up input.

## People

Who may send reminders to whom (`handlers/people.py`, tables `contacts` and
`invites`, `db/repositories/contact.py`). See the design decision above for
why the other person always opts in.

- **Invite link**: `👥 → ➕ Invite` (`Callback.NEW_INVITE`) creates an
  `invites` row with a random token and shows
  `https://t.me/<bot username>?start=inv_<token>`. Opening it sends
  `/start inv_<token>`; `handlers/commands.start` passes it to
  `on_start_invite`, which asks ✅ Allow / ❌ No (`inv:yes|no:<token>`).
  `ContactRepository.use_invite` checks it (unknown, used, expired, own) and
  makes or accepts the contact; ❌ No (`decline_invite`) uses the invite up too.
  Both tell the owner.
- **By @username**: the same screen sets `Awaiting.CONTACT_USERNAME`. A
  known `users.username` gets a pending `contacts` row and a message with
  `ppl:yes|no:<contact id>`; if Telegram refuses (they blocked the bot), the
  row is removed again. Against spam: ❌ No keeps the row as `declined`
  (not a contact: lists, names and senders skip it) so the same owner can't
  ask again for `REQUEST_COOLDOWN` (30 days), and an owner can send
  `REQUESTS_PER_DAY` (5) requests a day, at most one per person. Both
  limits count from `contact_requests`, a log that only grows (cancelling a
  pending request deletes its `contacts` row, but not its log entry). Usernames can go stale (the bot only
  sees changes when someone writes to it): `remember_profile` takes a
  username away from anyone else who had it, and `get_by_username` treats
  more than one match as unknown.
- **Messages to the other person** go through `tell()` (`bot.send_message`
  to their private chat, whose id is their Telegram id); a refusal is
  logged, not raised.
- **Names**: `core/contacts.py` (`clean_name`, `unique_name`,
  `default_name`); ✏️ Rename sets `Awaiting.CONTACT_NAME` with the id in
  `user_data["rename_contact_id"]`.
- **Ending it**: `ContactRepository.remove` (either side; 🗑 Remove by the
  owner, 🚫 Stop by the contact) cancels the owner's active reminders for
  that contact and deletes the row. It returns `Removed(contact, cancelled)`,
  the reminders as they were before (the bulk update isn't synchronized),
  so `retire_cancelled` can take the buttons off one that is firing. Only
  the two people in a contact can see or change it (`on_people_button`).
- **Blocked**: when delivering a reminder for someone else raises
  `Forbidden` (they blocked the bot or deleted their account), it is
  marked `failed` and `jobs/delivery._unreachable` removes the contact,
  like 🚫 Stop, and tells the creator. Blocking is the one way to say no
  without the bot, and every later reminder would fail the same way.
- **Profiles**: `handlers/ui.remember_profile` runs first for every update
  (`TypeHandler`, group -1) and stores `first_name` / `username` when they
  change, for known users; `/start` also stores them for new ones.

## Events

Events (`handlers/events.py`, logic in `core/events.py`, table `events`,
`db/repositories/event.py`) are the user's own, and can sync with
[Google Calendar](#google-calendar).

- **Parsing**: `parse_event` is `parse_reminder` with the text as the
  title. Without a time of day (`ParsedReminder.timed` is false: “friday”,
  “every friday”), it's an all-day event from that day's midnight. “today”
  is all day even after 09:00 (the parser would call that passed).
  `MissingText` / `MissingTime` ask for the title or the time
  (`Awaiting.EVENT_TITLE` / `EVENT_TIME`, the half in `pending_part`), like
  reminders; `Awaiting.EVENT` is ➕ New or a resend.
- **Repeats** are RRULEs (below). `events.skipped` holds occurrences that
  don't happen (`20261029T2000Z,…`, UTC, EXDATEs); those over are dropped
  when it's written. `next_occurrence` / `occurs_on` skip them; an
  occurrence counts as on until it ends (an all-day one, all of its day).
- **Which event**: `match_title` finds the longest title at the start of the
  words (“the”, “my” in front, “event” after are ignored), among the
  upcoming ones (`titles_of`, the soonest per title).
- **Moving**: `parser.parse_move` reads “to 20:00” (same day), “to friday”
  (same time), “to 8” (the closer of 08:00 / 20:00); for a repeat, see
  below. It reads the phrase in the event's timezone, and keeps the event's
  length. Skipped and moved days are dropped.

**Reminders relative to an event**: `split_relative` reads “<duration>
before|after <event> [to <text>]” or “<text> <duration> before|after
<event>” (and “the day before”) in `create_reminder`, before the usual
parser; a message that names no event but is a reminder as written (“to take
pills 30 min after breakfast every day”) stays an ordinary reminder. The
reminder gets `event_id` and `event_offset`. For a repeating event the bot
asks “just the next one, or every time?” (`EventAction.ONCE` / `EVERY`, the
details in `user_data["pending_event_reminder"]`): the next one is a
one-off at that occurrence, every time is an `Offset` repeat around the
event's `RRuleSet`, which is why `reminders.recurrence` is `Text`.

`follow(old, event)` runs after every change (edit, move, skip): “every
time” ones get the new `Offset` (only the string changes, `relink`, if their
occurrence still happens); one for a single occurrence moves to the new
occurrence nearest the old one, or is cancelled if that one is skipped; one
for a one-off moves with its start. A firing one loses its buttons.
Cancelling an event (`EventRepository.cancel`) cancels its reminders in the
same transaction. Delivery adds “📅 padel: Today, 21:00 (in 30 min)”
(`occurrence_line`).

**Buttons** (`evt:<EventAction>:<id>[:<value>]`, only for the event's
owner): ⏰ `rem:<minutes>`, `once` / `every`, ↩️ `undo`, ✏️ `edit`
(`Awaiting.EVENT_EDIT`, `user_data["edit_event_id"]`), 👎 `wrong`
(`WRONG_RESULT` with `event_id` and `{"title", "starts_at", "recurrence",
"all_day"}`), `open` (its screen), ⏭ `skip:<occurrence>` (the occurrence in
the data, so a stale button can't skip another day) and 🗑 `del`.

“that's wrong” right after an event (`user_data["last_event_id"]`, cleared
by a new reminder or a message not understood) flags the event
(`flag_last`). The agenda (“what do I have tomorrow?”) is
`handlers/events.agenda`: that day's events (`day_text`), then the
reminders (`show_day`).

**Repeats** (`core/events.rule_of`): `events.recurrence` is an RRULE
(`FREQ=WEEKLY;BYDAY=TH`) from `starts_at` in the event's `timezone`;
`skipped` are EXDATEs, `moved` the occurrences moved in Google
(`<original>><new>`, so the original is skipped and the new time added).
`RRuleSet` (`core/recurrence.py`, with `python-dateutil`) expands them; it
can end (UNTIL, COUNT), so `next_after` may be None, which delivery, ✅ OK
and `follow` handle. An “every time” reminder's `Offset` wraps the event's
`RRuleSet` (`event:-30m;<tz>;;rrule:<tz>;<start>;<exdates>;<rdates>;<RRULE>`).
Each occurrence lasts `duration` (to `ends_at`, a day if all day, else 0),
and counts as on until it ends.

**Moving a repeat** (`parse_move` with the RRULE): a time moves it from the
current occurrence on (a new DTSTART), a weekday changes a weekly one with
one day (`BYDAY`), a whole repeat replaces it.

## Google Calendar

`handlers/calendar.py` (with `core/gcal.py`, `services/google_calendar.py`,
`handlers/web.py`, `jobs/calendar.py`, tables `google_accounts` and
`google_calendars`). Off unless `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`GOOGLE_REDIRECT_URI` and `CALENDAR_KEY` are set (`config.calendar_configured`);
then `bot.py` also starts the web server (aiohttp, `WEB_PORT`) in the same
event loop.

- **Linking**: the 🔗 button opens Google's consent page
  (`access_type=offline`, `prompt=consent`) with a `state` signed by
  `core/secrets.sign_state` (the Telegram id and the time, valid 15 min).
  Google comes back to `/oauth/callback`; `complete_link` checks the state,
  exchanges the code, stores the refresh token encrypted (Fernet,
  `CALENDAR_KEY`), saves the calendar list (the primary one synced, new
  events go there), opens push channels, tells the user, then sends the
  bot's upcoming events to Google and syncs.
- **Bot → Google** (`push`, called by `handlers/events.to_google` after
  every create, edit, move, skip and cancel): insert, patch or delete in the
  event's calendar (new ones: the account's `default_calendar_id`). It sets
  `pending_push` first and clears it with the new `etag`; if Google can't be
  reached it stays set, and `sync_user` sends pending events first. Without
  an end, Google gets one hour (all day: the day), but the bot doesn't store
  it. Skipped days go as EXDATEs.
- **Google → bot** (`sync_calendar`): `events.list` with the calendar's
  sync token (all events the first time; a 410 starts over), repeating
  events before their exceptions. `apply` creates, updates or cancels the
  bot's copy, skipping it when the `etag` is the one the bot already has
  (its own change coming back) or when the bot's change is newer and still
  pending. An exception (`recurringEventId`) cancels or moves one occurrence
  of its parent (`skipped`, `moved`). Every change runs `follow`, so
  reminders move, and cancelling cancels them. One-offs that ended over a
  day ago aren't imported the first time. If any item fails to apply, the
  sync token isn't advanced, so the next sync gets those changes again (the
  applied ones are skipped by their `etag`); after 3 tries an item is given up
  on (logged), so one broken event can't stall a calendar. An unexpected
  failure sending one pending event is logged and the sync goes on.
- **One at a time per user**: `sync_user` and `push` take a per-user
  `asyncio.Lock`, so a sync can't import an event the bot is inserting
  (Google has it, the bot doesn't know its id yet), and a burst of push
  notifications syncs one after the other. Inside a sync, sending doesn't take
  it again (`_syncing`).
- **Gone means gone**: an event imported from Google (`source` is
  `MessageSource.GOOGLE`) that is cancelled (in Google, in the bot, or with
  🗑 Remove them) is deleted (`EventRepository.delete`; its reminders stay
  cancelled, unlinked), once Google knows: `cancel_with_reminders` deletes it
  unless the push is still pending, and `_send` does when it gets there. The
  bot's own events stay as cancelled rows.
- **When**: `/google/push` (`on_push`, checked against the channel's token;
  Google's first "sync" message is ignored) syncs that calendar;
  `maybe_sync` at the start of `handle_text`, 📅 Events and 📋 My reminders
  syncs if the last one is 5 minutes old (`GoogleRepository.claim_poll`),
  waiting at most 8 s; `jobs/calendar.daily` renews channels expiring within
  2 days and syncs everyone.
- **Expired login**: `GoogleAuthError` (refresh refused, 401, or a missing
  scope) → `expire`: status `expired`, one message with 🔗 Link again, a
  warning line on 📅 Events (`warning`), no syncing; `push` marks changes
  pending for later. Linking again resets the status and keeps the sync tokens.
- **Screens and buttons** (`gcal:<CalendarAction>[:<id|all>]`, the id of a
  `google_calendars` row): ⬜/✅ `tgl`, 📥 `def` (only calendars the user can
  write to), 🔄 `sync`, 🔓 `unl`, then 📌 `keep` / 🗑 `rm` for a calendar or
  `all` (unlink: also revokes the token and deletes the account rows).
  Keeping detaches the events (`EventRepository.detach`): `external_source`
  becomes None but the Google ids stay, so nothing is sent for them, and
  syncing that calendar again (or linking again) links them up instead of
  importing copies.
- **Setup mistakes aren't the user's**: only Google's `invalid_grant` is an
  expired login; any other refusal from the token endpoint (`invalid_client`:
  a wrong secret) is `GoogleUnavailable`, so nobody is warned or marked
  expired. A `CALENDAR_KEY` that isn't a valid Fernet key turns the feature
  off (`config.calendar_configured`, logged once).

Tests fake Google with an `httpx.MockTransport` (`tests/test_calendar.FakeGoogle`).

## Enums

Use an enum instead of loose strings for any fixed set of values. **All
enums live in `enums.py`**, so they are easy to find and change; add new
ones there too.

| Enum                                    | For |
| --------------------------------------- | --- |
| `ReminderStatus` (+ `ACTIVE_STATUSES`)  | reminder lifecycle; stored as its value in `reminders.status`, a `VARCHAR(16)` (non-native SQLAlchemy `Enum` in `db/models/reminder.py`) |
| `RepeatKind`                            | the kind of repeat the parser found |
| `ReplyCommand`                          | what a reply to a reminder message asks for (`core/replies.py`) |
| `Awaiting`                              | what the next typed message answers |
| `IntentName`                            | free-text intents; stored in `failed_messages.intent` |
| `MessageSource`                         | typed or voice; in `reminders.source` and `failed_messages.source`; `events.source` is `google` for an imported event |
| `FailureReason`, `FailureStatus`        | `failed_messages.reason` and `.status` (open, fixed, ignored) |
| `ContactStatus`                         | `contacts.status`: pending (asked by @username), accepted, or declined (a note not to ask again) |
| `RequestResult`                         | what asking by @username did (`ContactRepository.request`) |
| `InviteResult`                          | what opening an invite did (`ContactRepository.use_invite`) |
| `EventStatus`                           | `events.status`: active or cancelled |
| `GoogleStatus`                          | `google_accounts.status`: linked, or expired (link again) |
| `ExternalSource`                        | `events.external_source`: where it's synced (#22) |
| `Callback`, `CallbackPrefix`, `ReminderAction`, `OptionAction`, `PeopleAction`, `EventAction`, `CalendarAction` | callback data of every button |

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
| `users`         | `telegram_id`, `timezone`, `first_name` and `username` (from Telegram, refreshed on every update by `remember_profile` in `handlers/ui.py`) |
| `reminders`     | creator/target user, chat, text, `remind_at`, `next_fire_at`, `status`, `fire_count`, `last_message_id`, `recurrence` (`Text`), `request` and `source` (the message it was made from), `event_id` and `event_offset` (minutes from the event's start) if it follows an event |
| `user_settings` | `(user_id, key)` → JSON value, only non-defaults |
| `contacts`      | `owner_user_id` may remind `contact_user_id`; `name` (what the owner calls them, unique per owner, case-insensitive, checked in code), `status`, `created_at`, `accepted_at`; unique `(owner, contact)` |
| `contact_requests` | log of requests by @username: `owner_user_id`, `contact_user_id`, `created_at` (for the daily limits) |
| `invites`       | `token` (the link), `owner_user_id`, `created_at`, `expires_at`, `used_at`, `used_by_user_id` |
| `failed_messages` | user, `text`, `source`, `reason`, `intent`, `bot_understood` (JSON), optional `reminder_id` or `event_id`, `status`, `created_at`, `fixed_at`, `note`, `fix_pr` |
| `events`        | user, `title`, `starts_at` (the first occurrence), `ends_at`, `all_day`, `timezone`, `recurrence` (an RRULE), `skipped`, `moved`, `status`, `request`, `source`, `created_at`, `updated_at`, and for Google `external_source`, `external_calendar_id`, `external_id`, `etag`, `external_updated_at`, `pending_push` |
| `google_accounts` | per user: `refresh_token` (encrypted), `status`, `default_calendar_id`, `linked_at`, `last_poll_at` |
| `google_calendars` | a user's Google calendars: `calendar_id`, `summary`, `time_zone`, `primary`, `writable`, `selected`, `sync_token`, and the push channel (`channel_id`, `channel_token`, `channel_resource_id`, `channel_expires_at`) |

## Tests

```bash
pip install -r requirements-dev.txt
python -m pyflakes bot.py config.py enums.py core db handlers jobs scripts services tests autofix
pytest
```

pyflakes catches undefined names and unused imports, which tests can miss.

Tests use a throwaway SQLite database (`tests/conftest.py`) with all
migrations applied; the `chat` fixture (a user with a timezone) is there too. CI runs pyflakes and the tests on every pull request
and before every deploy. Parser, recurrence, quiet hours and settings tests are pure;
delivery tests use a fake bot (`tests/test_recurrence.FakeBot`);
`tests/test_handlers.py`, `tests/test_events.py`, `tests/test_calendar.py`
`tests/test_errors.py` (with a fake clock)
and `tests/test_voice.py` drive the handlers with mocked Telegram objects; `tests/test_numbers.py` covers spoken phrases.

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
Set `typos=False` for a phrase that's one letter from common words.

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
