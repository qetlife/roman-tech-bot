from    telegram                import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext            import ContextTypes

from    helpers.chat_helper     import render_menu


REMINDERS_TEXT = (
    "Reminders:\n\n"
    "You can also just type, e.g. “remind me in 2 hours to call mom”."
)


def build_reminders_menu():
    keyboard = [
        [InlineKeyboardButton("➕ New", callback_data="rem:new")],
        [InlineKeyboardButton("📋 My reminders", callback_data="rem:list")],
        [InlineKeyboardButton("↩️ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def on_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context, REMINDERS_TEXT, build_reminders_menu())
