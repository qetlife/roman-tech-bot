import os

from    telegram        import Update
from    telegram.ext    import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from    dotenv          import load_dotenv

load_dotenv()

BOT_TOKEN =     os.environ.get("BOT_TOKEN")

application =   ApplicationBuilder().token(BOT_TOKEN).build()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
     await update.message.reply_text(
        text="Hello",
        parse_mode="Markdown"
    )

application.add_handler(CommandHandler("start", start))

if __name__ == "__main__":
    print("Running!")
    application.run_polling()