from    telegram                        import Update
from    telegram.ext                    import ContextTypes

from    commands.menu_command           import build_main_menu
from    helpers.chat_helper             import render_menu
from    db.repository.user_repository   import UserRepository

repo = UserRepository()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        telegram_id = update.effective_user.id
        user = repo.get_or_create(telegram_id)
    except:
        pass #TODO: log
    await render_menu(update, context,
        "Hi! I’m your assistant. Here’s your menu:",
        build_main_menu()
    )
