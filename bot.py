"""Entry point: registers the handlers and the delivery job, then polls Telegram."""

import logging

from    telegram                    import MenuButtonWebApp, Update, WebAppInfo
from    telegram.error              import TelegramError
from    telegram.ext                import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, TypeHandler, filters,
)

from    config                      import BOT_TOKEN, ERRORS_DIR, WEBAPP_URL, calendar_configured
from    core.errors                 import install as install_errors
from    db.session                  import init_db
from    handlers                    import calendar, failed, web
from    handlers.buttons            import BUTTONS
from    handlers.errors             import on_error
from    handlers.commands           import menu_cmd, start
from    handlers.text               import on_text
from    handlers.ui                 import remember_profile
from    handlers.voice              import on_voice
from    jobs                        import calendar as calendar_jobs
from    jobs.delivery               import POLL_INTERVAL, deliver_due
from    jobs.failed                 import resolve_understood



async def start_web(app):
    """With Google Calendar or the web app set up: the web server (Google's login and push, the web app)."""
    if calendar_configured() or WEBAPP_URL:
        app.bot_data["web"] = await web.start(app)
    if WEBAPP_URL:
        # The button next to the text box opens the web app (a Mini App)
        try:
            await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp("Open app", WebAppInfo(WEBAPP_URL)))
        except TelegramError:
            logging.getLogger(__name__).warning("Couldn't set the web app's menu button", exc_info=True)


async def stop_web(app):
    runner = app.bot_data.pop("web", None)
    if runner is not None:
        await runner.cleanup()


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s [%(name)s] %(message)s", level=logging.INFO)
    # httpx logs every Telegram poll at INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Unexpected errors (logger.exception) also go to a file, to review with scripts/errors.py
    error_file = install_errors(ERRORS_DIR)

    init_db()

    # A deploy may have taught the parser some failed messages: close them.
    try:
        resolve_understood()
    except Exception:
        logging.exception("Re-checking failed messages failed; starting anyway")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(start_web).post_shutdown(stop_web).build()

    # Before everything else: keep each user's Telegram name and @username up to date
    app.add_handler(TypeHandler(Update, remember_profile), group=-1)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("failed", failed.on_failed_cmd))         # admin only
    app.add_handler(CommandHandler("calendar", calendar.on_calendar_cmd))

    # Buttons (handlers/buttons.py: the web app uses the same list)
    for pattern, handler in BUTTONS:
        app.add_handler(CallbackQueryHandler(handler, pattern=pattern))

    # Free text in private chats: trigger phrases ("remind me ...") and answers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text))

    # Voice messages in private chats: transcribed, then handled like text
    app.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, on_voice))

    # Sends due reminders; also catches up on anything due while the bot was down
    app.job_queue.run_repeating(deliver_due, interval=POLL_INTERVAL, first=1)
    # Google Calendar: daily sync and push channel renewal (nothing if it isn't set up)
    app.job_queue.run_repeating(calendar_jobs.daily, interval=calendar_jobs.DAILY, first=300)

    # Anything a handler or job didn't handle: recorded, and the user gets a short apology
    app.add_error_handler(on_error)

    try:
        app.run_polling()
    finally:
        if error_file is not None:
            error_file.close()

if __name__ == "__main__":
    print("Running!")
    main()
