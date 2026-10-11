import uuid

from datetime       import datetime
from typing         import Optional

from sqlalchemy     import select

from db.db          import SessionLocal
from models.reminder import Reminder, ReminderStatus, utcnow
from models.user    import User


class ReminderRepository:
    def create(
        self, user: User, chat_id: int, text: str, remind_at: datetime, recurrence: Optional[str] = None,
    ) -> Reminder:
        with SessionLocal(expire_on_commit=False) as session:
            reminder = Reminder(
                creator_user_id=user.id,
                target_user_id=user.id,
                chat_id=chat_id,
                text=text,
                remind_at=remind_at,
                next_fire_at=remind_at,
                recurrence=recurrence,
            )
            session.add(reminder)
            session.commit()
            return reminder

    def get_for_user(self, reminder_id: int, telegram_id: int) -> Optional[Reminder]:
        """The reminder, if `telegram_id` is the user it is meant for."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .join(User, User.id == Reminder.target_user_id)
                .where(Reminder.id == reminder_id, User.telegram_id == telegram_id)
            )
            return session.scalar(stmt)

    def list_active(self, user_id: uuid.UUID) -> list:
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .where(Reminder.target_user_id == user_id, Reminder.status.in_(ReminderStatus.ACTIVE))
                .order_by(Reminder.remind_at)
            )
            return list(session.scalars(stmt))

    def get_due(self, now: datetime) -> list:
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .where(Reminder.status.in_(ReminderStatus.ACTIVE), Reminder.next_fire_at <= now)
                .order_by(Reminder.next_fire_at)
            )
            return list(session.scalars(stmt))

    def _update(self, reminder_id: int, only_active: bool = True, **values) -> Optional[Reminder]:
        with SessionLocal(expire_on_commit=False) as session:
            reminder = session.get(Reminder, reminder_id, with_for_update=True)
            if reminder is None or (only_active and reminder.status not in ReminderStatus.ACTIVE):
                return None
            for key, value in values.items():
                setattr(reminder, key, value)
            session.commit()
            return reminder

    def mark_fired(self, reminder_id: int, message_id: int, next_fire_at: datetime) -> Optional[Reminder]:
        with SessionLocal(expire_on_commit=False) as session:
            reminder = session.get(Reminder, reminder_id, with_for_update=True)
            if reminder is None or reminder.status not in ReminderStatus.ACTIVE:
                return None
            reminder.status = ReminderStatus.FIRING
            reminder.fire_count += 1
            reminder.last_message_id = message_id
            reminder.next_fire_at = next_fire_at
            session.commit()
            return reminder

    def acknowledge(self, reminder_id: int) -> Optional[Reminder]:
        return self._update(reminder_id, status=ReminderStatus.DONE, acknowledged_at=utcnow())

    def advance(self, reminder_id: int, remind_at: datetime, next_fire_at: datetime = None) -> Optional[Reminder]:
        """Move a recurring reminder on to its next occurrence."""
        return self._update(
            reminder_id, status=ReminderStatus.PENDING, remind_at=remind_at,
            next_fire_at=next_fire_at or remind_at, fire_count=0, last_message_id=None,
        )

    def snooze(self, reminder_id: int, until: datetime) -> Optional[Reminder]:
        return self._update(
            reminder_id, status=ReminderStatus.PENDING, remind_at=until, next_fire_at=until, fire_count=0,
        )

    def reschedule(
        self, reminder_id: int, text: str, remind_at: datetime, recurrence: Optional[str] = None,
    ) -> Optional[Reminder]:
        return self._update(
            reminder_id, status=ReminderStatus.PENDING, text=text, recurrence=recurrence,
            remind_at=remind_at, next_fire_at=remind_at, fire_count=0, last_message_id=None,
        )

    def cancel(self, reminder_id: int) -> Optional[Reminder]:
        return self._update(reminder_id, status=ReminderStatus.CANCELLED)

    def mark_missed(self, reminder_id: int) -> Optional[Reminder]:
        return self._update(reminder_id, status=ReminderStatus.MISSED)

    def mark_failed(self, reminder_id: int) -> Optional[Reminder]:
        return self._update(reminder_id, status=ReminderStatus.FAILED)
