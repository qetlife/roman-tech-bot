"""Entry point: registers the handlers and the delivery job, then polls Telegram."""

import logging
import re

from    telegram.ext                import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from    config                      import BOT_TOKEN
from    db.session                  import init_db
from    enums                       import Callback, CallbackPrefix, ReminderAction
from    handlers                    import failed, reminders, settings
from    handlers.commands           import menu_cmd, start
from    handlers.menus              import on_main_menu, on_my_id, on_reminders, on_settings
from    handlers.text               import on_text
from    handlers.ui                 import exact, prefixed
from    handlers.voice              import on_voice
from    jobs.delivery               import POLL_INTERVAL, deliver_due

# rem:<action>:<id>[:<minutes>]; "rem:new" etc. are separate buttons.
REMINDER_BUTTON = (
    "^" + re.escape(CallbackPrefix.REMINDER) + "(?:" + "|".join(ReminderAction) + r"):\d+"
)


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s [%(name)s] %(message)s", level=logging.INFO)
    # httpx logs every Telegram poll at INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("failed", failed.on_failed_cmd))         # admin only

    # Main Menu
    app.add_handler(CallbackQueryHandler(on_main_menu,    pattern=exact(Callback.MAIN_MENU, Callback.SETTINGS_BACK)))
    app.add_handler(CallbackQueryHandler(on_reminders,    pattern=exact(Callback.REMINDERS_MENU)))
    app.add_handler(CallbackQueryHandler(on_settings,     pattern=exact(Callback.SETTINGS_MENU)))

    # Settings
    app.add_handler(CallbackQueryHandler(on_my_id,        pattern=exact(Callback.MY_ID)))
    app.add_handler(CallbackQueryHandler(settings.on_timezone_settings, pattern=exact(Callback.TIMEZONE_SETTINGS)))
    app.add_handler(CallbackQueryHandler(settings.on_timezone_button,   pattern=prefixed(CallbackPrefix.TIMEZONE)))
    app.add_handler(CallbackQueryHandler(settings.on_reminder_settings, pattern=exact(
        Callback.REMINDER_SETTINGS, Callback.REMINDER_SETTINGS_FROM_MENU, Callback.REMINDER_SETTINGS_RETURN,
    )))
    app.add_handler(CallbackQueryHandler(settings.on_snooze_settings, pattern=exact(Callback.SNOOZE_SETTINGS)))
    app.add_handler(CallbackQueryHandler(settings.on_snooze_button,   pattern=prefixed(CallbackPrefix.SNOOZE_OPTION)))
    app.add_handler(CallbackQueryHandler(settings.on_repeat_settings, pattern=exact(Callback.REPEAT_SETTINGS)))
    app.add_handler(CallbackQueryHandler(settings.on_repeat_button,   pattern=prefixed(CallbackPrefix.REPEAT_OPTION)))
    app.add_handler(CallbackQueryHandler(settings.on_quiet_settings,  pattern=exact(Callback.QUIET_SETTINGS)))
    app.add_handler(CallbackQueryHandler(settings.on_quiet_button,    pattern=prefixed(CallbackPrefix.QUIET_OPTION)))

    # Reminders
    app.add_handler(CallbackQueryHandler(reminders.on_new,              pattern=exact(Callback.NEW_REMINDER)))
    app.add_handler(CallbackQueryHandler(reminders.list_reminders,      pattern=exact(Callback.LIST_REMINDERS)))
    app.add_handler(CallbackQueryHandler(reminders.on_reminder_button,  pattern=REMINDER_BUTTON))

    # Failed messages (/failed list)
    app.add_handler(CallbackQueryHandler(failed.on_failed_button,       pattern=prefixed(CallbackPrefix.FAILED_FIXED)))

    # Free text in private chats: trigger phrases ("remind me ...") and answers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text))

    # Voice messages in private chats: transcribed, then handled like text
    app.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, on_voice))

    # Sends due reminders; also catches up on anything due while the bot was down
    app.job_queue.run_repeating(deliver_due, interval=POLL_INTERVAL, first=1)

    app.run_polling()

if __name__ == "__main__":
    print("Running!")
    main()
