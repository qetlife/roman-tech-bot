"""The bot's small web server, for Google: the OAuth callback and push notifications.

Runs next to Telegram polling, in the same event loop (started by bot.py),
on WEB_PORT, only when Google Calendar is set up. Nginx and Cloudflare put
it at the host of GOOGLE_REDIRECT_URI (docs/setup.md).

    GET  /oauth/callback   Google's consent page sends the user back here
    POST /google/push      Google says a synced calendar changed
    GET  /health           "ok", to check the route works
"""

import html
import logging

from    aiohttp                     import web

import  config

from    handlers                    import calendar


logger = logging.getLogger(__name__)

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Google Calendar</title>
<style>body{{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;line-height:1.5}}</style>
</head><body><p>{message}</p>{back}</body></html>"""


def _page(message: str, bot_username: str = None, status: int = 200) -> web.Response:
    back = f'<p><a href="https://t.me/{html.escape(bot_username)}">Back to Telegram</a></p>' if bot_username else ""
    return web.Response(text=PAGE.format(message=html.escape(message), back=back), content_type="text/html",
                        status=status)


async def oauth_callback(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    username = getattr(bot, "username", None)
    if request.query.get("error"):
        # The user said no on Google's page
        return _page("Linking was cancelled. Nothing was changed.", username)
    state, code = request.query.get("state"), request.query.get("code")
    if not state or not code:
        return _page("This page is for linking Google Calendar from the bot.", username, status=400)
    try:
        message = await calendar.complete_link(bot, state, code)
    except Exception:
        logger.exception("Linking Google Calendar failed")
        message = "Something went wrong. Open 📅 Calendar in the bot and try again."
    return _page(message, username)


async def google_push(request: web.Request) -> web.Response:
    known = await calendar.on_push(
        request.app["bot"], request.headers.get("X-Goog-Channel-ID"), request.headers.get("X-Goog-Channel-Token"),
        request.headers.get("X-Goog-Resource-State"),
    )
    # 200 either way would keep an unknown channel alive; Google stops one that answers 404
    return web.Response(status=200 if known else 404)


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def make_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/oauth/callback", oauth_callback)
    app.router.add_post("/google/push", google_push)
    app.router.add_get("/health", health)
    return app


async def start(bot) -> web.AppRunner:
    """Start serving on WEB_PORT; returns the runner, to stop it on shutdown."""
    runner = web.AppRunner(make_app(bot), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.WEB_PORT).start()
    logger.info("Web server for Google Calendar on port %s", config.WEB_PORT)
    return runner
