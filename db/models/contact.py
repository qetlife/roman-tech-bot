import uuid

from datetime           import datetime
from typing             import Optional

from sqlalchemy         import Enum, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm     import Mapped, mapped_column

from enums              import ContactStatus
from db.models.reminder import BigIntId, utcnow
from db.models.types    import UTCDateTime
from db.models.user     import Base


class Contact(Base):
    """`owner` may send reminders to `contact`, who agreed to it.

    One row per direction: if the contact wants to remind the owner too,
    that's another row. Removing a contact deletes the row.
    """

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    contact_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # What the owner calls them ("anna", "mom"): unique per owner, compared case-insensitively
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ContactStatus] = mapped_column(
        Enum(ContactStatus, native_enum=False, create_constraint=False, length=16,
             values_callable=lambda members: [m.value for m in members]),
        nullable=False, default=ContactStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # Accepted, or declined (status), at
    accepted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "contact_user_id", name="uq_contacts_owner_contact"),
        Index("ix_contacts_contact_user_id", "contact_user_id"),
    )


class ContactRequest(Base):
    """A request sent by @username, kept for a day or more to limit them.

    Separate from `contacts`, whose pending rows can be cancelled (deleted):
    this log only grows, so cancelling and asking again still counts.
    """

    __tablename__ = "contact_requests"

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    contact_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (Index("ix_contact_requests_owner_created_at", "owner_user_id", "created_at"),)


class Invite(Base):
    """A single-use link (t.me/<bot>?start=inv_<token>) that makes whoever opens it a contact of `owner`."""

    __tablename__ = "invites"

    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    used_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
