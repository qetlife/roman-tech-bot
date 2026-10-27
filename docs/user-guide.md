# User guide

Everything you can do with the bot, and how. For how the code works, see
[development.md](development.md).

- [Getting started](#getting-started)
- [Menus](#menus)
- [Voice messages](#voice-messages)
- [🌐 Web app](#-web-app)
- [Reminders](#reminders)
  - [Creating a reminder](#creating-a-reminder)
  - [Time expressions](#time-expressions)
  - [Recurring reminders](#recurring-reminders)
  - [When a reminder is due](#when-a-reminder-is-due)
  - [Listing, editing and cancelling](#listing-editing-and-cancelling)
  - [“Move it”, “cancel that”: following up](#move-it-cancel-that-following-up)
  - [When the bot gets it wrong](#when-the-bot-gets-it-wrong)
- [📅 Events](#-events)
  - [Adding an event](#adding-an-event)
  - [Reminders before an event](#reminders-before-an-event)
  - [Moving, editing and cancelling events](#moving-editing-and-cancelling-events)
  - [📅 Google Calendar](#-google-calendar)
- [👥 People](#-people)
  - [Reminding someone](#reminding-someone)
- [Settings](#settings)
  - [🆔 My ID](#-my-id)
  - [🌍 Timezone](#-timezone)
  - [💤 Snooze options](#-snooze-options)
  - [🔁 Repeat interval](#-repeat-interval)
  - [🌙 Quiet hours](#-quiet-hours)
  - [📣 Updates from people](#-updates-from-people)
- [Good to know](#good-to-know)

## Getting started

1. Open a private chat with the bot and send `/start`. This registers you
   and shows the menu.
2. Create your first reminder, e.g. type “remind me in 2 hours to call mom”.
3. The first time, the bot asks for your timezone. Pick one or type a city.

Anything you can type, you can also say in a [voice message](#voice-messages).

Commands:

| Command  | What it does                     |
| -------- | -------------------------------- |
| `/start` | Registers you and shows the menu |
| `/menu`  | Shows the menu                   |
| `/calendar` | [Google Calendar](#-google-calendar): link it, pick calendars, unlink |
| `/failed` | Admin only: [failed messages](#when-the-bot-gets-it-wrong) |

## Menus

The menu is a single message whose buttons update in place as you navigate.

```
Menu
├── ⏰ Reminders
│   ├── ➕ New                 create a reminder
│   ├── 📋 My reminders        list and cancel upcoming reminders
│   └── ⚙️ Settings            → ⏰ Reminder settings (below)
├── 📅 Events                  your upcoming events
│   ├── 📅 <title>             ⏰ add a reminder · ✏️ Edit · ⏭ Skip · 🗑 Cancel event
│   └── ➕ New                 add an event
├── 👥 People                  who you can remind, and who can remind you
│   ├── 👤 <name>              ✏️ Rename · 🗑 Remove
│   ├── 📨 <name>              🚫 Stop their reminders
│   └── ➕ Invite              a link to send, or their @username
└── ⚙️ Settings
    ├── 🆔 My ID               your Telegram ID
    ├── 🌍 Timezone            change your timezone
    ├── ⏰ Reminders           ⏰ Reminder settings:
    │   ├── 💤 Snooze options
    │   ├── 🔁 Repeat interval
    │   ├── 🌙 Quiet hours
    │   └── 📣 Updates from people
    └── 📅 Calendar            link Google Calendar, pick calendars, unlink
```

`↩️ Back` always returns to the screen you came from; ⏰ Reminder settings
returns to whichever menu you opened it from.

## Voice messages

Send a voice message instead of typing. The bot transcribes it and handles
the words exactly as if you had typed them: create reminders, list them,
answer its questions (✏️ Edit, timezone, custom snooze options or quiet
hours).

```
🎤 (voice) “remind me tomorrow at nine thirty to call mom”
🎙 “remind me tomorrow at nine thirty to call mom”
⏰ Got it: call mom
🗓 Tomorrow, 09:30 (in 18 h)
```

The first reply shows what the bot heard, so a misheard word is obvious; fix
it with ✏️ Edit or send it again.

- Two common mishearings are fixed when a message isn't understood
  otherwise: “to borrow” for “tomorrow”, and “too” for “to” before the text
  (“to borrow at nine am too call the bank” is “call the bank”, tomorrow
  09:00).

- Speak naturally; numbers can be words: “in twenty five minutes”, “at half
  past six”, “at a quarter to five”, “at nine thirty pm”, “on the fifteenth”
  (see [Time expressions](#time-expressions)).
- English only, up to 2 minutes per message.
- Transcription runs on the bot's own server (offline, with Vosk): your audio
  is never sent to Google or any other company.
- If voice isn't available, the bot says so; typing always works.

## 🌐 Web app

The bot as an assistant in a page: it tells you what's left today, what it
can do, and when you ask for something, the steps it took and the result.
Type, or hold 🎙 and speak, and it answers out loud. Two ways in:

- **In Telegram**: tap **Open app** next to the text box in the bot's chat.
  You're logged in already. You can add it to your phone's home screen from
  its ⋯ menu.
- **In a browser**: [app.romanis.xyz](https://app.romanis.xyz), then **Log
  in with Telegram**.

It's the same bot: the same phrases, questions and buttons (What time?, ↩️
Undo, ✏️ Edit, 👎 Wrong), and the same conversation, so “move it to 10” works
on a reminder you just made in Telegram, and the other way round.

- **The briefing**, when you open it: a greeting, what's left today (and
  what's next, and how soon), and how tomorrow starts.
- **What I can do**: one tile per skill (⏰ Reminders, 📅 Events, 👥 People,
  and 🔄 Google Calendar where it's set up), each with an example. Tap one
  to put the example in the text box, to change or send.
- **Asking**: type and send, or **hold 🎙** while you speak and let go. Your
  message (or what it heard) shows on the right, then:
  - **the steps** it took, e.g. “Understood: a reminder, tomorrow at
    09:00”, “Saved”, “Added to Google Calendar”;
  - **the result**: a reminder or event as a card, with its buttons (↩️
    Undo, ✏️ Edit, 👎 Wrong, ⏰ a reminder before an event); other replies
    as text.

  Scroll up for what you asked before; tap **Assistant** at the top to go
  back to the briefing.
- **🔊 Spoken replies**: the bot reads its replies aloud. Tap the speaker to
  switch that off; the text is always there. On an iPhone in silent mode you
  may not hear it.
- **📅 The next 7 days** (the calendar button at the top): your reminders
  and events today and in the next 6 days.
- It follows Telegram's light or dark look (in a browser, your system's).

Good to know:

- **Reminders still arrive in Telegram**, with their buttons, also when the
  app is closed or your phone is locked. Tap **Open app** to go back.
- The app only runs while it's open; it starts at the briefing when you open
  it again (what you made is all there, in 📅 the next 7 days and in
  Telegram).
- No AI: it understands exactly the phrases the Telegram bot does.
- Like voice messages, your recordings and the bot's spoken replies stay on
  the bot's own server (offline speech, with Vosk and Piper).
- Logging in shows the app who you are (your Telegram ID, name and
  @username), nothing else. Everyone sees only their own reminders and events.

## Reminders

### Creating a reminder

Either type a message that starts with a trigger phrase, or press
`⏰ Reminders → ➕ New` and send the time and text.

Trigger phrases (case-insensitive; “please”, “hey”, “can you”, “also” etc. in front
are fine; small typos too, see [Typos](#typos)):

| To…               | Start the message with                                                                    |
| ----------------- | ----------------------------------------------------------------------------------------- |
| create a reminder for someone in [👥 People](#reminding-someone) | “remind anna …”, “remind @anna …” |
| create a reminder | “remind me”, “remind”, “set a reminder”, “set reminder”, “create a reminder”, “add a reminder”, “new reminder”, “don't let me forget”, “don't forget” |
| list reminders    | “my reminders”, “show my reminders”, “show reminders”, “list reminders”, “list my reminders”, “reminders” |
| list one day      | “what do I have tomorrow?”, “what's on friday?”, “my reminders on dec 24”, “anything on monday?” (repeats included, also ones that already went off today); all but “my reminders on …” also show that day's [events](#-events) |
| cancel a reminder | “cancel the dentist reminder”, “delete my reminder to call mom”, “remove …”: finds the one whose text has those words and asks you to confirm with ❌; if several or none match, it shows them to pick with ❌. If one of your [events](#-events) has that name (“cancel padel”), it's the event, unless you say “reminder” |
| see what the bot can do | “what can you do?”, “what else can you do”, “what can I ask you”, “how can you help”, “what can you help with”: each skill with an example |
| set your timezone | “set my timezone to Lisbon”, “my timezone is UTC+3”, “change my timezone” (asks) |
| flag the last reminder (or event) as wrong | “that's wrong”, “that is wrong”, “that was wrong”, “that's not right”, “you got that wrong”, “wrong reminder”, “save the last one as failed”, “mark the last one as failed”, “save it as failed”, “mark as failed” |

Tapping ❌ on one of these lists (one day, or “which one?”) cancels that
reminder and shows your full list of what's left.

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
[↩️ Undo] [✏️ Edit] [👎 Wrong]
```

If half is missing, the bot asks for it and puts the two together:

- **No time** (“remind me to call mom”): it asks
  `⏰ When should I remind you: “call mom”?`; answer with just the time
  (“tomorrow at 9”, or a wait such as “10 minutes”). If the answer isn't a time it asks again.
- **No text** (“remind me tomorrow at 12”, or just “tomorrow at 12” on its
  own): it asks `⏰ tomorrow at 12: what should I remind you about?`; answer
  with the text (“call the bank”).
- **A day but no time** (“remind me friday dentist”, “every monday to call
  mom”): the time is never guessed. It asks
  `⏰ What time should I remind you: “dentist”?` with
  `[🌅 Morning 09:00] [☀️ Afternoon 14:00] [🌙 Evening 19:00]`; tap one, or
  type a time (“10:30”, “at 9”, “evening”) or a whole new one (“tomorrow at
  10”).
- **“every week” without a day** (“remind me every week to water the
  plants”): it asks which day, with `[Mon] … [Sun]`, then the time if that's
  missing too. One question at a time.

```
You: remind me friday dentist
Bot: ⏰ What time should I remind you: “dentist”?
     [🌅 Morning 09:00] [☀️ Afternoon 14:00] [🌙 Evening 19:00]
You: 10
Bot: ⏰ Got it: dentist
     🗓 Fri 30 Oct, 10:00 (in 4 d)
```

While it asks, you can move on:

- “never mind”, “cancel” or “forget it” drops the question
  (`OK, dropped the reminder “dentist”.`); for “What time?”, “Which day?”
  and “When?”, so do “no”, “stop” and “skip”. (Elsewhere they can be the
  answer: a reminder to “stop”, or “no” to switch quiet hours off.)
- Something that fits as an answer is the answer.
- A command of its own (“what do I have tomorrow?”, “my reminders”, “cancel
  the second one”) is done, and the question dropped: `Dropped: the reminder
  “dentist”.` A new “remind me …” just replaces the question. “make it …”
  and “also …” are taken as the answer then.
- “that's wrong” saves the message it asked about as failed: asking was
  the mistake. If it can't understand the time in some other way (a repeat
under 15 minutes, a time that has passed, more than 100 years away), it says
so and asks you to send it again.

### Time expressions

All times are in your timezone.

| Kind            | Examples |
| --------------- | -------- |
| In some time    | “in 2 hours”, “in two hours”, “in 30 min”, “in 1.5 hours”, “in 1h30m”, “in half an hour”, “in an hour and a half”, “in 3 days”, “in a week”, “in a fortnight” |
| At a time       | “at 9”, “at 9am”, “at 9:30pm”, “at 18:00”, “18:00”, “at 21.20”, “at 9.20pm”, “noon”, “midnight”, “at 9 o'clock” |
| Spoken times    | “at nine”, “at nine thirty”, “at nine oh five”, “at half past six”, “at a quarter past nine”, “at quarter to five”, “at ten to five”, “at nine p m” |
| On a day        | “today”, “tonight”, “tomorrow”, “day after tomorrow”, “monday”, “on friday”, “next friday”, “next week”, “next month” (the same day), “end of the month” (its last day) |
| On a date       | “24.12”, “24/12”, “2026-12-24”, “dec 24”, “24th of december 2026”, “december twenty fourth”, “on the 15th” / “on the fifteenth” (the next 15th) |
| Part of the day | “morning” (09:00), “afternoon” (15:00), “evening” (19:00), “night” (21:00), “tonight” (20:00) |
| Combined        | “tomorrow at 9”, “friday 18:00”, “at 9 tomorrow”, “tomorrow morning”, “on dec 24 at 10am”, “tonight at 9”, “at 7 in the evening”, “tomorrow at 9 in the morning” |

Numbers can be written as words everywhere (“in twenty five minutes”, “every
two hours”), which is what voice messages produce.

Rules:

- The day and the time can be on either side of the text: “friday dentist
  at 10”, “at 9 to call mom tomorrow”, “every monday to call mom at 10”.
- A reminder with a day but no time isn't guessed: the bot
  [asks what time](#creating-a-reminder). (For an [event](#adding-an-event),
  a day alone is all day.)
- A bare “at 9” means the **next** 09:00 or 21:00, whichever comes first.
  So do spoken times like “at nine thirty” or “at half past six”. Typed
  “9:30”, “09” and “18:00” are taken as written.
- A dot works like a colon in times: “at 21.20” is 21:20. A number that
  could also be a date stays a date unless it follows “at”: “10.11” is
  10 November, “at 10.11” is 10:11 (and “at 24.12”, not a time, is 24
  December).
- “tonight”, “in the afternoon”, “in the evening” and “at night” make the
  time pm: “tonight at 9” and “at 7 in the evening” are 21:00 and 19:00.
- “On the 15th” without a month means the next 15th (this month or next;
  months without that day are skipped).
- Before 04:00, “tomorrow” means the coming day (at 01:00 on Sunday,
  “tomorrow at 9” is Sunday 09:00).
- A weekday that has already passed today means next week; a date that has
  passed this year means next year.
- Times in the past are rejected, also on their own (“today at 9” in the
  afternoon, “yesterday at 9”).

#### Typos

Small typos in trigger phrases and time words are fixed: “remid me”, “set a
remider”, “tomorow”, “tommorow”, “wensday”, “teusday”, “saterday”,
“febuary”, “evry day”, “in 10 minuts”, “in fourty minutes”, and the
shorthand “tonite”, “tmrw”.

- Only words the bot knows are fixed. Your reminder text is kept exactly as
  you typed it: “remind me to call Mondy tomorow” is “call Mondy”, tomorrow.
- A message that makes sense as written is never “fixed”: in “remind me to
  eat a sundae at 9”, “sundae” stays.
- Words under 4 letters aren't guessed (“tue”, “mon” and “jan” are still
  fine as abbreviations), and neither is a typo that could mean two
  different things.

### Recurring reminders

Add a repeat to any reminder:

| Repeats             | Examples |
| ------------------- | -------- |
| Daily               | “every day at 9”, “daily”, “every morning”, “every evening at 7” |
| On weekdays         | “every weekday at 8:30”, “on weekdays”, “every weekend”, “weekends” |
| On certain days     | “every monday”, “every mon and thu 18:00”, “mondays and fridays”, “every week” (asks which day) |
| Every few minutes/hours | “every 2 hours”, “every 30 minutes”, “every hour”, “every 1h30m” |
| Every few days/weeks | “every 3 days”, “every other day at 20:00”, “every 2 weeks at 7am”, “every fortnight”, “fortnightly” |
| Every other weekday | “every other tuesday at 19”, “every 2nd tuesday”, “every second thursday” (every two weeks, from the next one) |
| Monthly             | “monthly”, “every month on the 15th”, “on the 1st of every month”, “every 1st at 10” |
| Monthly on a weekday | “every last friday of the month”, “the first monday of every month at 10”, “every 2nd tuesday of the month”, “every last friday” (a 5th weekday skips months without one) |

Rules:

- Without a time, the bot asks what time (“every evening” is 19:00, so it
  doesn't ask). “every day at 9” is 09:00, not 21:00 (“every evening at 7”
  is 19:00).
- “Every N minutes/hours” starts N minutes/hours from now and must be at
  least **15 minutes** apart. It can't have a time of day.
- “Every N days/weeks” starts at the given time (asked if none), today if
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

**Replying** to the reminder message works like its buttons (typed or by
voice):

| Reply | Does |
| --- | --- |
| “done”, “ok”, “👍” | ✅ OK |
| “snooze”, “later”, “snooze 20 min”, “snooze for an hour” | 💤 for that long; without a time, your first snooze option |
| “move it to 10”, “move to tomorrow at 9”, “make it 18:30” | sets a new time; for a recurring reminder only this time moves |
| “cancel”, “delete it” | cancels it |

This works while the reminder is going off (waiting for ✅ OK); once it's
snoozed or answered, the old message is just a message. Any other reply is
handled like a normal message, so “remind me …” still works.

### Listing, editing and cancelling

- **List**: “my reminders” or `⏰ Reminders → 📋 My reminders` shows your
  upcoming reminders with their time and repeat, including those people
  sent you (“📨 from Roman”), and then, under **For others**, the ones you
  set for people in [👥 People](#reminding-someone).
- **Cancel**: tap `❌` next to a reminder in the list, or `↩️ Undo` right
  after creating it. Cancelling a recurring reminder stops all future
  occurrences.
- **Edit**: tap `✏️ Edit` on the confirmation and send the new time and text,
  e.g. “tomorrow at 10 to call mom”. This can also add or remove a repeat.
  It needs a time of day: with only a day, the bot asks you to add one.

If a reminder you edit or cancel is currently waiting for your OK, its old
message loses its buttons.

### “Move it”, “cancel that”: following up

For **10 minutes after your last message**, the bot remembers what you
talked about, so you don't have to reply to a message or say its name:

- **“it” / “that”** is the reminder or [event](#-events) the bot last made,
  moved or edited for you.
- **“the second one”** (“the first”, “number 3”, “the last one”) is from the
  last numbered list it showed: “my reminders”, “what do I have tomorrow?”
  (its reminders), “my events”.

| To…  | Say | |
| ---- | --- | --- |
| move it | “move it to 10”, “make it 9:30”, “change it to tomorrow”, “push the second one to friday at 10” | What you don't say stays: “to 10” keeps the day, “to friday” the time. A repeating reminder moves just this time. |
| cancel it | “cancel that”, “delete it”, “remove the first one” | A reminder is cancelled at once: `🗑 Cancelled: call mom [↩️ Undo]`. An event asks first (`Cancel “padel”?`), since its reminders and Google Calendar go with it. |
| copy it | “and the same next week”, “also on thursday”, “same time tomorrow” | A new one like it at that time (“next week” is a week after it). Not for repeats. |

```
You: remind me friday at 9 to call mom
Bot: ⏰ Got it: call mom …
You: make it 10
Bot: ⏰ Moved: call mom
     🗓 Fri 30 Oct, 10:00 (in 4 d)
You: and the same next week
Bot: ⏰ Got it: call mom
     🗓 Fri 6 Nov, 10:00 (in 11 d)
```

After 10 minutes, “it” means nothing any more and the bot asks which one;
say its name (“cancel the dentist reminder”, “move padel to 20:00”) or reply
to its message. Only whoever made a reminder can move or copy it; one sent to
you can be cancelled.

### When the bot gets it wrong

The bot keeps a list of messages it didn't handle well, so its phrasing can
be improved:

- **It didn't understand**: anything it answers with “I didn't get that” or
  “I couldn't understand when” is saved automatically, typed or voice.
- **It understood it wrong** (e.g. the wrong time): tap `👎 Wrong` on the
  confirmation, or say “that's wrong” / “save the last one as failed”. The
  bot saves your message together with what it made of it and **deletes the
  reminder**; send it again if you still need it. “The last one” is the last
  reminder (or [event](#-events)) the bot created or edited from your
  messages; if your last message wasn't understood at all, it's already saved.

```
⏰ Got it: at 21.20 to call mom
🗓 Thu 22 Oct, 09:00 (in 4 d)
[↩️ Undo] [✏️ Edit] [👎 Wrong]
```

After tapping `👎 Wrong`, the confirmation becomes:

```
👎 Deleted: at 21.20 to call mom
Saved as failed, so I can learn it. Send it again if you still need it.
```

To fix a reminder instead of deleting it, use `✏️ Edit`.

The admin (set with `ADMIN_TELEGRAM_ID`) sees the open ones with `/failed`,
newest first. `✅ <number>` marks one fixed once the bot understands that
phrasing, `🗑 <number>` ignores one that can't be learned (a garbled voice
message, say); neither deletes it. Nobody else can see them.

Most close on their own: after every update the bot tries the messages it
didn't understand again, and marks the ones it now understands fixed. A
message with a fix on the way shows “🔧 Fix waiting in pull request #n”;
one the bot needs a new feature for shows “⏳ Waiting for: …”; tap ✅
on it once that feature is added.

If something breaks on the bot's side, it answers “Sorry, something went
wrong on my side. Try again in a moment.” The error is kept on the bot's own
server (never sent anywhere) for the admin to fix.

## 📅 Events

Events are things that happen at a time: padel on Thursday, the dentist on
Friday, dinner at mom's on Christmas Eve. Reminders can hang off them (“30
min before padel”) and move with them.

### Adding an event

Start the message with a trigger phrase, or press `📅 Events → ➕ New` and
send the time and title. Voice messages work too.

| To…              | Say                                                                                 |
| ---------------- | ----------------------------------------------------------------------------------- |
| add an event     | “event …”, “new event …”, “add event …”, “add an event …”, “create an event …”, “make an event …”, “put … in my calendar”, “add … to my calendar”, “add to my calendar …” |
| list your events | “my events”, “events”, “show my events”, “list events”, “upcoming events”, “my calendar”, “what's on my calendar” (“my events on friday” shows one day) |
| move one         | “move padel to 20:00”, “reschedule padel to friday”, or just “padel is at 20:00 now” |
| cancel one       | “cancel padel”, “cancel event padel”, “delete the event padel”; “cancel padel on thursday” skips one day of a repeating one |
| remind before one | “remind me 30 min before padel to pack the racket” (see [below](#reminders-before-an-event)) |

The time works like a reminder's ([Time expressions](#time-expressions)),
before or after the title, and events can repeat the same way:

- “event **padel on thursday at 21:00**”
- “event **every thursday at 21:00**: padel”
- “put **dinner at mom's on dec 24 at 19:00** in my calendar”
- “event **dentist on friday**”: a day without a time is an **all-day**
  event (also “today”, even late in the day)

```
📅 Added: padel
🗓 Thu 29 Oct, 21:00 (in 6 d)
🔁 every Thu at 21:00

A reminder before it?
[⏰ 15 min before] [⏰ 30 min before] [⏰ 1 h before]
[↩️ Undo] [✏️ Edit] [👎 Wrong]
```

An all-day event offers `⏰ the day before, 09:00` and `⏰ on the day,
09:00` instead. If the time or the title is missing, the bot asks for it
(`📅 When is “padel”?`), like for reminders.

**Without a keyword**: a message with a time and a text but no trigger
phrase, like “padel on thursday at 21:00”, could be either, so the bot asks:

```
“padel”, Thu 29 Oct, 21:00 (in 6 d)
Is this an event or a reminder?
[📅 Event] [⏰ Reminder]
```

An event keeps the clock of the timezone you had when you made it: if you
move to another timezone, “padel at 21:00” is still 21:00 where it was
(shown in your new time). Events can also sync with
[Google Calendar](#-google-calendar).

An event with an end shows it: “Thu 29 Oct, 21:00–22:30”, or “Fri 24 – Sun 26
Oct (all day)” over several days, and it counts as on (in the list and the
agenda) until it ends. Events from Google Calendar have their end; the bot
doesn't ask for one.

### Reminders before an event

Tap one of the ⏰ buttons on the event, or say when, relative to it:

- “remind me 30 min before padel to pack the racket”
- “remind me to stretch 10 minutes after padel”
- “remind me the day before the trip to pack”
- “remind anna 1 hour before padel to bring the balls” (someone in
  [👥 People](#reminding-someone))

Without a text (“remind me 30 min before padel”), the reminder is the
event's title. The event is found by its title (“the”, “my” in front are
fine); if you have no event called that, the bot says so. It can be at most
5 years before or after the event. For a
**repeating** event, it asks:

```
⏰ pack the racket, 30 min before padel: just the next one, or every time?
[1️⃣ Just the next one] [🔁 Every time]
```

```
⏰ Got it: pack the racket
📅 30 min before padel
🗓 Thu 29 Oct, 20:30 (in 6 d)
🔁 30 min before, every Thu at 21:00
```

When it goes off, it says which event it's for:

```
⏰ pack the racket
📅 padel: Today, 21:00 (in 30 min)
[✅ OK] [💤 10 min] [💤 1 h]
```

These reminders **follow the event**: if padel moves to 20:00, the reminder
moves to 19:30; if padel is cancelled, so are its reminders; if one Thursday
is skipped, so is its reminder that day. Editing such a reminder (✏️ Edit, or
“move it to 10” as a reply) makes it an ordinary one that no longer follows
the event.

### Moving, editing and cancelling events

`📅 Events` lists your upcoming events; tap one to see its reminders and:

- **⏰** add a reminder before it,
- **✏️ Edit**: send its new time and title (“padel on friday at 20:00”),
- **⏭ Skip <day>** (repeating events): that one occurrence doesn't happen,
- **🗑 Cancel event**: every occurrence, and its reminders.

**Moving by message**: “move padel to 20:00” keeps the day, “move padel to
friday” keeps the time, “to friday at 20:00” changes both; “move padel to
8” is whichever of 08:00 and 20:00 is closer to its time now. For a
repeating event, a time changes every occurrence's time, a weekday moves a
weekly one to that day, and a repeat (“move padel to every monday at 19:00”)
replaces it; anything else, ✏️ Edit it. A time alone on an all-day event
gives it that time.

**Cancelling by message**: “cancel padel” asks to confirm; for a repeating
event you can pick `⏭ Just Thu 29 Oct` or `🗑 Every time`. “cancel padel on
thursday” asks to skip just that day. If a reminder you set before it is
waiting for your OK right now, its message loses its buttons.

`👎 Wrong` on the confirmation (or “that's wrong” right after) cancels the
event and saves your message as failed, like for
[reminders](#when-the-bot-gets-it-wrong).

### 📅 Google Calendar

Link Google Calendar and your events sync both ways: events you add, move,
edit, skip or cancel here change in Google Calendar, and Google's events are
here too, so “remind me 30 min before padel” works for them, and they show
in 📅 Events and “what do I have tomorrow?”.

**Linking**: `⚙️ Settings → 📅 Calendar` (or `/calendar`) →
`🔗 Link Google Calendar`. Google asks you to allow two things: seeing and
changing your events, and seeing the list of your calendars. Allow both;
Google then sends you back, and the bot says `✅ Google Calendar linked.` The
events you already made here go to your main calendar.

```
📅 Google Calendar: linked

Tap a calendar to sync it or stop:
[✅ Roman]
[⬜ Work]
[⬜ Holidays in Portugal]

New events from the bot go to: Roman
[🔄 Sync now] [🔓 Unlink]
```

- **Which calendars**: your main one syncs at first; tap others to add them
  (read-only ones, like holidays, come in but can't receive new events).
  With more than one, `📥 Put new events in another one` picks where events
  you add here go.
- **Stopping one**, or `🔓 Unlink`: the bot asks whether to keep its events
  here (no longer synced) or remove them (with their reminders). Kept ones
  link up again, without copies, if you sync that calendar again later.
  Unlinking also gives the bot's access back to Google.
- **How fast**: Google tells the bot about changes right away. The bot also
  checks when you ask about reminders or events (at most every 5 minutes) and
  once a day, in case a notice got lost. `🔄 Sync now` checks right away.
- **Both changed it**: the latest change wins.
- **A single day changed in Google** (one Thursday moved or cancelled): the
  bot follows it, and so do the event's reminders.
- **Repeats** can be anything Google allows (“every 2nd and 4th Tuesday”,
  “until December”, “10 times”); the bot shows them as “every 2 weeks on
  Tue at 19:00, until 24 Dec 2026”.

**If the login expires** (while the bot's Google app is in testing, Google
ends logins after 7 days) or you remove the bot's access in your Google
account, the bot tells you once, with `🔗 Link again`, and 📅 Events shows a
warning. Nothing is deleted or moved meanwhile; changes you make here are
sent once you link again.

**Privacy**: unlike everything else here, linking sends your events (the
ones in the bot, and their changes) to Google, and the bot reads the
calendars you pick. It keeps a copy of their events (title, times, repeat;
not descriptions, places or guests), so reminders can follow them. An event
from Google that is deleted (there, here, or with `🗑 Remove them`) is
deleted from the bot too, not kept; events you made here are kept as
cancelled, like any other. Your Google login is stored encrypted. Only test
users can link while the app is in testing.

## 👥 People

To send reminders to someone else, they first have to agree: Telegram only
lets the bot message people who started it, and nobody gets reminders from
you without saying yes.

**Inviting someone**: `👥 People → ➕ Invite` gives you a link like
`https://t.me/<bot>?start=inv_…`. Send it to them any way you like. When they
open it and tap **Start**, the bot asks them:

```
👥 Roman (@roman) wants to send you reminders.
[✅ Allow] [❌ No]
```

If they tap ✅ Allow, you're told, and they appear in your 👥 People. The link
works **once**, for **7 days**; if they tap ❌ No, it stops working and
you're told.

**If they already use the bot**, you can send their @username instead of the
link (on the same ➕ Invite screen). They get the same question. If they say
no, you can't ask them that way again for 30 days (an invite link still
works if they change their mind), and you can send at most 5 requests a
day, one per person.

**Names**: each person gets a name (their Telegram first name, or “Anna 2”
if you already have an Anna). Rename it with `👤 <name> → ✏️ Rename`, e.g.
to “mom”: up to 32 letters, digits, spaces, ' or -, starting with a letter.

**Ending it**: either of you can, at any time, and nothing is kept.

- `👤 <name> → 🗑 Remove`: you stop reminding them. They aren't told.
- `📨 <name> → 🚫 Stop their reminders`: they can't remind you any more,
  and they're told.

Either way, reminders they had set for you that haven't gone off are
cancelled, and one that's going off right now loses its buttons
(“↩️ Cancelled.”). The 🗑 Remove confirmation and the 🚫 Stop message say how
many were cancelled. Each direction is separate: if Anna can remind you,
that doesn't let you remind her.

**If they block the bot** (or leave Telegram), the next reminder for them
can't be delivered. The bot then removes them from your 👥 People, cancels
your other reminders for them, and tells you:

```
⚠️ I couldn't deliver “bring the keys” to Anna: they've blocked the bot or
left Telegram. I removed them from 👥 People and cancelled your other
reminder for them. If they want your reminders again, send them a new invite.
```

### Reminding someone

Once someone is in your 👥 People, start a reminder with their name (or
their @username) instead of “me”:

- “remind anna tomorrow at 9 to bring the keys”
- “remind mom every Sunday at 18 to call me”
- “remind @anna, buy milk at 5”

Everything that works for your own reminders works here: repeats, voice
messages, and the bot asking for a missing time or text (“⏰ When should I
remind Anna: “bring the keys”?”). If the name isn't one of yours, the bot
asks “Who's “bob”?” instead of guessing, and makes nothing. If they haven't
answered your request yet, it says so.

```
⏰ Got it for Anna: bring the keys
🗓 Tomorrow, 09:00 (in 9 h)
[↩️ Undo] [✏️ Edit] [👎 Wrong]
```

**The time is yours**: “tomorrow at 9” and “every day at 9” are 9 o'clock
in *your* timezone, since you said it. Anna sees it in hers (11:00 if she's
two hours ahead), and a repeat shows whose clock it follows: “🔁 every day
at 09:00 (Roman's time)”.

**Anna gets it in her chat**, with her own snooze options, repeat interval
and quiet hours:

```
⏰ bring the keys
📨 from Roman (@roman)
[✅ OK] [💤 10 min] [💤 1 h]
```

**Who can do what:**

| | You (sender) | Anna |
| --- | --- | --- |
| ✅ OK, 💤 snooze, replies (“done”, “move it to 10”) | | ✓ |
| ↩️ Undo, ✏️ Edit, 👎 Wrong | ✓ | |
| ❌ Cancel from the list | ✓ | ✓ (you're told) |

**What you're told:**

- “✅ Anna did it: bring the keys” when she taps ✅ OK (each time, for a
  repeat).
- “❌ Anna missed it: bring the keys” when it's marked missed.
- “🗑 Anna cancelled your reminder: bring the keys” if she cancels it.

Turn off the first two in [📣 Updates from people](#-updates-from-people);
you're always told about a cancellation. When either of you leaves the
other's 👥 People, reminders that haven't gone off are cancelled.

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
- Reminders you [set for someone](#reminding-someone) are in your timezone
  too, and follow it when you change it. Those others set for you follow
  theirs, so changing yours only changes how their time is shown to you.

### 💤 Snooze options

`⚙️ Settings → ⏰ Reminders → 💤 Snooze options`. The snooze buttons on a due
reminder.

| | |
| --- | --- |
| Default | 10 min · 1 h |
| Presets | 5 min · 15 min · 1 h — 10 min · 1 h — 10 min · 30 min · 2 h |
| Custom  | Up to 3 options, each 1 minute – 24 hours. Send e.g. “10m, 1h, 3h”, “5, 15, 60” (minutes), “10 min, 1 hour” or say “ten minutes and one hour” |

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
| Custom  | Send e.g. “23:00-07:00”, “22 to 8”, “11 pm to 7” or “off” (or say “eleven pm to seven”). Start and end must differ; windows across midnight are fine |

### 📣 Updates from people

`⚙️ Settings → ⏰ Reminders → 📣 Updates from people`. Whether you're told
when someone you [sent a reminder](#reminding-someone) taps ✅ OK or misses
it. Cancellations are always told.

| | |
| --- | --- |
| Default | 🔔 On |
| Options | 🔔 On, 🔕 Off |

## Good to know

- Typed and voice messages work in **private chats** only.
- Only the person a reminder is for can answer it (✅ OK, 💤); only whoever
  made it can undo, edit or flag it.
- If the bot doesn't understand a message, it says “I didn't get that.”
  (no examples), and saves the message so the bot can learn it (see
  [When the bot gets it wrong](#when-the-bot-gets-it-wrong)).
- A trigger phrase always works, even while the bot is waiting for an
  answer to a question (e.g. during ✏️ Edit).
