from    telegram                import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.ext            import ContextTypes

from    helpers.chat_helper     import render_menu


REMINDERS_TEXT = "Reminders: try “Buy milk | tomorrow 09:00”."


def build_reminders_menu():
    keyboard = [
        [InlineKeyboardButton("↩️ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def on_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await render_menu(update, context, REMINDERS_TEXT, build_reminders_menu())
