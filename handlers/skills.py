"""“What can you do?”: the assistant's skills (core/skills.py), with an example of each."""

from    telegram                    import Update
from    telegram.ext                import ContextTypes

from    core.skills                 import available, describe
from    services                    import google_calendar as google


def skills() -> list:
    return available(calendar=google.is_configured())


async def what_i_can_do(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str = ""):
    """Intent action for "what can you do?"; anything after the phrase is ignored."""
    mine = skills()
    await update.effective_message.reply_text(describe(mine))
