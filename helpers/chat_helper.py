from    telegram                    import Update
from    telegram.ext                import ContextTypes
from    telegram.error              import BadRequest


async def render_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    """Render a menu screen as a single, long-lived message.

    - When triggered by an inline button (callback query), the existing
      message is edited in place.
    - When triggered by a command, the previously tracked menu message is
      edited; if that fails it is replaced with a fresh one.
    """
    chat_id = update.effective_chat.id
    query = update.callback_query

    if query is not None:
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
        except BadRequest as e:
            # Pressing a button that does not change the screen is harmless.
            if "not modified" not in str(e).lower():
                raise
        context.chat_data["menu_message_id"] = query.message.message_id
        return

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

    msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    context.chat_data["menu_message_id"] = msg.message_id
