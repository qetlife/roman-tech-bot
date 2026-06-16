import os

from    telegram.ext                import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from    dotenv                      import load_dotenv

from    menu.reminders_button       import on_reminders
from    menu.settings_button        import on_back_settings, on_my_id, on_settings
from    commands.menu_command       import menu_cmd, on_main_menu
from    commands.start_command      import start

def main():
    load_dotenv()

    BOT_TOKEN =     os.environ.get("BOT_TOKEN")

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

    app.run_polling()

if __name__ == "__main__":
    print("Running!")
    main()
