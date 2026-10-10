import uuid

from datetime       import datetime, timezone
from typing         import Optional

from sqlalchemy     import BigInteger, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from models.types   import UTCDateTime
from models.user    import Base


# SQLite only auto-increments INTEGER primary keys.
BigIntId = BigInteger().with_variant(Integer, "sqlite")


class ReminderStatus:
    PENDING = "pending"     # waiting for remind_at
    FIRING = "firing"       # sent, re-sent every few minutes until acknowledged
    DONE = "done"           # user pressed OK
    CANCELLED = "cancelled"
    MISSED = "missed"       # no OK within the give-up window
    FAILED = "failed"       # could not be delivered (e.g. the user blocked the bot)

    ACTIVE = (PENDING, FIRING)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True)
    creator_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    # Same as the creator for now; kept separate for reminders for other users.
    target_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # When the reminder is due (moves forward on snooze).
    remind_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    # When the delivery loop should send it next.
    next_fire_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ReminderStatus.PENDING)
    fire_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)

    __table_args__ = (
        Index("ix_reminders_status_next_fire_at", "status", "next_fire_at"),
        Index("ix_reminders_target_user_id", "target_user_id"),
    )
