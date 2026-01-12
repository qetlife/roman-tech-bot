import uuid

from typing         import Optional
from sqlalchemy     import select
from sqlalchemy.exc import IntegrityError

from db.db          import SessionLocal
from models.user    import User


class UserRepository:
    def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        with SessionLocal() as session:
            return session.get(User, user_id)

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
