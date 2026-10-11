import uuid

from typing         import Optional

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy     import BigInteger, String, Uuid

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    # IANA timezone name, e.g. "Europe/Kyiv"; asked for on the first reminder
    timezone: Mapped[Optional[str]] = mapped_column(String(64))
