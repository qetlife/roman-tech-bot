# User guide

Everything you can do with the bot, and how. For how the code works, see
[development.md](development.md).

- [Getting started](#getting-started)
- [Menus](#menus)
- [Reminders](#reminders)
  - [Creating a reminder](#creating-a-reminder)
  - [Time expressions](#time-expressions)
  - [Recurring reminders](#recurring-reminders)
  - [When a reminder is due](#when-a-reminder-is-due)
  - [Listing, editing and cancelling](#listing-editing-and-cancelling)
- [Settings](#settings)
  - [🆔 My ID](#-my-id)
  - [🌍 Timezone](#-timezone)
  - [💤 Snooze options](#-snooze-options)
  - [🔁 Repeat interval](#-repeat-interval)
  - [🌙 Quiet hours](#-quiet-hours)
- [Good to know](#good-to-know)

## Getting started

1. Open a private chat with the bot and send `/start`. This registers you
   and shows the menu.
2. Create your first reminder, e.g. type “remind me in 2 hours to call mom”.
3. The first time, the bot asks for your timezone. Pick one or type a city.

Commands:

| Command  | What it does                     |
| -------- | -------------------------------- |
| `/start` | Registers you and shows the menu |
| `/menu`  | Shows the menu                   |

## Menus

The menu is a single message whose buttons update in place as you navigate.

```
Menu
├── ⏰ Reminders
│   ├── ➕ New                 create a reminder
│   ├── 📋 My reminders        list and cancel upcoming reminders
│   └── ⚙️ Settings            → ⏰ Reminder settings (below)
└── ⚙️ Settings
    ├── 🆔 My ID               your Telegram ID
    ├── 🌍 Timezone            change your timezone
    └── ⏰ Reminders           ⏰ Reminder settings:
        ├── 💤 Snooze options
        ├── 🔁 Repeat interval
        └── 🌙 Quiet hours
```

`↩️ Back` always returns to the screen you came from; ⏰ Reminder settings
returns to whichever menu you opened it from.

## Reminders

### Creating a reminder

Either type a message that starts with a trigger phrase, or press
`⏰ Reminders → ➕ New` and send the time and text.

Trigger phrases (case-insensitive; “please”, “hey”, “can you” etc. in front
are fine):

| To…               | Start the message with                                                                    |
| ----------------- | ----------------------------------------------------------------------------------------- |
| create a reminder | “remind me”, “set a reminder”, “set reminder”, “create a reminder”, “add a reminder”, “new reminder” |
| list reminders    | “my reminders”, “show my reminders”, “show reminders”, “list reminders”, “list my reminders”, “reminders” |

The time can come before or after the text:

- “remind me **in 2 hours** to call mom”
- “remind me to pay rent **tomorrow at 9**”
- “set a reminder **for friday 18:00**: dentist”
- “remind me **every day at 9** to take pills”

Words like “to”, “that”, “about” or a colon between the time and the text are
dropped. The bot replies with what it understood:

```
⏰ Got it: call mom
🗓 Today, 16:30 (in 2 h)
[↩️ Undo] [✏️ Edit]
```

If it can't understand the time, it says so and asks you to send it again.

### Time expressions

All times are in your timezone.

| Kind            | Examples |
| --------------- | -------- |
| In some time    | “in 2 hours”, “in two hours”, “in 30 min”, “in 1.5 hours”, “in 1h30m”, “in half an hour”, “in an hour and a half”, “in 3 days”, “in a week” |
| At a time       | “at 9”, “at 9am”, “at 9:30pm”, “at 18:00”, “18:00”, “noon”, “midnight” |
| On a day        | “today”, “tonight”, “tomorrow”, “day after tomorrow”, “monday”, “on friday”, “next friday”, “next week” |
| On a date       | “24.12”, “24/12”, “2026-12-24”, “dec 24”, “24th of december 2026” |
| Part of the day | “morning” (09:00), “afternoon” (15:00), “evening” (19:00), “night” (21:00), “tonight” (20:00) |
| Combined        | “tomorrow at 9”, “friday 18:00”, “at 9 tomorrow”, “tomorrow morning”, “on dec 24 at 10am” |

Rules:

- A day without a time means **09:00** (“tomorrow” = tomorrow 09:00).
- A bare “at 9” means the **next** 09:00 or 21:00, whichever comes first.
  “9:00”, “09” and “18:00” are taken as written.
- Before 04:00, “tomorrow” means the coming day (at 01:00 on Sunday,
  “tomorrow at 9” is Sunday 09:00).
- A weekday that has already passed today means next week; a date that has
  passed this year means next year.
- Times in the past are rejected.

### Recurring reminders

Add a repeat to any reminder:

| Repeats             | Examples |
| ------------------- | -------- |
| Daily               | “every day at 9”, “daily”, “every morning”, “every evening at 7” |
| On weekdays         | “every weekday at 8:30”, “on weekdays”, “every weekend”, “weekends” |
| On certain days     | “every monday”, “every mon and thu 18:00”, “mondays and fridays”, “every week” (today's weekday) |
| Every few minutes/hours | “every 2 hours”, “every 30 minutes”, “every hour”, “every 1h30m” |
| Every few days/weeks | “every 3 days”, “every other day at 20:00”, “every 2 weeks at 7am” |
| Monthly             | “monthly”, “every month on the 15th”, “on the 1st of every month”, “every 1st at 10” |

Rules:

- Without a time, a repeat is at **09:00**. “every day at 9” is 09:00, not
  21:00 (“every evening at 7” is 19:00).
- “Every N minutes/hours” starts N minutes/hours from now and must be at
  least **15 minutes** apart. It can't have a time of day.
- “Every N days/weeks” starts at the given time (09:00 if none), today if
  it's still ahead, otherwise tomorrow.
- “Monthly” without a day uses today's day of the month. In shorter months,
  the 29th–31st become the last day of the month.
- Times stay in local time across daylight saving changes: “every day at 9”
  is always 09:00.
- Occurrences of “every N minutes/hours” that fall in your
  [quiet hours](#-quiet-hours) are skipped.

The confirmation and the list show the repeat, e.g. `🔁 weekdays at 08:30`.

### When a reminder is due

The bot sends:

```
⏰ call mom
[✅ OK] [💤 10 min] [💤 1 h]
```

- **✅ OK**: done. A recurring reminder moves on to its next occurrence and
  the message shows when that is (`Next: Tomorrow, 09:00`).
- **💤 Snooze**: sends it again after that long. The buttons are your
  [snooze options](#-snooze-options).
- **No answer**: the bot sends it again every
  [repeat interval](#-repeat-interval) (5 minutes by default), with
  “🔁 Still waiting for your OK.”, and deletes the previous copy so only
  one is on screen. Repeats pause during [quiet hours](#-quiet-hours).
- **Still no answer after 24 hours**: the reminder is marked
  `❌ Missed: no response for 24 h`. A recurring reminder is marked missed
  when its next occurrence comes (or after 24 hours) and continues with the
  next one.

If the bot was offline, anything that came due meanwhile is sent when it is
back. For a recurring reminder, only the latest due occurrence is sent.

### Listing, editing and cancelling

- **List**: “my reminders” or `⏰ Reminders → 📋 My reminders` shows your
  upcoming reminders with their time and repeat.
- **Cancel**: tap `❌` next to a reminder in the list, or `↩️ Undo` right
  after creating it. Cancelling a recurring reminder stops all future
  occurrences.
- **Edit**: tap `✏️ Edit` on the confirmation and send the new time and text,
  e.g. “tomorrow at 10 to call mom”. This can also add or remove a repeat.

If a reminder you edit or cancel is currently waiting for your OK, its old
message loses its buttons.

## Settings

Open `⚙️ Settings` from the menu. Reminder settings are also under
`⏰ Reminders → ⚙️ Settings`. Each screen shows the current value; a ✅ marks
the selected option. `♻️ Default` restores the default.

### 🆔 My ID

`⚙️ Settings → 🆔 My ID` shows your Telegram user ID.

### 🌍 Timezone

`⚙️ Settings → 🌍 Timezone`. All reminder times are in this timezone.

- Pick a button (Europe/Lisbon, Europe/Kyiv, Europe/Warsaw, Europe/Berlin, Europe/London,
  America/New_York, UTC), or type a city (“Kyiv”, “New York”), an IANA
  name (“Europe/Kyiv”) or an offset (“UTC+3”).
- Asked automatically before your first reminder.
- Changing it keeps the clock time of daily, weekly and monthly reminders:
  “every day at 9” is then 09:00 in the new timezone. One-off reminders and
  “every N minutes/hours/days” keep their moment in time, so their local
  time shifts.

### 💤 Snooze options

`⚙️ Settings → ⏰ Reminders → 💤 Snooze options`. The snooze buttons on a due
reminder.

| | |
| --- | --- |
| Default | 10 min · 1 h |
| Presets | 5 min · 15 min · 1 h — 10 min · 1 h — 10 min · 30 min · 2 h |
| Custom  | Up to 3 options, each 1 minute – 24 hours. Send e.g. “10m, 1h, 3h”, “5, 15, 60” (minutes) or “10 min, 1 hour” |

### 🔁 Repeat interval

`⚙️ Settings → ⏰ Reminders → 🔁 Repeat interval`. How often an unanswered
reminder is sent again until you press OK.

| | |
| --- | --- |
| Default | every 5 min |
| Options | 2 min, 5 min, 10 min, 15 min, 30 min, 1 h |

### 🌙 Quiet hours

`⚙️ Settings → ⏰ Reminders → 🌙 Quiet hours`. A nightly window without
interruptions:

- “Every N minutes/hours” occurrences in it are **skipped**. For example,
  with “every 2 hours” and 00:00–07:00, the next one after 23:30 is 07:30.
- Unanswered reminders **stop repeating** and are sent again when quiet
  hours end.
- Reminders set for a **specific time** (including “every day at 3:00”) still
  go off.

| | |
| --- | --- |
| Default | 00:00–07:00 |
| Presets | 00:00–07:00, 23:00–07:00, 22:00–08:00, 🔔 Off |
| Custom  | Send e.g. “23:00-07:00”, “22 to 8” or “off”. Start and end must differ; windows across midnight are fine |

## Good to know

- Typed messages work in **private chats** only.
- Only the person a reminder is for can press its buttons.
- If the bot doesn't understand a message, it suggests an example and
  `/menu`.
- A trigger phrase always works, even while the bot is waiting for an
  answer to a question (e.g. during ✏️ Edit).
