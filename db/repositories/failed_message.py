import uuid

from typing                     import Optional

from sqlalchemy                 import func, select

from db.session                 import SessionLocal
from db.models.failed_message   import FailedMessage
from db.models.reminder         import utcnow
from enums                      import FailureReason, FailureStatus, MessageSource


class FailedMessageRepository:
    def create(
        self, user_id: uuid.UUID, text: str, source: MessageSource, reason: FailureReason,
        intent: Optional[str] = None, bot_understood: Optional[dict] = None, reminder_id: Optional[int] = None,
    ) -> FailedMessage:
        with SessionLocal(expire_on_commit=False) as session:
            failed = FailedMessage(
                user_id=user_id, text=text, source=source, reason=reason, intent=intent,
                bot_understood=bot_understood, reminder_id=reminder_id,
            )
            session.add(failed)
            session.commit()
            return failed

    def open_for_reminder(self, reminder_id: int) -> Optional[FailedMessage]:
        """The open entry already saved for this reminder, if any."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = select(FailedMessage).where(
                FailedMessage.reminder_id == reminder_id, FailedMessage.status == FailureStatus.OPEN,
            )
            return session.scalars(stmt).first()

    def list_open(self, limit: int) -> list:
        """The newest open entries."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(FailedMessage)
                .where(FailedMessage.status == FailureStatus.OPEN)
                .order_by(FailedMessage.created_at.desc(), FailedMessage.id.desc())
                .limit(limit)
            )
            return list(session.scalars(stmt))

    def count_open(self) -> int:
        with SessionLocal() as session:
            stmt = select(func.count()).select_from(FailedMessage).where(FailedMessage.status == FailureStatus.OPEN)
            return session.scalar(stmt)

    def mark_fixed(self, failed_id: int) -> Optional[FailedMessage]:
        with SessionLocal(expire_on_commit=False) as session:
            failed = session.get(FailedMessage, failed_id, with_for_update=True)
            if failed is None or failed.status != FailureStatus.OPEN:
                return None
            failed.status = FailureStatus.FIXED
            failed.fixed_at = utcnow()
            session.commit()
            return failed
