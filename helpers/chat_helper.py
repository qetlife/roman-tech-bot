from    telegram                    import Update
from    telegram.ext                import ContextTypes
from telegram.error                 import BadRequest


async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    chat_id = update.effective_chat.id
    msg_id = context.chat_data.get("menu_message_id")

    if msg_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=reply_markup
            )
            return
        except BadRequest:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except BadRequest:
                pass
            
            msg = await update.message.reply_text(text, reply_markup=reply_markup)
            context.chat_data["menu_message_id"] = msg.message_id
    else:
        msg = await update.message.reply_text(text, reply_markup=reply_markup)
        context.chat_data["menu_message_id"] = msg.message_id

