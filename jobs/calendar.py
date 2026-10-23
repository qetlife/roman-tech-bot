"""Google Calendar jobs: the daily sync (in case a push notification got lost) and renewing push channels."""

import logging

from    datetime                    import timedelta

from    telegram.ext                import ContextTypes

from    handlers                    import calendar
from    services                    import google_calendar as google


logger = logging.getLogger(__name__)

DAILY = timedelta(hours=24)


async def daily(context: ContextTypes.DEFAULT_TYPE):
    """Job, once a day (and a few minutes after startup): renew push channels, then sync every linked user."""
    if not google.is_configured():
        return
    try:
        await calendar.renew_channels(context.bot)
    except Exception:
        logger.exception("Renewing Google push channels failed")
    await calendar.sync_everyone(context.bot)
