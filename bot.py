import os

from    telegram.ext                import ApplicationBuilder, CommandHandler, MessageHandler, filters
from    dotenv                      import load_dotenv

from    menu.reminders_button       import on_reminders
from    menu.settings_button        import on_back_settings, on_my_id, on_settings
from    commands.menu_command       import menu_cmd, hide_menu
from    commands.start_command      import start

def main():
    load_dotenv()

    BOT_TOKEN =     os.environ.get("BOT_TOKEN")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))

    #Main Menu
    app.add_handler(MessageHandler(filters.Regex(r"^⏰ Reminders$"), on_reminders))
    app.add_handler(MessageHandler(filters.Regex(r"^⚙️ Settings$"), on_settings))
    app.add_handler(MessageHandler(filters.Regex(r"^⬇️ Hide Menu$"), hide_menu))
    
    #Settings
    app.add_handler(MessageHandler(filters.Regex(r"^↩️ Back$"), on_back_settings))
    app.add_handler(MessageHandler(filters.Regex(r"^🆔 My ID$"), on_my_id))



    app.run_polling()

if __name__ == "__main__":
    print("Running!")
    main()
    