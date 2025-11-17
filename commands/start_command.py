from    telegram                    import Update
from    telegram.ext                import ContextTypes

from    commands.menu_command       import build_main_menu
from    helpers.chat_helper         import send_message


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update, context,
        "Hi! I’m your assistant. Here’s your menu:",
        build_main_menu()
    )