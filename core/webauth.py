"""Who is using the web app: Telegram's signed login data, and the app's own session token.

- Inside Telegram (a Mini App), the page gets `initData`, signed with a key
  made from the bot token ("WebAppData"):
  https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
- In a browser, the Telegram Login Widget gives fields signed with the
  SHA-256 of the bot token: https://core.telegram.org/widgets/login#checking-authorization
- Either way the app then gets a session token (`sign_session`) for its
  API calls, signed with a key derived from the bot token.

No Telegram, no database.
"""

import hashlib
import hmac
import json
import time

from typing         import Optional
from urllib.parse   import parse_qsl


# Telegram's login data is used only this soon after it was made
LOGIN_MAX_AGE = 24 * 3600
# A session lasts this long; then the page logs in again (inside Telegram, without asking)
SESSION_MAX_AGE = 30 * 24 * 3600


def _now(now: Optional[float]) -> float:
    return now if now is not None else time.time()


def _check_string(fields: dict) -> str:
    return "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))


def check_init_data(init_data: str, bot_token: str, now: float = None) -> Optional[dict]:
    """The Telegram user ({"id", "first_name", "username", …}) in a Mini App's initData, or None if not genuine."""
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    given = fields.pop("hash", None)
    if not given:
        return None
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, _check_string(fields).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(given, expected):
        return None
    if not _fresh(fields.get("auth_date"), now):
        return None
    try:
        user = json.loads(fields.get("user", ""))
    except ValueError:
        return None
    return user if isinstance(user, dict) and isinstance(user.get("id"), int) else None


def check_login(fields: dict, bot_token: str, now: float = None) -> Optional[dict]:
    """The Telegram user in the Login Widget's fields ({"id", "first_name", …, "auth_date", "hash"}), or None."""
    fields = {k: str(v) for k, v in fields.items() if v is not None}
    given = fields.pop("hash", None)
    if not given:
        return None
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, _check_string(fields).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(given, expected) or not _fresh(fields.get("auth_date"), now):
        return None
    try:
        user_id = int(fields["id"])
    except (KeyError, ValueError):
        return None
    return {"id": user_id, "first_name": fields.get("first_name"), "username": fields.get("username")}


def _fresh(auth_date: Optional[str], now: Optional[float]) -> bool:
    try:
        made = int(auth_date)
    except (TypeError, ValueError):
        return False
    return 0 <= _now(now) - made <= LOGIN_MAX_AGE


def _session_mac(payload: str, bot_token: str) -> str:
    key = hashlib.sha256(b"webapp-session:" + bot_token.encode()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def sign_session(telegram_id: int, bot_token: str, now: float = None) -> str:
    payload = f"{telegram_id}.{int(_now(now))}"
    return f"{payload}.{_session_mac(payload, bot_token)}"


def verify_session(token: str, bot_token: str, now: float = None) -> Optional[int]:
    """The Telegram id in a token from sign_session, or None if it's forged or older than SESSION_MAX_AGE."""
    try:
        telegram_id, made, mac = token.split(".")
        user, made_at = int(telegram_id), int(made)
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(mac, _session_mac(f"{telegram_id}.{made}", bot_token)):
        return None
    if not 0 <= _now(now) - made_at <= SESSION_MAX_AGE:
        return None
    return user
