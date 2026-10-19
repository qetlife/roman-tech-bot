import secrets
import uuid

from dataclasses        import dataclass
from datetime           import timedelta
from typing             import Optional

from sqlalchemy         import func, select, update

from core.contacts      import default_name, unique_name
from db.session         import SessionLocal
from db.models.contact  import Contact, ContactRequest, Invite
from db.models.reminder import Reminder, utcnow
from db.models.user     import User
from enums              import ACTIVE_STATUSES, ContactStatus, InviteResult, ReminderStatus, RequestResult

INVITE_LIFETIME = timedelta(days=7)
# After ❌ No to a request by @username, the same person can't be asked again for this long.
REQUEST_COOLDOWN = timedelta(days=30)
# Requests by @username one person can send a day.
REQUESTS_PER_DAY = 5


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
            name = default_name(user.first_name, user.username)
            if contact is None:
                contact = Contact(owner_user_id=owner.id, contact_user_id=user.id, name=self._free_name(session, owner.id, name))
                session.add(contact)
            elif contact.status == ContactStatus.DECLINED:
                # An old "no": its name may have been given to someone else since.
                contact.name = self._free_name(session, owner.id, name)
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

    def request(self, owner_id: uuid.UUID, contact_user: User) -> tuple:
        """Ask `contact_user`: (RequestResult, the pending contact row if one was made)."""
        with SessionLocal(expire_on_commit=False) as session:
            existing = session.scalar(select(Contact).where(
                Contact.owner_user_id == owner_id, Contact.contact_user_id == contact_user.id,
            ))
            if existing is not None and existing.status != ContactStatus.DECLINED:
                return RequestResult.EXISTS, None
            if existing is not None and existing.accepted_at > utcnow() - REQUEST_COOLDOWN:
                return RequestResult.DECLINED, None
            # Counted from the request log, which cancelling a request doesn't shrink.
            day_ago = utcnow() - timedelta(days=1)
            sent = session.scalars(select(ContactRequest.contact_user_id).where(
                ContactRequest.owner_user_id == owner_id, ContactRequest.created_at > day_ago,
            )).all()
            if contact_user.id in sent:
                return RequestResult.RECENT, None
            if len(sent) >= REQUESTS_PER_DAY:
                return RequestResult.TOO_MANY, None
            session.add(ContactRequest(owner_user_id=owner_id, contact_user_id=contact_user.id))
            if existing is not None:
                session.delete(existing)
                session.flush()
            contact = Contact(owner_user_id=owner_id, contact_user_id=contact_user.id,
                              name=self._free_name(session, owner_id,
                                                   default_name(contact_user.first_name, contact_user.username)))
            session.add(contact)
            session.commit()
            return RequestResult.ASKED, contact

    def answer(self, contact_id: int, contact_user_id: uuid.UUID, allow: bool) -> Optional[Contact]:
        """The asked person allows (accepted) or declines a pending request.

        A declined row is kept, as a note not to ask again for REQUEST_COOLDOWN;
        it isn't a contact (people_of / senders_of skip it).
        """
        with SessionLocal(expire_on_commit=False) as session:
            contact = session.get(Contact, contact_id, with_for_update=True)
            if contact is None or contact.contact_user_id != contact_user_id \
                    or contact.status != ContactStatus.PENDING:
                return None
            contact.status = ContactStatus.ACCEPTED if allow else ContactStatus.DECLINED
            contact.accepted_at = utcnow()
            session.commit()
            return contact

    # --- lists and changes -----------------------------------------------------

    def get(self, contact_id: int) -> Optional[Contact]:
        with SessionLocal(expire_on_commit=False) as session:
            return session.get(Contact, contact_id)

    def find(self, owner_id: uuid.UUID, contact_user_id: uuid.UUID) -> Optional[Contact]:
        """The owner's contact row for this user (any status), or None."""
        with SessionLocal(expire_on_commit=False) as session:
            return session.scalar(select(Contact).where(
                Contact.owner_user_id == owner_id, Contact.contact_user_id == contact_user_id,
            ))

    def people_of(self, owner_id: uuid.UUID) -> list:
        """[(contact, their user)] the owner can (or asked to) remind, by name."""
        with SessionLocal(expire_on_commit=False) as session:
            stmt = (select(Contact, User).join(User, User.id == Contact.contact_user_id)
                    .where(Contact.owner_user_id == owner_id, Contact.status != ContactStatus.DECLINED)
                    .order_by(func.lower(Contact.name)))
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
                Contact.status != ContactStatus.DECLINED,
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
            if contact is None or user_id not in (contact.owner_user_id, contact.contact_user_id) \
                    or contact.status == ContactStatus.DECLINED:
                # A declined row is a note not to ask again, not a contact.
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

    @staticmethod
    def _free_name(session, owner_id: uuid.UUID, name: str) -> str:
        taken = session.scalars(select(Contact.name).where(
            Contact.owner_user_id == owner_id, Contact.status != ContactStatus.DECLINED,
        ))
        return unique_name(name, list(taken))
