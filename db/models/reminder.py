import uuid

from datetime        import datetime, timezone
from typing          import Optional

from sqlalchemy      import BigInteger, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm  import Mapped, mapped_column

from enums           import ReminderStatus
from db.models.types import UTCDateTime
from db.models.user  import Base


# SQLite only auto-increments INTEGER primary keys.
BigIntId = BigInteger().with_variant(Integer, "sqlite")


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
    # Stored as its value ("pending") in a plain VARCHAR(16), as before the enum.
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus, native_enum=False, create_constraint=False, length=16,
             values_callable=lambda statuses: [s.value for s in statuses]),
        nullable=False, default=ReminderStatus.PENDING,
    )
    fire_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    # Repeats on these days, e.g. "mon,fri@09:00" (reminders/recurrence.py); None = once.
    recurrence: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)

    __table_args__ = (
        Index("ix_reminders_status_next_fire_at", "status", "next_fire_at"),
        Index("ix_reminders_target_user_id", "target_user_id"),
    )
