"""Encrypting Google logins, and signing the state that comes back from Google's login page.

`key` is CALENDAR_KEY (a Fernet key). No Telegram, no database.
"""

import hashlib
import hmac
import time

from typing                 import Optional

from cryptography.fernet    import Fernet, InvalidToken

# How long a "🔗 Link Google Calendar" button works
STATE_MAX_AGE = 15 * 60


def encrypt(text: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(text.encode()).decode()


def decrypt(token: str, key: str) -> Optional[str]:
    """The text, or None if it wasn't encrypted with this key (the key changed)."""
    try:
        return Fernet(key.encode()).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def _mac(payload: str, key: str) -> str:
    # A key of its own for signing, derived from the encryption key
    signing_key = hashlib.sha256(b"state:" + key.encode()).digest()
    return hmac.new(signing_key, payload.encode(), hashlib.sha256).hexdigest()[:32]


def sign_state(telegram_id: int, key: str, now: float = None) -> str:
    """The OAuth `state` for a user: who it is for and when, signed so nobody can link their Google to someone else."""
    payload = f"{telegram_id}.{int(now if now is not None else time.time())}"
    return f"{payload}.{_mac(payload, key)}"


def verify_state(state: str, key: str, now: float = None) -> Optional[int]:
    """The Telegram id in a state made by sign_state, or None if it's forged or older than STATE_MAX_AGE."""
    try:
        telegram_id, made, mac = state.split(".")
        made_at, user = int(made), int(telegram_id)
    except ValueError:
        return None
    if not hmac.compare_digest(mac, _mac(f"{telegram_id}.{made}", key)):
        return None
    if (now if now is not None else time.time()) - made_at > STATE_MAX_AGE:
        return None
    return user
