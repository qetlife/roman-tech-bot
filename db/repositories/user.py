import uuid

from typing         import Optional
from sqlalchemy     import select
from sqlalchemy.exc import IntegrityError

from db.session     import SessionLocal
from db.models.user import User


class UserRepository:
    def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        with SessionLocal() as session:
            return session.get(User, user_id)

    def get_timezones(self, user_ids) -> dict:
        """{user_id: timezone or None} for many users at once."""
        with SessionLocal() as session:
            rows = session.execute(select(User.id, User.timezone).where(User.id.in_(set(user_ids))))
            return dict(rows.all())

    def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        with SessionLocal() as session:
            stmt = select(User).where(User.telegram_id == telegram_id)
            return session.scalar(stmt)

    def create(self, telegram_id: int) -> User:
        with SessionLocal() as session:
            user = User(telegram_id=telegram_id)
            session.add(user)
            try:
                session.commit()
            except IntegrityError as e:
                session.rollback()
                raise ValueError(f"User with telegram_id={telegram_id} already exists") from e

            session.refresh(user)
            return user

    def get_or_create(self, telegram_id: int) -> User:
        with SessionLocal() as session:
            existing = session.scalar(select(User).where(User.telegram_id == telegram_id))
            if existing:
                return existing

            user = User(telegram_id=telegram_id)
            session.add(user)
            try:
                session.commit()
                session.refresh(user)
                return user
            except IntegrityError:
                session.rollback()
                return session.scalar(select(User).where(User.telegram_id == telegram_id))

    def get_by_username(self, username: str) -> Optional[User]:
        with SessionLocal() as session:
            return session.scalar(select(User).where(User.username == username.lstrip("@").lower()))

    def remember_profile(self, telegram_id: int, first_name: Optional[str], username: Optional[str]) -> None:
        """Store the user's Telegram first name and @username, if they changed (only for known users)."""
        first_name = (first_name or "")[:64] or None
        username = (username or "").lower()[:64] or None
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None or (user.first_name, user.username) == (first_name, username):
                return
            user.first_name, user.username = first_name, username
            session.commit()

    def set_timezone(self, telegram_id: int, timezone: str) -> Optional[User]:
        with SessionLocal(expire_on_commit=False) as session:
            user = session.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                return None
            user.timezone = timezone
            session.commit()
            return user
