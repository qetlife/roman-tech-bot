import secrets
import uuid

from dataclasses        import dataclass
from datetime           import timedelta
from typing             import Optional

from sqlalchemy         import delete, func, or_, select, update

from core.contacts      import default_name, unique_name
from db.session         import SessionLocal
from db.models.contact  import Contact, Invite
from db.models.reminder import Reminder, utcnow
from db.models.user     import User
from enums              import ACTIVE_STATUSES, ContactStatus, InviteResult, ReminderStatus

INVITE_LIFETIME = timedelta(days=7)


@dataclass
class Accepted:
    """What using an invite did: `result`, and the contact row if one was made (or existed)."""
    result: InviteResult
    contact: Optional[Contact] = None
    owner: Optional[User] = None


class ContactRepository:
    # --- invites ------------------------------------------------------------

    def create_invite(self, owner_id: uuid.UUID) -> Invite:
        with SessionLocal(expire_on_commit=False) as session:
            invite = Invite(token=secrets.token_urlsafe(12), owner_user_id=owner_id,
                            expires_at=utcnow() + INVITE_LIFETIME)
            session.add(invite)
            session.commit()
            return invite

    def get_invite(self, token: str) -> Optional[Invite]:
        with SessionLocal(expire_on_commit=False) as session:
            return session.get(Invite, token)

    def use_invite(self, token: str, user: User) -> Accepted:
        """`user` accepts the invite: they become an accepted contact of its owner (once)."""
        with SessionLocal(expire_on_commit=False) as session:
            invite = session.get(Invite, token, with_for_update=True)
            if invite is None or invite.used_at is not None:
                return Accepted(InviteResult.USED if invite else InviteResult.UNKNOWN)
            if invite.expires_at <= utcnow():
                return Accepted(InviteResult.EXPIRED)
            if invite.owner_user_id == user.id:
                return Accepted(InviteResult.OWN)
            owner = session.get(User, invite.owner_user_id)

            invite.used_at, invite.used_by_user_id = utcnow(), user.id
            contact = session.scalar(select(Contact).where(
                Contact.owner_user_id == owner.id, Contact.contact_user_id == user.id,
            ))
            if contact is not None and contact.status == ContactStatus.ACCEPTED:
                session.commit()
                return Accepted(InviteResult.ALREADY, contact, owner)
            if contact is None:
                contact = Contact(owner_user_id=owner.id, contact_user_id=user.id,
                                  name=self._free_name(session, owner.id, default_name(user.first_name, user.username)))
                session.add(contact)
            contact.status, contact.accepted_at = ContactStatus.ACCEPTED, utcnow()
            session.commit()
            return Accepted(InviteResult.ACCEPTED, contact, owner)

    def decline_invite(self, token: str, user: User) -> Optional[User]:
        """`user` says no: the invite can't be used any more. Its owner, or None if it was already used."""
        with SessionLocal(expire_on_commit=False) as session:
            invite = session.get(Invite, token, with_for_update=True)
            if invite is None or invite.used_at is not None or invite.owner_user_id == user.id:
                return None
            invite.used_at, invite.used_by_user_id = utcnow(), user.id
            owner = session.get(User, invite.owner_user_id)
            session.commit()
            return owner

    # --- requests by @username --------------------------------------------------

    def request(self, owner_id: uuid.UUID, contact_user: User) -> Optional[Contact]:
        """A pending contact row for `contact_user`, to be answered by them; None if one exists."""
        with SessionLocal(expire_on_commit=False) as session:
            existing = session.scalar(select(Contact).where(
                Contact.owner_user_id == owner_id, Contact.contact_user_id == contact_user.id,
            ))
            if existing is not None:
                return None
            contact = Contact(owner_user_id=owner_id, contact_user_id=contact_user.id,
                              name=self._free_name(session, owner_id,
                                                   default_name(contact_user.first_name, contact_user.username)))
            session.add(contact)
            session.commit()
            return contact

    def answer(self, contact_id: int, contact_user_id: uuid.UUID, allow: bool) -> Optional[Contact]:
        """The asked person allows (accepted) or declines (row deleted) a pending request."""
        with SessionLocal(expire_on_commit=False) as session:
            contact = session.get(Contact, contact_id, with_for_update=True)
            if contact is None or contact.contact_user_id != contact_user_id \
                    or contact.status != ContactStatus.PENDING:
                return None
            if allow:
                contact.status, contact.accepted_at = ContactStatus.ACCEPTED, utcnow()
            else:
                session.delete(contact)
            session.commit()
            return contact

    # --- lists and changes -----------------------------------------------------

    def get(self, contact_id: int) -> Optional[Contact]:
        with SessionLocal(expire_on_commit=False) as session:
            return session.get(Contact, contact_id)

    def people_of(self, owner_id: uuid.UUID) -> list:
        """[(contact, their user)] the owner can (or asked to) remind, by name."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (select(Contact, User).join(User, User.id == Contact.contact_user_id)
                    .where(Contact.owner_user_id == owner_id).order_by(func.lower(Contact.name)))
            return [tuple(row) for row in session.execute(stmt)]

    def senders_of(self, contact_user_id: uuid.UUID) -> list:
        """[(contact, owner's user)] who can remind this user (accepted only)."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (select(Contact, User).join(User, User.id == Contact.owner_user_id)
                    .where(Contact.contact_user_id == contact_user_id, Contact.status == ContactStatus.ACCEPTED)
                    .order_by(Contact.accepted_at))
            return [tuple(row) for row in session.execute(stmt)]

    def rename(self, contact_id: int, owner_id: uuid.UUID, name: str) -> Optional[Contact]:
        """Give a contact a new name; None if it isn't the owner's or another contact has it."""
        with SessionLocal(expire_on_commit=False) as session:
            contact = session.get(Contact, contact_id, with_for_update=True)
            if contact is None or contact.owner_user_id != owner_id:
                return None
            clash = session.scalar(select(Contact.id).where(
                Contact.owner_user_id == owner_id, func.lower(Contact.name) == name.lower(), Contact.id != contact_id,
            ))
            if clash is not None:
                return None
            contact.name = name
            session.commit()
            return contact

    def remove(self, contact_id: int, user_id: uuid.UUID) -> Optional[Contact]:
        """Either side ends it: the row is deleted, and the owner's waiting reminders for them cancelled."""
        with SessionLocal(expire_on_commit=False) as session:
            contact = session.get(Contact, contact_id, with_for_update=True)
            if contact is None or user_id not in (contact.owner_user_id, contact.contact_user_id):
                return None
            session.execute(
                update(Reminder)
                .where(Reminder.creator_user_id == contact.owner_user_id,
                       Reminder.target_user_id == contact.contact_user_id,
                       Reminder.status.in_(ACTIVE_STATUSES))
                .values(status=ReminderStatus.CANCELLED)
            )
            session.delete(contact)
            session.commit()
            return contact

    def remove_all_for(self, user_id: uuid.UUID) -> int:
        """Delete every contact row with this user on either side (e.g. they blocked the bot)."""
        with SessionLocal() as session:
            result = session.execute(delete(Contact).where(
                or_(Contact.owner_user_id == user_id, Contact.contact_user_id == user_id)
            ))
            session.commit()
            return result.rowcount

    @staticmethod
    def _free_name(session, owner_id: uuid.UUID, name: str) -> str:
        taken = session.scalars(select(Contact.name).where(Contact.owner_user_id == owner_id))
        return unique_name(name, list(taken))
