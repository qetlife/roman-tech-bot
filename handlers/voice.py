"""Voice messages: transcribed by the speech-service, then handled like typed text."""

import logging

from    telegram                    import Update
from    telegram.constants          import ChatAction
from    telegram.ext                import ContextTypes

from    handlers.text               import handle_text
from    services                    import speech


logger = logging.getLogger(__name__)

# Longer voice messages are refused before downloading (the service cuts at 2 min).
MAX_SECONDS = 120

NOT_SET_UP = "🎙 Voice messages aren't set up yet. Please type it."
UNAVAILABLE = "🎙 I can't understand voice messages right now. Please type it."
TOO_LONG = f"🎙 That's too long. Voice messages can be up to {MAX_SECONDS // 60} minutes."
NO_WORDS = "🎙 I couldn't make out any words. Try again, or type it."


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A voice message in a private chat."""
    message = update.effective_message
    if not speech.is_configured():
        await message.reply_text(NOT_SET_UP)
        return
    if (message.voice.duration or 0) > MAX_SECONDS:
        await message.reply_text(TOO_LONG)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    file = await message.voice.get_file()
    audio = bytes(await file.download_as_bytearray())

    try:
        text = await speech.transcribe(audio)
    except speech.SpeechUnavailable:
        logger.warning("speech-service unavailable", exc_info=True)
        await message.reply_text(UNAVAILABLE)
        return
    except speech.InvalidAudio:
        logger.warning("speech-service couldn't decode a voice message", exc_info=True)
        await message.reply_text(NO_WORDS)
        return

    if not text:
        await message.reply_text(NO_WORDS)
        return

    # Show what was heard, so a misheard word is obvious.
    await message.reply_text(f"🎙 “{text}”")
    await handle_text(update, context, text)
