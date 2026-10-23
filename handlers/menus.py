"""Menu screens: main menu, ⏰ Reminders and ⚙️ Settings (📅 Events is in handlers/events.py)."""

from    telegram                import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext            import ContextTypes

from    enums                   import Callback
from    handlers.ui             import render_menu


# --- main menu --------------------------------------------------------------

MAIN_MENU_TEXT = "Menu:"


def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("⏰ Reminders", callback_data=Callback.REMINDERS_MENU)],
        [InlineKeyboardButton("📅 Events", callback_data=Callback.EVENTS_MENU)],
        [InlineKeyboardButton("👥 People", callback_data=Callback.PEOPLE_MENU)],
        [InlineKeyboardButton("⚙️ Settings", callback_data=Callback.SETTINGS_MENU)],
    ]
    return InlineKeyboardMarkup(keyboard)


async def on_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """↩️ Back to the main menu (from ⏰ Reminders or ⚙️ Settings)."""
    await update.callback_query.answer()
    await render_menu(update, context, MAIN_MENU_TEXT, build_main_menu())


# --- ⏰ Reminders ------------------------------------------------------------

REMINDERS_TEXT = (
    "Reminders:\n\n"
    "You can also just type, e.g. “remind me in 2 hours to call mom”."
)


def build_reminders_menu():
    keyboard = [
        [InlineKeyboardButton("➕ New", callback_data=Callback.NEW_REMINDER)],
        [InlineKeyboardButton("📋 My reminders", callback_data=Callback.LIST_REMINDERS)],
        [InlineKeyboardButton("⚙️ Settings", callback_data=Callback.REMINDER_SETTINGS_FROM_MENU)],
        [InlineKeyboardButton("↩️ Back", callback_data=Callback.MAIN_MENU)],
    ]
    return InlineKeyboardMarkup(keyboard)


async def on_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context, REMINDERS_TEXT, build_reminders_menu())


# --- ⚙️ Settings -------------------------------------------------------------

SETTINGS_TEXT = "Settings:"


def build_settings_menu():
    keyboard = [
        [InlineKeyboardButton("🆔 My ID", callback_data=Callback.MY_ID)],
        [InlineKeyboardButton("🌍 Timezone", callback_data=Callback.TIMEZONE_SETTINGS)],
        [InlineKeyboardButton("⏰ Reminders", callback_data=Callback.REMINDER_SETTINGS)],
        [InlineKeyboardButton("📅 Calendar", callback_data=Callback.CALENDAR_SETTINGS)],
        [InlineKeyboardButton("↩️ Back", callback_data=Callback.SETTINGS_BACK)],
    ]
    return InlineKeyboardMarkup(keyboard)


async def on_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context, SETTINGS_TEXT, build_settings_menu())


async def on_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context, f"Your ID: {update.effective_user.id}", build_settings_menu())
