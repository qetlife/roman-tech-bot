from    telegram                import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext            import ContextTypes

from    commands.menu_command   import MAIN_MENU_TEXT, build_main_menu
from    helpers.chat_helper     import render_menu


SETTINGS_TEXT = "Settings:"


def build_settings_menu():
    keyboard = [
        [InlineKeyboardButton("🆔 My ID", callback_data="settings:my_id")],
        [InlineKeyboardButton("↩️ Back", callback_data="settings:back")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def on_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context, SETTINGS_TEXT, build_settings_menu())


async def on_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context,
        f"Your ID: {update.effective_user.id}",
        build_settings_menu())


async def on_back_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context, MAIN_MENU_TEXT, build_main_menu())
