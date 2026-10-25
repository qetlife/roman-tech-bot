import uuid

from typing             import Optional

from sqlalchemy         import delete, select

from db.session         import SessionLocal
from db.models.google   import GoogleAccount, GoogleCalendar
from db.models.reminder import utcnow
from enums              import GoogleStatus


class GoogleRepository:
    """Linked Google accounts and their calendars. The refresh token is stored as given (encrypted by the caller)."""

    def account(self, user_id: uuid.UUID) -> Optional[GoogleAccount]:
        with SessionLocal(expire_on_commit=False) as session:
            return session.get(GoogleAccount, user_id)

    def link(self, user_id: uuid.UUID, refresh_token: str) -> GoogleAccount:
        """Link (or link again): a new login, linked from now."""
        with SessionLocal(expire_on_commit=False) as session:
            account = session.get(GoogleAccount, user_id, with_for_update=True)
            if account is None:
                account = GoogleAccount(user_id=user_id, refresh_token=refresh_token)
                session.add(account)
            account.refresh_token, account.status, account.linked_at = refresh_token, GoogleStatus.LINKED, utcnow()
            session.commit()
            return account

    def update_account(self, user_id: uuid.UUID, **values) -> Optional[GoogleAccount]:
        with SessionLocal(expire_on_commit=False) as session:
            account = session.get(GoogleAccount, user_id, with_for_update=True)
            if account is None:
                return None
            for key, value in values.items():
                setattr(account, key, value)
            session.commit()
            return account

    def claim_poll(self, user_id: uuid.UUID, since) -> bool:
        """Whether to sync now: linked and not synced after `since`. Marks it synced now, so only one caller does."""
        with SessionLocal(expire_on_commit=False) as session:
            account = session.get(GoogleAccount, user_id, with_for_update=True)
            if account is None or account.status != GoogleStatus.LINKED \
                    or (account.last_poll_at is not None and account.last_poll_at > since):
                return False
            account.last_poll_at = utcnow()
            session.commit()
            return True

    def unlink(self, user_id: uuid.UUID) -> None:
        with SessionLocal() as session:
            session.execute(delete(GoogleCalendar).where(GoogleCalendar.user_id == user_id))
            session.execute(delete(GoogleAccount).where(GoogleAccount.user_id == user_id))
            session.commit()

    def linked(self) -> list:
        """Every account that is linked (not expired)."""
        with SessionLocal(expire_on_commit=False) as session:
            return list(session.scalars(select(GoogleAccount).where(GoogleAccount.status == GoogleStatus.LINKED)))

    # --- calendars ----------------------------------------------------------

    def calendars(self, user_id: uuid.UUID) -> list:
        """The user's calendars, primary first, then by name."""
        with SessionLocal(expire_on_commit=False) as session:
            items = list(session.scalars(select(GoogleCalendar).where(GoogleCalendar.user_id == user_id)))
            return sorted(items, key=lambda c: (not c.primary, c.summary.lower()))

    def calendar(self, calendar_row_id: int) -> Optional[GoogleCalendar]:
        with SessionLocal(expire_on_commit=False) as session:
            return session.get(GoogleCalendar, calendar_row_id)

    def by_channel(self, channel_id: str) -> Optional[GoogleCalendar]:
        with SessionLocal(expire_on_commit=False) as session:
            return session.scalar(select(GoogleCalendar).where(GoogleCalendar.channel_id == channel_id))

    def save_calendars(self, user_id: uuid.UUID, items: list) -> list:
        """Google's calendar list: new ones are added (the primary one synced), gone ones removed, names refreshed.

        Returns the removed ones (to stop their push channels).
        """
        with SessionLocal(expire_on_commit=False) as session:
            rows = {c.calendar_id: c for c in session.scalars(
                select(GoogleCalendar).where(GoogleCalendar.user_id == user_id))}
            seen = set()
            for item in items:
                seen.add(item["id"])
                row = rows.get(item["id"])
                if row is None:
                    row = GoogleCalendar(user_id=user_id, calendar_id=item["id"], selected=bool(item.get("primary")))
                    session.add(row)
                row.summary = item.get("summaryOverride") or item.get("summary") or item["id"]
                row.time_zone = item.get("timeZone")
                row.primary = bool(item.get("primary"))
                row.writable = item.get("accessRole", "owner") in ("owner", "writer")
            removed = [row for calendar_id, row in rows.items() if calendar_id not in seen]
            for row in removed:
                session.delete(row)
            session.commit()
            return removed

    def update_calendar(self, calendar_row_id: int, **values) -> Optional[GoogleCalendar]:
        with SessionLocal(expire_on_commit=False) as session:
            row = session.get(GoogleCalendar, calendar_row_id, with_for_update=True)
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()
            return row
