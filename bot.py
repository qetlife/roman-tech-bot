import os

from    telegram        import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from    telegram.ext    import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from    dotenv          import load_dotenv


MAIN_BUTTONS = [
    [KeyboardButton("⏰ Reminders")],
    [KeyboardButton("❌ Hide Menu")]
]

def build_main_menu():
    return ReplyKeyboardMarkup(
        MAIN_BUTTONS,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Pick a tool…"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I’m your assistant. Here’s your menu:",
        reply_markup=build_main_menu()
    )

# Show menu again (if user hid it)
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Menu:", reply_markup=build_main_menu())

# Hide the reply keyboard
async def hide_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Menu hidden. Type /menu to bring it back.",
                                    reply_markup=ReplyKeyboardRemove())

async def on_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Reminders: try “Buy milk | tomorrow 09:00”.")

# Fallback to exit mini flows and go back “home”
async def back_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("mode", None)
    await update.message.reply_text("Back to menu.", reply_markup=build_main_menu())

def main():
    load_dotenv()

    BOT_TOKEN =     os.environ.get("BOT_TOKEN")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("back", back_cmd))

    # Button presses (match by visible text)
    app.add_handler(MessageHandler(filters.Regex(r"^⏰ Reminders$"), on_reminders))
    app.add_handler(MessageHandler(filters.Regex(r"^❌ Hide Menu$"), hide_menu))

    app.run_polling()
    print("Running!")

if __name__ == "__main__":
    main()