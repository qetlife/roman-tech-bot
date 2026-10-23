import uuid

from datetime           import datetime
from typing             import Optional

from sqlalchemy         import JSON, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm     import Mapped, mapped_column

from enums              import FailureReason, FailureStatus, MessageSource
from db.models.reminder import BigIntId, utcnow
from db.models.types    import UTCDateTime
from db.models.user     import Base


def _enum(enum_class):
    """Stored as its value in a plain VARCHAR(16), like reminders.status."""
    return Enum(enum_class, native_enum=False, create_constraint=False, length=16,
                values_callable=lambda members: [m.value for m in members])


class FailedMessage(Base):
    """A message the bot didn't understand, or got wrong according to the user.

    Not tied to reminders: `intent` says what the bot thought was asked, and
    `bot_understood` is a snapshot of what it made of it (it survives edits).
    """

    __tablename__ = "failed_messages"

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # What the parser was given (for voice: the transcript)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[MessageSource] = mapped_column(_enum(MessageSource), nullable=False)
    reason: Mapped[FailureReason] = mapped_column(_enum(FailureReason), nullable=False)
    # An IntentName value; None if no intent matched
    intent: Mapped[Optional[str]] = mapped_column(String(64))
    # Not understood: {"error": ...}; wrong result: {"text", "remind_at", "recurrence"},
    # or for an event {"title", "starts_at", "recurrence", "all_day"}
    bot_understood: Mapped[Optional[dict]] = mapped_column(JSON)
    reminder_id: Mapped[Optional[int]] = mapped_column(BigIntId, ForeignKey("reminders.id", ondelete="SET NULL"))
    event_id: Mapped[Optional[int]] = mapped_column(BigIntId, ForeignKey("events.id", ondelete="SET NULL"))
    status: Mapped[FailureStatus] = mapped_column(_enum(FailureStatus), nullable=False, default=FailureStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # When it stopped being open (fixed or ignored)
    fixed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    # Why it was fixed or ignored, e.g. "garbled transcript"; while open, what it waits for
    note: Mapped[Optional[str]] = mapped_column(Text)
    # The pull request that teaches the parser this message, while waiting to be merged
    fix_pr: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_failed_messages_status_created_at", "status", "created_at"),
        Index("ix_failed_messages_reminder_id", "reminder_id"),
        Index("ix_failed_messages_event_id", "event_id"),
    )
