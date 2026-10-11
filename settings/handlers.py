from    telegram                    import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext                import ContextTypes

from    db.repository.settings_repository import SettingsRepository
from    db.repository.user_repository import UserRepository
from    helpers.chat_helper         import render_menu
from    settings.registry           import (
    REPEAT_MINUTES, REPEAT_PRESETS, SNOOZE_OPTIONS, SNOOZE_PRESETS, format_minutes, parse_snooze_options,
)


users = UserRepository()
settings = SettingsRepository()

# context.user_data["awaiting"] value while waiting for custom snooze options
AWAIT_SNOOZE_OPTIONS = "snooze_options"


def format_snooze_options(minutes) -> str:
    return " · ".join(format_minutes(m) for m in minutes)


def build_snooze_menu(current):
    rows = [
        [InlineKeyboardButton(
            ("✅ " if preset == current else "") + format_snooze_options(preset),
            callback_data="snzopt:set:" + ",".join(map(str, preset)),
        )]
        for preset in SNOOZE_PRESETS
    ]
    rows.append([
        InlineKeyboardButton("✏️ Custom", callback_data="snzopt:custom"),
        InlineKeyboardButton("♻️ Default", callback_data="snzopt:default"),
    ])
    rows.append([InlineKeyboardButton("↩️ Back", callback_data="menu:settings")])
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
    action, _, arg = query.data.removeprefix("snzopt:").partition(":")
    user = users.get_or_create(update.effective_user.id)

    if action == "custom":
        context.user_data["awaiting"] = AWAIT_SNOOZE_OPTIONS
        await query.answer()
        await query.message.reply_text(
            "Send up to 3 snooze times, e.g. “10m, 1h, 3h” or “5, 15, 60” (minutes)."
        )
        return

    try:
        if action == "default":
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
    context.user_data.pop("awaiting", None)
    await update.effective_message.reply_text(
        f"💤 Snooze options set to {format_snooze_options(minutes)}.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Settings", callback_data="menu:settings"),
        ]]),
    )


# --- repeat interval --------------------------------------------------------

def build_repeat_menu(current):
    buttons = [
        InlineKeyboardButton(("✅ " if m == current else "") + format_minutes(m), callback_data=f"rptopt:set:{m}")
        for m in REPEAT_PRESETS
    ]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton("↩️ Back", callback_data="menu:settings")])
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
        settings.set(user.id, REPEAT_MINUTES, int(query.data.removeprefix("rptopt:set:")))
    except ValueError as e:
        await query.answer(str(e), show_alert=True)
        return
    await on_repeat_settings(update, context, toast="Saved")
