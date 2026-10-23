import uuid

from dataclasses        import dataclass
from datetime           import datetime
from typing             import Optional

from sqlalchemy         import select, update

from db.session         import SessionLocal
from db.models.event    import Event
from db.models.reminder import Reminder
from enums              import ACTIVE_STATUSES, EventStatus, MessageSource, ReminderStatus


@dataclass
class Cancelled:
    event: Event
    reminders: list     # its reminders that were waiting, as they were (so a firing one's message can be retired)


class EventRepository:
    def create(
        self, user_id: uuid.UUID, title: str, starts_at: datetime, timezone: str, recurrence: Optional[str] = None,
        all_day: bool = False, request: Optional[str] = None, source: Optional[MessageSource] = None, **synced,
    ) -> Event:
        """`synced`: other columns, e.g. the Google ids of an imported event."""
        with SessionLocal(expire_on_commit=False) as session:
            event = Event(
                user_id=user_id, title=title, starts_at=starts_at, timezone=timezone, recurrence=recurrence,
                all_day=all_day, request=request, source=source, **synced,
            )
            session.add(event)
            session.commit()
            return event

    def get(self, event_id: int) -> Optional[Event]:
        with SessionLocal(expire_on_commit=False) as session:
            return session.get(Event, event_id)

    def get_many(self, event_ids) -> dict:
        """id → event."""
        if not event_ids:
            return {}
        with SessionLocal(expire_on_commit=False) as session:
            return {e.id: e for e in session.scalars(select(Event).where(Event.id.in_(event_ids)))}

    def list_active(self, user_id: uuid.UUID) -> list:
        """The user's events that aren't cancelled, past one-offs included (see core/events.next_occurrence)."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Event)
                .where(Event.user_id == user_id, Event.status == EventStatus.ACTIVE)
                .order_by(Event.starts_at, Event.id)
            )
            return list(session.scalars(stmt))

    def find_external(self, user_id: uuid.UUID, calendar_id: str, external_id: str) -> Optional[Event]:
        """The event synced with this Google event, cancelled or not."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (
                select(Event)
                .where(Event.user_id == user_id, Event.external_calendar_id == calendar_id,
                       Event.external_id == external_id)
                .order_by(Event.id.desc())
            )
            return session.scalars(stmt).first()

    def list_synced(self, user_id: uuid.UUID, calendar_id: str) -> list:
        """The active events synced with one of the user's Google calendars."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = select(Event).where(Event.user_id == user_id, Event.external_calendar_id == calendar_id,
                                       Event.status == EventStatus.ACTIVE)
            return list(session.scalars(stmt))

    def list_unsynced(self, user_id: uuid.UUID) -> list:
        """The active events only in the bot (not in Google)."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = select(Event).where(Event.user_id == user_id, Event.external_id.is_(None),
                                       Event.status == EventStatus.ACTIVE)
            return list(session.scalars(stmt))

    def list_pending(self, user_id: uuid.UUID) -> list:
        """Events changed (or cancelled) in the bot that Google doesn't know about yet."""
        with SessionLocal(expire_on_commit=False) as session:
            return list(session.scalars(select(Event).where(Event.user_id == user_id, Event.pending_push.is_(True))))

    def set_sync(self, event_id: int, **values) -> Optional[Event]:
        """Sync bookkeeping (Google ids, etag, pending_push), also on a cancelled event; doesn't count as a change."""
        with SessionLocal(expire_on_commit=False) as session:
            event = session.get(Event, event_id, with_for_update=True)
            if event is None:
                return None
            # Not a change by the user: keep updated_at (last change wins)
            values.setdefault("updated_at", event.updated_at)
            for key, value in values.items():
                setattr(event, key, value)
            session.commit()
            return event

    def detach(self, user_id: uuid.UUID, calendar_id: str) -> int:
        """Stop syncing a calendar's events but keep them in the bot. Returns how many."""
        with SessionLocal(expire_on_commit=False) as session:
            result = session.execute(
                update(Event).where(Event.user_id == user_id, Event.external_calendar_id == calendar_id)
                .values(external_source=None, external_calendar_id=None, external_id=None, etag=None,
                        external_updated_at=None, pending_push=False)
                .execution_options(synchronize_session=False)
            )
            session.commit()
            return result.rowcount

    def update(self, event_id: int, **values) -> Optional[Event]:
        """Change an active event; None if it's cancelled or gone."""
        with SessionLocal(expire_on_commit=False) as session:
            event = session.get(Event, event_id, with_for_update=True)
            if event is None or event.status != EventStatus.ACTIVE:
                return None
            for key, value in values.items():
                setattr(event, key, value)
            session.commit()
            return event

    def cancel(self, event_id: int) -> Optional[Cancelled]:
        """Cancel the event and its waiting reminders; None if it was already cancelled."""
        with SessionLocal(expire_on_commit=False) as session:
            event = session.get(Event, event_id, with_for_update=True)
            if event is None or event.status != EventStatus.ACTIVE:
                return None
            event.status = EventStatus.CANCELLED
            cancelled = list(session.scalars(
                select(Reminder)
                .where(Reminder.event_id == event_id, Reminder.status.in_(ACTIVE_STATUSES))
                .with_for_update()
            ))
            if cancelled:
                # Not synchronized: the returned reminders keep their old status.
                session.execute(
                    update(Reminder).where(Reminder.id.in_([r.id for r in cancelled]))
                    .values(status=ReminderStatus.CANCELLED)
                    .execution_options(synchronize_session=False)
                )
            session.commit()
            return Cancelled(event, cancelled)
