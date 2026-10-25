import uuid

from datetime           import datetime
from typing             import Optional

from sqlalchemy         import Boolean, Enum, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm     import Mapped, mapped_column

from enums              import EventStatus, ExternalSource, MessageSource
from db.models.reminder import BigIntId, utcnow
from db.models.types    import UTCDateTime
from db.models.user     import Base


def _enum(enum_class):
    """Stored as its value in a plain VARCHAR(16), like reminders.status."""
    return Enum(enum_class, native_enum=False, create_constraint=False, length=16,
                values_callable=lambda members: [m.value for m in members])


class Event(Base):
    """Something that happens at a time ("padel on thursday at 21:00"), maybe every week.

    Reminders can hang off it (reminders.event_id): they move and are
    cancelled with it. Laid out for syncing with Google Calendar (#22):
    times in UTC plus the event's own timezone, a repeat that maps to an
    RRULE, skipped occurrences (EXDATE) and room for the external ids.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # One-off: when it starts; repeating: its first occurrence. An all-day
    # event starts at the midnight of its day.
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ends_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # IANA name: the clock of its time and repeat (its creator's when made)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # An RFC 5545 RRULE ("FREQ=WEEKLY;BYDAY=TH") from `starts_at`, in `timezone`;
    # older events may have the bot's own format (core/recurrence.py). None = once
    recurrence: Mapped[Optional[str]] = mapped_column(Text)
    # Occurrences that don't happen (EXDATE), "20261029T2000Z,…" (UTC; past ones are dropped)
    skipped: Mapped[Optional[str]] = mapped_column(Text)
    # Single occurrences moved in Google Calendar, "<original>><new>,…" (UTC stamps)
    moved: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[EventStatus] = mapped_column(_enum(EventStatus), nullable=False, default=EventStatus.ACTIVE)
    # The message it was made (or last edited) from, and how it came in; saved with 👎 Wrong
    request: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[MessageSource]] = mapped_column(_enum(MessageSource))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    # Synced with Google Calendar: which calendar, its id and version there, and
    # when Google last changed it. None for events only in the bot.
    external_source: Mapped[Optional[ExternalSource]] = mapped_column(_enum(ExternalSource))
    external_calendar_id: Mapped[Optional[str]] = mapped_column(String(255))
    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    etag: Mapped[Optional[str]] = mapped_column(String(255))
    external_updated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    # Changed in the bot but not yet in Google (it was unreachable): sent on the next sync
    pending_push: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_events_user_id_status", "user_id", "status"),
        Index("ix_events_external", "user_id", "external_calendar_id", "external_id"),
    )
