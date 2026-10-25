"""The catch-all for errors nothing else handled: recorded, and the user told something went wrong.

python-telegram-bot calls `on_error` for an exception in any handler or job. It
is logged with `logger.exception`, so it lands in the errors file
(core/errors.py) with what the bot was doing. Telegram's own network
hiccups (polling timeouts, a dropped connection) are expected and only logged
as warnings: the library retries them.
"""

import logging

from    telegram                    import Update
from    telegram.error              import Forbidden, NetworkError, TelegramError
from    telegram.ext                import ContextTypes


logger = logging.getLogger(__name__)

SORRY = "Sorry, something went wrong on my side. Try again in a moment."


def describe(update) -> dict:
    """What the bot was doing, without the user's text: the kind of update, the command or button, who."""
    if not isinstance(update, Update):
        return {"update": type(update).__name__ if update is not None else None}
    context = {"user": update.effective_user.id if update.effective_user else None}
    if update.callback_query is not None:
        context.update(update="button", data=update.callback_query.data)
    elif update.effective_message is not None:
        message = update.effective_message
        text = message.text or ""
        if text.startswith("/"):
            context.update(update="command", command=text.split()[0])
        elif message.voice is not None:
            context.update(update="voice message")
        else:
            context.update(update="message")
    else:
        context["update"] = "other"
    return context


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if isinstance(error, (NetworkError, Forbidden)):
        # Telegram unreachable for a moment (retried), or a user who blocked the bot
        logger.warning("Telegram: %s", error)
        return
    logger.error("Unexpected error", exc_info=error, extra={"error_context": describe(update)})
    if not isinstance(update, Update):
        return
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(SORRY, show_alert=True)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(SORRY)
    except TelegramError:
        pass
