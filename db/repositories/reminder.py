import uuid

from datetime           import datetime
from typing             import Optional

from sqlalchemy         import select

from db.session         import SessionLocal
from enums              import ACTIVE_STATUSES, MessageSource, ReminderStatus
from db.models.reminder import Reminder, utcnow
from db.models.user     import User


class ReminderRepository:
    def create(
        self, user: User, chat_id: int, text: str, remind_at: datetime, recurrence: Optional[str] = None,
        request: Optional[str] = None, source: Optional[MessageSource] = None, target: Optional[User] = None,
        event_id: Optional[int] = None, event_offset: Optional[int] = None,
    ) -> Reminder:
        """A reminder by `user`, for `target` (a contact, delivered to `chat_id`) or themselves.

        With `event_id`, it is `event_offset` minutes from that event's start, and follows it.
        """
        with SessionLocal(expire_on_commit=False) as session:
            reminder = Reminder(
                creator_user_id=user.id,
                target_user_id=(target or user).id,
                chat_id=chat_id,
                text=text,
                remind_at=remind_at,
                next_fire_at=remind_at,
                recurrence=recurrence,
                request=request,
                source=source,
                event_id=event_id,
                event_offset=event_offset,
            )
            session.add(reminder)
            session.commit()
            return reminder

    def get(self, reminder_id: int) -> Optional[Reminder]:
        with SessionLocal(expire_on_commit=False) as session:
            return session.get(Reminder, reminder_id)

    def get_created(self, reminder_id: int, telegram_id: int) -> Optional[Reminder]:
        """The reminder, if `telegram_id` made it (for themselves or for someone else)."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .join(User, User.id == Reminder.creator_user_id)
                .where(Reminder.id == reminder_id, User.telegram_id == telegram_id)
            )
            return session.scalar(stmt)

    def get_by_message(self, message_id: int, chat_id: int, telegram_id: int) -> Optional[Reminder]:
        """The reminder going off as this message (firing, waiting for OK), if it is meant for `telegram_id`.

        Not once it was snoozed or answered: then the message is an old one.
        """
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .join(User, User.id == Reminder.target_user_id)
                .where(Reminder.last_message_id == message_id, Reminder.chat_id == chat_id,
                       User.telegram_id == telegram_id, Reminder.status == ReminderStatus.FIRING)
            )
            return session.scalar(stmt)

    def latest_created(self, telegram_id: int) -> Optional[Reminder]:
        """The reminder `telegram_id` made most recently."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .join(User, User.id == Reminder.creator_user_id)
                .where(User.telegram_id == telegram_id)
                .order_by(Reminder.id.desc())
                .limit(1)
            )
            return session.scalar(stmt)

    def list_active(self, user_id: uuid.UUID) -> list:
        """The reminders waiting for this user: their own, and those others sent them."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .where(Reminder.target_user_id == user_id, Reminder.status.in_(ACTIVE_STATUSES))
                .order_by(Reminder.remind_at)
            )
            return list(session.scalars(stmt))

    def list_created(self, user_id: uuid.UUID) -> list:
        """The active reminders this user made: for themselves and for others."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .where(Reminder.creator_user_id == user_id, Reminder.status.in_(ACTIVE_STATUSES))
                .order_by(Reminder.remind_at)
            )
            return list(session.scalars(stmt))

    def list_sent(self, user_id: uuid.UUID) -> list:
        """The active reminders this user made for others."""
        return [r for r in self.list_created(user_id) if r.target_user_id != user_id]

    def list_for_event(self, event_id: int) -> list:
        """The active reminders that follow this event."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .where(Reminder.event_id == event_id, Reminder.status.in_(ACTIVE_STATUSES))
                .order_by(Reminder.remind_at)
            )
            return list(session.scalars(stmt))

    def get_due(self, now: datetime) -> list:
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Reminder)
                .where(Reminder.status.in_(ACTIVE_STATUSES), Reminder.next_fire_at <= now)
                .order_by(Reminder.next_fire_at)
            )
            return list(session.scalars(stmt))

    def _update(self, reminder_id: int, only_active: bool = True, **values) -> Optional[Reminder]:
        with SessionLocal(expire_on_commit=False) as session:
            reminder = session.get(Reminder, reminder_id, with_for_update=True)
            if reminder is None or (only_active and reminder.status not in ACTIVE_STATUSES):
                return None
            for key, value in values.items():
                setattr(reminder, key, value)
            session.commit()
            return reminder

    def mark_fired(self, reminder_id: int, message_id: int, next_fire_at: datetime) -> Optional[Reminder]:
        with SessionLocal(expire_on_commit=False) as session:
            reminder = session.get(Reminder, reminder_id, with_for_update=True)
            if reminder is None or reminder.status not in ACTIVE_STATUSES:
                return None
            reminder.status = ReminderStatus.FIRING
            reminder.fire_count += 1
            reminder.last_message_id = message_id
            reminder.next_fire_at = next_fire_at
            session.commit()
            return reminder

    def postpone(self, reminder_id: int, next_fire_at: datetime) -> Optional[Reminder]:
        """Send the next repeat later, keeping the reminder as it is."""
        return self._update(reminder_id, next_fire_at=next_fire_at)

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
        request: Optional[str] = None, source: Optional[MessageSource] = None,
    ) -> Optional[Reminder]:
        """New time and text (✏️ Edit, "move it to 10"): it no longer follows an event."""
        return self._update(
            reminder_id, status=ReminderStatus.PENDING, text=text, recurrence=recurrence,
            remind_at=remind_at, next_fire_at=remind_at, fire_count=0, last_message_id=None,
            request=request, source=source, event_id=None, event_offset=None,
        )

    def follow_event(self, reminder_id: int, remind_at: datetime, recurrence: Optional[str]) -> Optional[Reminder]:
        """The event it follows moved (or skips a day): a new time, waiting again."""
        return self._update(
            reminder_id, status=ReminderStatus.PENDING, recurrence=recurrence,
            remind_at=remind_at, next_fire_at=remind_at, fire_count=0, last_message_id=None,
        )

    def relink(self, reminder_id: int, recurrence: Optional[str]) -> Optional[Reminder]:
        """Only the repeat changes (its event skips a day): the same time, as it is."""
        return self._update(reminder_id, recurrence=recurrence)

    def cancel(self, reminder_id: int) -> Optional[Reminder]:
        return self._update(reminder_id, status=ReminderStatus.CANCELLED)

    def restore(self, reminder_id: int, remind_at: datetime, now: datetime) -> Optional[Reminder]:
        """↩️ Undo after "cancel it": waiting again for `remind_at` (going off now if that has passed).

        None unless it is cancelled.
        """
        with SessionLocal(expire_on_commit=False) as session:
            reminder = session.get(Reminder, reminder_id, with_for_update=True)
            if reminder is None or reminder.status != ReminderStatus.CANCELLED:
                return None
            reminder.status = ReminderStatus.PENDING
            reminder.remind_at = remind_at
            reminder.next_fire_at = max(remind_at, now)
            reminder.fire_count = 0
            reminder.last_message_id = None
            session.commit()
            return reminder

    def mark_missed(self, reminder_id: int) -> Optional[Reminder]:
        return self._update(reminder_id, status=ReminderStatus.MISSED)

    def mark_failed(self, reminder_id: int) -> Optional[Reminder]:
        return self._update(reminder_id, status=ReminderStatus.FAILED)
