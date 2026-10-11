import logging
import os
import re

from    telegram.ext                import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from    dotenv                      import load_dotenv

from    menu.reminders_button       import on_reminders
from    menu.settings_button        import on_back_settings, on_my_id, on_settings
from    commands.menu_command       import menu_cmd, on_main_menu
from    commands.start_command      import start
from    db.db                       import init_db
from    enums                       import Callback, CallbackPrefix, ReminderAction
from    helpers.callbacks           import exact, prefixed
from    intents.text_handler        import on_text
from    reminders                   import handlers as reminders
from    reminders.delivery          import POLL_INTERVAL, deliver_due
from    settings                    import handlers as user_settings

# rem:<action>:<id>[:<minutes>]; "rem:new" etc. are separate buttons.
REMINDER_BUTTON = (
    "^" + re.escape(CallbackPrefix.REMINDER) + "(?:" + "|".join(ReminderAction) + r"):\d+"
)


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
    app.add_handler(CallbackQueryHandler(on_main_menu,    pattern=exact(Callback.MAIN_MENU)))
    app.add_handler(CallbackQueryHandler(on_reminders,    pattern=exact(Callback.REMINDERS_MENU)))
    app.add_handler(CallbackQueryHandler(on_settings,     pattern=exact(Callback.SETTINGS_MENU)))

    # Settings
    app.add_handler(CallbackQueryHandler(on_my_id,        pattern=exact(Callback.MY_ID)))
    app.add_handler(CallbackQueryHandler(on_back_settings, pattern=exact(Callback.SETTINGS_BACK)))
    app.add_handler(CallbackQueryHandler(reminders.on_timezone_settings, pattern=exact(Callback.TIMEZONE_SETTINGS)))
    app.add_handler(CallbackQueryHandler(user_settings.on_reminder_settings, pattern=exact(
        Callback.REMINDER_SETTINGS, Callback.REMINDER_SETTINGS_FROM_MENU, Callback.REMINDER_SETTINGS_RETURN,
    )))
    app.add_handler(CallbackQueryHandler(user_settings.on_snooze_settings, pattern=exact(Callback.SNOOZE_SETTINGS)))
    app.add_handler(CallbackQueryHandler(user_settings.on_snooze_button,   pattern=prefixed(CallbackPrefix.SNOOZE_OPTION)))
    app.add_handler(CallbackQueryHandler(user_settings.on_repeat_settings, pattern=exact(Callback.REPEAT_SETTINGS)))
    app.add_handler(CallbackQueryHandler(user_settings.on_repeat_button,   pattern=prefixed(CallbackPrefix.REPEAT_OPTION)))
    app.add_handler(CallbackQueryHandler(user_settings.on_quiet_settings,  pattern=exact(Callback.QUIET_SETTINGS)))
    app.add_handler(CallbackQueryHandler(user_settings.on_quiet_button,    pattern=prefixed(CallbackPrefix.QUIET_OPTION)))

    # Reminders
    app.add_handler(CallbackQueryHandler(reminders.on_new,              pattern=exact(Callback.NEW_REMINDER)))
    app.add_handler(CallbackQueryHandler(reminders.list_reminders,      pattern=exact(Callback.LIST_REMINDERS)))
    app.add_handler(CallbackQueryHandler(reminders.on_reminder_button,  pattern=REMINDER_BUTTON))
    app.add_handler(CallbackQueryHandler(reminders.on_timezone_button,  pattern=prefixed(CallbackPrefix.TIMEZONE)))

    # Free text in private chats: trigger phrases ("remind me ...") and answers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text))

    # Sends due reminders; also catches up on anything due while the bot was down
    app.job_queue.run_repeating(deliver_due, interval=POLL_INTERVAL, first=1)

    app.run_polling()

if __name__ == "__main__":
    print("Running!")
    main()
