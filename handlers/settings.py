"""⚙️ Settings screens: timezone and the reminder settings."""

from    telegram                    import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext                import ContextTypes

from    core.settings               import (
    QUIET_HOURS, QUIET_PRESETS, REPEAT_MINUTES, REPEAT_PRESETS, SNOOZE_OPTIONS, SNOOZE_PRESETS,
    format_minutes, format_quiet_hours, parse_quiet_hours, parse_snooze_options,
)
from    core.timezones              import COMMON_TIMEZONES, resolve_timezone, user_now
from    db.repositories.settings    import SettingsRepository
from    db.repositories.user        import UserRepository
from    enums                       import Awaiting, Callback, CallbackPrefix, OptionAction
from    handlers.ui                 import (
    AWAITING, PENDING_REQUEST, REMINDER_SETTINGS_BACK, option_callback, render_menu, split_option,
)


users = UserRepository()
settings = SettingsRepository()

# Reminder settings open from ⚙️ Settings or from the ⏰ Reminders menu;
# ↩️ Back returns to whichever it was (remembered in REMINDER_SETTINGS_BACK).
REMINDER_SETTINGS_ENTRIES = {
    Callback.REMINDER_SETTINGS: Callback.SETTINGS_MENU,
    Callback.REMINDER_SETTINGS_FROM_MENU: Callback.REMINDERS_MENU,
}


def format_snooze_options(minutes) -> str:
    return " · ".join(format_minutes(m) for m in minutes)


# --- timezone ---------------------------------------------------------------

def build_timezone_keyboard():
    rows = [
        [InlineKeyboardButton(tz, callback_data=f"{CallbackPrefix.TIMEZONE}{tz}") for tz in COMMON_TIMEZONES[i:i + 2]]
        for i in range(0, len(COMMON_TIMEZONES), 2)
    ]
    return InlineKeyboardMarkup(rows)


async def ask_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE, intro: str = ""):
    context.user_data[AWAITING] = Awaiting.TIMEZONE
    await update.effective_message.reply_text(
        f"{intro}Which timezone are you in? Pick one or type a city "
        "(e.g. Kyiv, New York) or an offset (e.g. UTC+3).",
        reply_markup=build_timezone_keyboard(),
    )


async def apply_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE, tz_name: str):
    old_tz = users.get_or_create(update.effective_user.id).timezone
    user = users.set_timezone(update.effective_user.id, tz_name)
    if old_tz and old_tz != tz_name:
        # Imported here: handlers.reminders imports this module (ask_timezone).
        from handlers.reminders import keep_clock_times
        keep_clock_times(user.id, old_tz, tz_name)
    context.user_data.pop(AWAITING, None)
    local = user_now(tz_name)
    await update.effective_message.reply_text(f"🌍 Timezone set to {tz_name} (local time {local:%H:%M}).")

    pending = context.user_data.pop(PENDING_REQUEST, None)
    if pending is not None:
        # Imported here: handlers.reminders imports this module (ask_timezone).
        from handlers.reminders import create_reminder
        await create_reminder(update, context, pending)


async def on_timezone_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tz_name = query.data.removeprefix(CallbackPrefix.TIMEZONE)
    await query.edit_message_reply_markup(reply_markup=None)
    await apply_timezone(update, context, tz_name)


async def on_timezone_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    tz_name = resolve_timezone(text)
    if tz_name is None:
        await update.effective_message.reply_text(
            "I don't know that timezone. Try a city (e.g. Kyiv, London) or an offset (e.g. UTC+3).",
            reply_markup=build_timezone_keyboard(),
        )
        return
    await apply_timezone(update, context, tz_name)


async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "set my timezone to Lisbon"; without a place, asks for one."""
    if not request.strip():
        await ask_timezone(update, context)
        return
    await on_timezone_text(update, context, request.strip().rstrip(".!"))


async def on_timezone_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Settings → 🌍 Timezone."""
    await update.callback_query.answer()
    user = users.get_or_create(update.effective_user.id)
    current = f"Current timezone: {user.timezone}. " if user.timezone else ""
    await ask_timezone(update, context, current)


# --- reminder settings ------------------------------------------------------

def build_reminder_settings_menu(back: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(SNOOZE_OPTIONS.label, callback_data=Callback.SNOOZE_SETTINGS)],
        [InlineKeyboardButton(REPEAT_MINUTES.label, callback_data=Callback.REPEAT_SETTINGS)],
        [InlineKeyboardButton(QUIET_HOURS.label, callback_data=Callback.QUIET_SETTINGS)],
        [InlineKeyboardButton("↩️ Back", callback_data=back)],
    ])


