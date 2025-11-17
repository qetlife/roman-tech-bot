from    telegram                import  Update, ReplyKeyboardMarkup, KeyboardButton
from    telegram.ext            import ContextTypes

from commands.menu_command      import build_main_menu
from    helpers.chat_helper     import send_message


SETTINGS_BUTTONS = [
    [KeyboardButton("🆔 My ID")],
    [KeyboardButton("↩️ Back")]
]

def build_settings_menu():
    return ReplyKeyboardMarkup(
        SETTINGS_BUTTONS,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Pick a tool…"
    )
    
async def on_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update, context,
        "Settings:", build_settings_menu())

async def on_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update, context,
        f"Your ID: {update.effective_user.id}",
        build_settings_menu()) 

async def on_back_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update, context,
        "Back to menu.", build_main_menu())