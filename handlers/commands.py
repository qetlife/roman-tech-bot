"""Slash commands: /start, /menu."""

import logging

from    telegram                        import Update
from    telegram.ext                    import ContextTypes

from    db.repositories.user            import UserRepository
from    handlers.menus                  import MAIN_MENU_TEXT, build_main_menu
from    handlers.ui                     import render_menu

logger = logging.getLogger(__name__)

repo = UserRepository()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        repo.get_or_create(update.effective_user.id)
    except Exception:
        # Still show the menu; the user is registered on their next action.
        logger.exception("Failed to register user %s on /start", update.effective_user.id)
    await render_menu(update, context,
        "Hi! I’m your assistant. Here’s your menu:",
        build_main_menu()
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_menu(update, context, MAIN_MENU_TEXT, build_main_menu())