def reminder_settings_text(snooze, repeat, quiet) -> str:
    return (
        "⏰ Reminder settings:\n\n"
        f"{SNOOZE_OPTIONS.label}: {format_snooze_options(snooze)}\n"
        f"{REPEAT_MINUTES.label}: every {format_minutes(repeat)}\n"
        f"{QUIET_HOURS.label}: {format_quiet_hours(quiet)}"
    )


async def on_reminder_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Settings → ⏰ Reminders, or ⏰ Reminders → ⚙️ Settings."""
    query = update.callback_query
    await query.answer()
    if query.data in REMINDER_SETTINGS_ENTRIES:
        context.user_data[REMINDER_SETTINGS_BACK] = REMINDER_SETTINGS_ENTRIES[query.data]
    back = context.user_data.get(REMINDER_SETTINGS_BACK, Callback.SETTINGS_MENU)

    user = users.get_or_create(update.effective_user.id)
    text = reminder_settings_text(
        settings.get(user.id, SNOOZE_OPTIONS), settings.get(user.id, REPEAT_MINUTES), settings.get(user.id, QUIET_HOURS),
    )
    await render_menu(update, context, text, build_reminder_settings_menu(back))


# --- snooze options ---------------------------------------------------------


def build_snooze_menu(current):
    rows = [
        [InlineKeyboardButton(
            ("✅ " if preset == current else "") + format_snooze_options(preset),
            callback_data=option_callback(CallbackPrefix.SNOOZE_OPTION, OptionAction.SET, ",".join(map(str, preset))),
        )]
        for preset in SNOOZE_PRESETS
    ]
    rows.append([
        InlineKeyboardButton("✏️ Custom", callback_data=option_callback(CallbackPrefix.SNOOZE_OPTION, OptionAction.CUSTOM)),
        InlineKeyboardButton("♻️ Default", callback_data=option_callback(CallbackPrefix.SNOOZE_OPTION, OptionAction.DEFAULT)),
    ])
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=Callback.REMINDER_SETTINGS_RETURN)])
    return InlineKeyboardMarkup(rows)


def snooze_menu_text(current) -> str:
    return (
        f"{SNOOZE_OPTIONS.label}\n\n"
        f"Current: {format_snooze_options(current)}\n\n"
        "These are the snooze buttons on your reminders. "
        "Pick a preset or set your own (up to 3)."
    )


async def on_snooze_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, toast: str = None):
    """⚙️ Settings → 💤 Snooze options."""
    await update.callback_query.answer(toast)
    user = users.get_or_create(update.effective_user.id)
    current = settings.get(user.id, SNOOZE_OPTIONS)
    await render_menu(update, context, snooze_menu_text(current), build_snooze_menu(current))


async def on_snooze_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, arg = split_option(query.data, CallbackPrefix.SNOOZE_OPTION)
    user = users.get_or_create(update.effective_user.id)

    if action == OptionAction.CUSTOM:
        context.user_data[AWAITING] = Awaiting.SNOOZE_OPTIONS
        await query.answer()
        await query.message.reply_text(
            "Send up to 3 snooze times, e.g. “10m, 1h, 3h” or “5, 15, 60” (minutes)."
        )
        return

    try:
        if action == OptionAction.DEFAULT:
            settings.reset(user.id, SNOOZE_OPTIONS)
        else:
            settings.set(user.id, SNOOZE_OPTIONS, [int(m) for m in arg.split(",")])
    except ValueError as e:
        await query.answer(str(e), show_alert=True)
        return

    await on_snooze_settings(update, context, toast="Saved")


async def on_snooze_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Answer to ✏️ Custom."""
    try:
        minutes = parse_snooze_options(text)
    except ValueError as e:
        await update.effective_message.reply_text(
            f"{e} Try again, e.g. “10m, 1h, 3h” (between 1 minute and 24 hours, up to 3)."
        )
        return

    user = users.get_or_create(update.effective_user.id)
    settings.set(user.id, SNOOZE_OPTIONS, minutes)
    context.user_data.pop(AWAITING, None)
    await update.effective_message.reply_text(
        f"💤 Snooze options set to {format_snooze_options(minutes)}.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Reminder settings", callback_data=Callback.REMINDER_SETTINGS_RETURN),
        ]]),
    )


# --- repeat interval --------------------------------------------------------

