"""Slash commands: /start, /menu."""

import logging

from    telegram                        import Update
from    telegram.ext                    import ContextTypes

from    db.repositories.user            import UserRepository
from    handlers.menus                  import MAIN_MENU_TEXT, build_main_menu
from    handlers.people                 import INVITE_PREFIX, on_start_invite
from    handlers.ui                     import render_menu

logger = logging.getLogger(__name__)

repo = UserRepository()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start, also from a link: "/start inv_<token>" is an invite (handlers/people.py)."""
    tg_user = update.effective_user
    try:
        repo.get_or_create(tg_user.id)
        repo.remember_profile(tg_user.id, tg_user.first_name, tg_user.username)
    except Exception:
        # Still show the menu; the user is registered on their next action.
        logger.exception("Failed to register user %s on /start", tg_user.id)
    payload = context.args[0] if context.args else ""
    if payload.startswith(INVITE_PREFIX):
        await on_start_invite(update, context, payload.removeprefix(INVITE_PREFIX))
        return
    await render_menu(update, context,
        "Hi! I’m your assistant. Here’s your menu:",
        build_main_menu()
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_menu(update, context, MAIN_MENU_TEXT, build_main_menu())
