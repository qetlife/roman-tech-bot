import uuid

from datetime           import datetime
from typing             import Optional

from sqlalchemy         import Boolean, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm     import Mapped, mapped_column

from enums              import GoogleStatus
from db.models.reminder import BigIntId, utcnow
from db.models.types    import UTCDateTime
from db.models.user     import Base


class GoogleAccount(Base):
    """A user's linked Google Calendar: their login (encrypted) and when it was last synced."""

    __tablename__ = "google_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # The OAuth refresh token, encrypted with CALENDAR_KEY (core/secrets.py)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GoogleStatus] = mapped_column(
        Enum(GoogleStatus, native_enum=False, create_constraint=False, length=16,
             values_callable=lambda members: [m.value for m in members]),
        nullable=False, default=GoogleStatus.LINKED,
    )
    # Google's calendar id of the one new events from the bot go to
    default_calendar_id: Mapped[Optional[str]] = mapped_column(String(255))
    linked_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # Last sync from Google (for the 5-minute limit on syncing when the user asks something)
    last_poll_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class GoogleCalendar(Base):
    """One of a linked user's Google calendars, synced or not, with its sync state."""

    __tablename__ = "google_calendars"

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    calendar_id: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # IANA name; all-day events and events without their own timezone use it
    time_zone: Mapped[Optional[str]] = mapped_column(String(64))
    primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The user may add events to it (owner or writer), so new events from the bot can go there
    writable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # From events.list: what changed since (None: sync everything)
    sync_token: Mapped[Optional[str]] = mapped_column(Text)
    # Push notifications (events.watch); the token comes back with each one, to check it's Google
    channel_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    channel_resource_id: Mapped[Optional[str]] = mapped_column(String(255))
    channel_token: Mapped[Optional[str]] = mapped_column(String(64))
    channel_expires_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)

    __table_args__ = (UniqueConstraint("user_id", "calendar_id", name="uq_google_calendars_user_calendar"),)
