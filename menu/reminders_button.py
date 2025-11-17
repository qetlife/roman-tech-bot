from    telegram        import  Update
from    telegram.ext    import  ContextTypes

from    helpers.chat_helper         import send_message

async def on_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update, context,
        "Reminders: try “Buy milk | tomorrow 09:00”.")