"""Client for Google's OAuth and the Calendar API (v3), over plain HTTPS.

The bot asks for two scopes: `calendar.events` (read and change events, and
watch a calendar for changes) and `calendar.calendarlist.readonly` (the
names of the user's calendars). Access tokens live in memory only; the
refresh token is what's stored (encrypted, db/models/google.py).
"""

import time

from typing     import Optional
from urllib.parse import quote, urlencode, urlsplit

import httpx

import config


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
TIMEOUT = 20

# Set by tests to fake Google (an httpx.MockTransport).
transport = None

# refresh token → (access token, expires at, time.time()); refreshed a minute early
_access = {}


class GoogleUnavailable(Exception):
    """Google can't be reached or failed; try again later."""


class GoogleAuthError(Exception):
    """Google refused the login (expired, revoked): the user has to link again."""


class SyncExpired(Exception):
    """The sync token is too old (HTTP 410): sync everything again."""


class NotFound(Exception):
    """No such event or calendar (any more)."""


def is_configured() -> bool:
    return config.calendar_configured()


def push_address() -> Optional[str]:
    """Where Google sends push notifications: /google/push next to the OAuth callback; None unless HTTPS."""
    parts = urlsplit(config.GOOGLE_REDIRECT_URI or "")
    return f"https://{parts.netloc}/google/push" if parts.scheme == "https" else None


def auth_url(state: str) -> str:
    """Google's consent page; it comes back to GOOGLE_REDIRECT_URI with `code` and `state`."""
    return AUTH_URL + "?" + urlencode({
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        # A refresh token, also when linking again
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    })


async def _post(url: str, data: dict) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            return await client.post(url, data=data)
    except httpx.HTTPError as e:
        raise GoogleUnavailable(f"{type(e).__name__}: {e}") from e


async def exchange_code(code: str) -> dict:
    """The tokens for the `code` from the consent page: {"refresh_token", "access_token", "expires_in", "scope"}."""
    response = await _post(TOKEN_URL, {
        "code": code, "client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": config.GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
    })
    if response.status_code in (400, 401):
        raise GoogleAuthError(response.text[:200])
    if response.status_code != 200:
        raise GoogleUnavailable(f"HTTP {response.status_code}: {response.text[:200]}")
    tokens = response.json()
    _access[tokens.get("refresh_token")] = (tokens["access_token"], time.time() + tokens.get("expires_in", 3600) - 60)
    return tokens


async def access_token(refresh_token: str) -> str:
    cached = _access.get(refresh_token)
    if cached is not None and cached[1] > time.time():
        return cached[0]
    response = await _post(TOKEN_URL, {
        "refresh_token": refresh_token, "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET, "grant_type": "refresh_token",
    })
    if response.status_code in (400, 401):
        # invalid_grant: expired (7 days while the app is in testing) or revoked
        _access.pop(refresh_token, None)
        raise GoogleAuthError(response.text[:200])
    if response.status_code != 200:
        raise GoogleUnavailable(f"HTTP {response.status_code}: {response.text[:200]}")
    tokens = response.json()
    _access[refresh_token] = (tokens["access_token"], time.time() + tokens.get("expires_in", 3600) - 60)
    return tokens["access_token"]


async def revoke(refresh_token: str) -> None:
    """Give the login back (unlinking). Failing is fine: it expires anyway."""
    _access.pop(refresh_token, None)
    try:
        await _post(REVOKE_URL, {"token": refresh_token})
    except GoogleUnavailable:
        pass


class Calendar:
    """The Calendar API as one user (their refresh token)."""

    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token

    async def _request(self, method: str, path: str, params: dict = None, json: dict = None) -> Optional[dict]:
        token = await access_token(self.refresh_token)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
                response = await client.request(method, API + path, params=params, json=json,
                                                headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise GoogleUnavailable(f"{type(e).__name__}: {e}") from e
        if response.status_code == 401:
            _access.pop(self.refresh_token, None)
            raise GoogleAuthError(response.text[:200])
        if response.status_code == 403 and "insufficient" in response.text.lower():
            # Linked before the bot needed a scope it asks for now
            raise GoogleAuthError(response.text[:200])
        if response.status_code == 410:
            raise SyncExpired(response.text[:200])
        if response.status_code == 404:
            raise NotFound(path)
        if response.status_code >= 300:
            raise GoogleUnavailable(f"HTTP {response.status_code}: {response.text[:200]}")
        return response.json() if response.content else None

    @staticmethod
    def _id(calendar_id: str) -> str:
        return quote(calendar_id, safe="")

    async def calendars(self) -> list:
        """The user's calendars: [{"id", "summary", "timeZone", "primary", "accessRole"}, …]."""
        found, page = [], None
        while True:
            body = await self._request("GET", "/users/me/calendarList",
                                       params={"maxResults": 250, **({"pageToken": page} if page else {})})
            found += body.get("items", [])
            page = body.get("nextPageToken")
            if not page:
                return found

    async def events(self, calendar_id: str, sync_token: Optional[str] = None, page_token: Optional[str] = None) -> dict:
        """One page of events.list: all of them (deleted ones too), or what changed since `sync_token`.

        Repeating events come as one event with their RRULE; a single changed
        or cancelled occurrence comes as its own event (`recurringEventId`).
        """
        params = {"maxResults": 250, "showDeleted": "true", "singleEvents": "false"}
        if sync_token:
            params["syncToken"] = sync_token
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", f"/calendars/{self._id(calendar_id)}/events", params=params)

    async def insert(self, calendar_id: str, body: dict) -> dict:
        return await self._request("POST", f"/calendars/{self._id(calendar_id)}/events", json=body)

    async def patch(self, calendar_id: str, event_id: str, body: dict) -> dict:
        return await self._request("PATCH", f"/calendars/{self._id(calendar_id)}/events/{quote(event_id, safe='')}",
                                   json=body)

    async def delete(self, calendar_id: str, event_id: str) -> None:
        try:
            await self._request("DELETE", f"/calendars/{self._id(calendar_id)}/events/{quote(event_id, safe='')}")
        except (NotFound, SyncExpired):
            # Already gone (410: deleted)
            pass

    async def watch(self, calendar_id: str, channel_id: str, token: str, address: str) -> dict:
        """Push notifications for changes to a calendar's events: {"resourceId", "expiration" (ms)}."""
        return await self._request("POST", f"/calendars/{self._id(calendar_id)}/events/watch", json={
            "id": channel_id, "type": "web_hook", "address": address, "token": token,
        })

    async def stop(self, channel_id: str, resource_id: str) -> None:
        try:
            await self._request("POST", "/channels/stop", json={"id": channel_id, "resourceId": resource_id})
        except NotFound:
            pass
