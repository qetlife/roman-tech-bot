from    telegram                    import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext                import ContextTypes

from    helpers.chat_helper         import render_menu


MAIN_MENU_TEXT = "Menu:"


def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("⏰ Reminders", callback_data="menu:reminders")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_menu(update, context, MAIN_MENU_TEXT, build_main_menu())


async def on_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context, MAIN_MENU_TEXT, build_main_menu())
