# Near-Term Plan

This document captures the next major steps for `roman-tech-bot`.

## Goal

Move the bot from a simple reply-keyboard prototype to a cleaner inline-button architecture, then build a real reminder system backed by the database.

## Phase 1: Refresh and Restructure the Current Bot

### 1. Review and modernize the current codebase

- Clean up the current handler structure and make the flow easier to extend.
- Improve naming consistency across `commands/`, `menu/`, `helpers/`, `db/`, and `models/`.
- Add clearer error handling and logging in places that currently swallow exceptions.
- Make the message/edit helpers work reliably for callback-based navigation.
- Prepare the code for multi-step user flows instead of single-message placeholder responses.

### 2. Replace `ReplyKeyboardMarkup` with `InlineKeyboardButton`

- Remove the current reply-keyboard based menu system.
- Rebuild the main menu and settings menu with inline keyboards.
- Move navigation to callback queries instead of text matching.
- Introduce stable callback IDs for actions such as:
  - `menu:main`
  - `menu:reminders`
  - `menu:settings`
  - `settings:my_id`
  - `settings:back`
- Update the chat helper so menus are edited in place when possible.
- Adjust `/start` and `/menu` to open the inline main menu.

### 3. Rework bot architecture for inline interactions

- Add callback query handlers in `bot.py`.
- Split UI rendering from business logic where possible.
- Keep each screen responsible for:
  - text content
  - inline keyboard layout
  - callback actions
- Define a predictable navigation pattern so new sections are easy to add later.

## Phase 2: Build the Reminder System

### 4. Define reminder requirements and flow

Each reminder should support:

- target user
- reminder text
- date
- time
- creator user
- delivery status

Supported use cases:

- A user creates a reminder for himself.
- A user creates a reminder for another known user.
- The bot stores the reminder in the database.
- The bot sends the reminder when the scheduled time arrives.

### 5. Extend the database schema

Add a reminders table with fields such as:

- `id`
- `creator_user_id`
- `target_user_id`
- `text`
- `remind_at`
- `created_at`
- `sent_at`
- `status`

Also consider:

- storing timezone if needed later
- indexes on `remind_at` and `status`
- adding a migration strategy instead of manual SQL changes

### 6. Create reminder models and repository layer

- Add a SQLAlchemy model for reminders.
- Add a reminder repository for:
  - create
  - fetch pending reminders
  - mark reminder as sent
  - fetch reminders by user
- Keep repository methods small and explicit.

### 7. Build the reminder creation flow

Implement a multi-step interaction for reminder creation:

1. Choose target user:
   self or another user
2. Enter reminder text
3. Enter date
4. Enter time
5. Show confirmation
6. Save to database

Notes:

- This likely needs conversation state management.
- Input validation should be added for date and time parsing.
- We should define what "specific user" means in the bot:
  - by Telegram ID
  - by previously registered bot user

### 8. Deliver reminders on schedule

- Add a background scheduling/checking mechanism.
- Periodically poll the database for due reminders.
- Send due reminders to the target Telegram user.
- Mark reminders as sent after successful delivery.
- Handle retry/error cases cleanly.

Possible implementation directions:

- simple polling loop inside the bot process
- job queue / scheduler integrated with the bot runtime

For the near future, a simple polling worker is enough.

## Suggested Order of Execution

1. Refactor the current menu/navigation code.
2. Replace reply keyboards with inline keyboards and callback handlers.
3. Improve helper utilities and error handling.
4. Design the reminder schema.
5. Add reminder model and repository.
6. Build the reminder creation conversation flow.
7. Add background processing for due reminders.
8. Test the full flow end to end.

## Open Decisions

These decisions should be clarified while implementing:

- How users select another user for reminders.
- What date/time format the bot should accept.
- Whether reminders are stored in UTC only.
- Whether editing an existing reminder is needed now or later.
- Whether recurring reminders are out of scope for this phase.

## Definition of Done for This Phase

The phase is complete when:

- all current menus use inline keyboards
- navigation is callback-based instead of text-match based
- users can create reminders through a guided flow
- reminders are persisted in PostgreSQL
- due reminders are sent automatically by the bot
- reminder delivery is marked in the database
