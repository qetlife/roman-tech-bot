import uuid

from datetime       import datetime

from sqlalchemy     import JSON, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from models.reminder import utcnow
from models.types   import UTCDateTime
from models.user    import Base


class UserSetting(Base):
    """A user's value for one setting; only stored when it differs from the
    default defined in settings/registry.py."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
