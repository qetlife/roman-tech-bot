from    telegram                    import ReplyKeyboardMarkup, Update, ReplyKeyboardRemove, KeyboardButton
from    telegram.ext                import ContextTypes

from    helpers.chat_helper         import send_message



MAIN_BUTTONS = [
    [KeyboardButton("⏰ Reminders")],
    [KeyboardButton("⚙️ Settings")],
    [KeyboardButton("⬇️ Hide Menu")]
]

def build_main_menu():
    return ReplyKeyboardMarkup(
        MAIN_BUTTONS,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Pick a tool…"
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update, context,
        "Menu:", build_main_menu())
    
async def hide_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update, context,
        "Menu hidden. Type /menu to bring it back.",
        ReplyKeyboardRemove()
    )