def build_repeat_menu(current):
    buttons = [
        InlineKeyboardButton(("✅ " if m == current else "") + format_minutes(m), callback_data=option_callback(CallbackPrefix.REPEAT_OPTION, OptionAction.SET, m))
        for m in REPEAT_PRESETS
    ]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=Callback.REMINDER_SETTINGS_RETURN)])
    return InlineKeyboardMarkup(rows)


def repeat_menu_text(current) -> str:
    return (
        f"{REPEAT_MINUTES.label}\n\n"
        f"Current: every {format_minutes(current)}\n\n"
        "Until you press OK, a reminder is sent again this often."
    )


async def on_repeat_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, toast: str = None):
    """⚙️ Settings → 🔁 Repeat interval."""
    await update.callback_query.answer(toast)
    user = users.get_or_create(update.effective_user.id)
    current = settings.get(user.id, REPEAT_MINUTES)
    await render_menu(update, context, repeat_menu_text(current), build_repeat_menu(current))


async def on_repeat_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = users.get_or_create(update.effective_user.id)
    try:
        settings.set(user.id, REPEAT_MINUTES, int(split_option(query.data, CallbackPrefix.REPEAT_OPTION)[1]))
    except ValueError as e:
        await query.answer(str(e), show_alert=True)
        return
    await on_repeat_settings(update, context, toast="Saved")


# --- quiet hours ------------------------------------------------------------

def build_quiet_menu(current):
    rows = [
        [InlineKeyboardButton(
            ("✅ " if preset == current else "") + format_quiet_hours(preset),
            callback_data=option_callback(CallbackPrefix.QUIET_OPTION, OptionAction.SET, "-".join(preset)),
        )]
        for preset in QUIET_PRESETS
    ]
    rows.append([InlineKeyboardButton(("✅ " if not current else "") + "🔔 Off", callback_data=option_callback(CallbackPrefix.QUIET_OPTION, OptionAction.OFF))])
    rows.append([
        InlineKeyboardButton("✏️ Custom", callback_data=option_callback(CallbackPrefix.QUIET_OPTION, OptionAction.CUSTOM)),
        InlineKeyboardButton("♻️ Default", callback_data=option_callback(CallbackPrefix.QUIET_OPTION, OptionAction.DEFAULT)),
    ])
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=Callback.REMINDER_SETTINGS_RETURN)])
    return InlineKeyboardMarkup(rows)


def quiet_menu_text(current) -> str:
    return (
        f"{QUIET_HOURS.label}\n\n"
        f"Current: {format_quiet_hours(current)}\n\n"
        "During quiet hours, “every 2 hours”-style reminders are skipped and "
        "unanswered reminders wait until morning. Reminders set for a specific "
        "time still go off."
    )


async def on_quiet_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, toast: str = None):
    """⏰ Reminder settings → 🌙 Quiet hours."""
    await update.callback_query.answer(toast)
    user = users.get_or_create(update.effective_user.id)
    current = settings.get(user.id, QUIET_HOURS)
    await render_menu(update, context, quiet_menu_text(current), build_quiet_menu(current))


async def on_quiet_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, arg = split_option(query.data, CallbackPrefix.QUIET_OPTION)
    user = users.get_or_create(update.effective_user.id)

    if action == OptionAction.CUSTOM:
        context.user_data[AWAITING] = Awaiting.QUIET_HOURS
        await query.answer()
        await query.message.reply_text("Send the quiet hours, e.g. “23:00-07:00” or “22 to 8”, or “off”.")
        return

    try:
        if action == OptionAction.DEFAULT:
            settings.reset(user.id, QUIET_HOURS)
        elif action == OptionAction.OFF:
            settings.set(user.id, QUIET_HOURS, [])
        else:
            settings.set(user.id, QUIET_HOURS, arg.split("-"))
    except ValueError as e:
        await query.answer(str(e), show_alert=True)
        return

    await on_quiet_settings(update, context, toast="Saved")


async def on_quiet_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Answer to ✏️ Custom."""
    try:
        value = parse_quiet_hours(text)
    except ValueError as e:
        await update.effective_message.reply_text(f"{e} Try again, e.g. “23:00-07:00” or “off”.")
        return

    user = users.get_or_create(update.effective_user.id)
    settings.set(user.id, QUIET_HOURS, value)
    context.user_data.pop(AWAITING, None)
    await update.effective_message.reply_text(
        f"🌙 Quiet hours set to {format_quiet_hours(value)}.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Reminder settings", callback_data=Callback.REMINDER_SETTINGS_RETURN),
        ]]),
    )
