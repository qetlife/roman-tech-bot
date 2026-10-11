import logging
import os

from    telegram.ext                import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from    dotenv                      import load_dotenv

from    menu.reminders_button       import on_reminders
from    menu.settings_button        import on_back_settings, on_my_id, on_settings
from    commands.menu_command       import menu_cmd, on_main_menu
from    commands.start_command      import start
from    db.db                       import init_db
from    intents.text_handler        import on_text
from    reminders                   import handlers as reminders
from    reminders.delivery          import POLL_INTERVAL, deliver_due
from    settings                    import handlers as user_settings

def main():
    load_dotenv()

    logging.basicConfig(format="%(asctime)s %(levelname)s [%(name)s] %(message)s", level=logging.INFO)
    # httpx logs every Telegram poll at INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)

    BOT_TOKEN =     os.environ.get("BOT_TOKEN")

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))

    # Main Menu
    app.add_handler(CallbackQueryHandler(on_main_menu,    pattern=r"^menu:main$"))
    app.add_handler(CallbackQueryHandler(on_reminders,    pattern=r"^menu:reminders$"))
    app.add_handler(CallbackQueryHandler(on_settings,     pattern=r"^menu:settings$"))

    # Settings
    app.add_handler(CallbackQueryHandler(on_my_id,        pattern=r"^settings:my_id$"))
    app.add_handler(CallbackQueryHandler(on_back_settings, pattern=r"^settings:back$"))
    app.add_handler(CallbackQueryHandler(reminders.on_timezone_settings, pattern=r"^settings:timezone$"))
    app.add_handler(CallbackQueryHandler(user_settings.on_snooze_settings, pattern=r"^settings:snooze$"))
    app.add_handler(CallbackQueryHandler(user_settings.on_snooze_button,   pattern=r"^snzopt:"))

    # Reminders
    app.add_handler(CallbackQueryHandler(reminders.on_new,              pattern=r"^rem:new$"))
    app.add_handler(CallbackQueryHandler(reminders.list_reminders,      pattern=r"^rem:list$"))
    app.add_handler(CallbackQueryHandler(reminders.on_reminder_button,  pattern=r"^rem:(ok|snz|undo|edit|del):\d+"))
    app.add_handler(CallbackQueryHandler(reminders.on_timezone_button,  pattern=r"^tz:"))

    # Free text in private chats: trigger phrases ("remind me ...") and answers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text))

    # Sends due reminders; also catches up on anything due while the bot was down
    app.job_queue.run_repeating(deliver_due, interval=POLL_INTERVAL, first=1)

    app.run_polling()

if __name__ == "__main__":
    print("Running!")
    main()
