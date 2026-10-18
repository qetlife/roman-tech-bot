"""👥 People: who you can send reminders to, and who can send them to you.

Telegram bots can only message people who started them, so the other person
always opts in: they open an invite link (t.me/<bot>?start=inv_<token>) and
tap ✅ Allow, or, if they already use the bot, answer a request sent to their
@username. Either side can end it at any time; that deletes the contact row.
"""

import logging

from    telegram                        import InlineKeyboardButton, InlineKeyboardMarkup, Update
from    telegram.error                  import TelegramError
from    telegram.ext                    import ContextTypes

from    core.contacts                   import clean_name
from    db.repositories.contact         import INVITE_LIFETIME, REQUESTS_PER_DAY, ContactRepository
from    db.repositories.user            import UserRepository
from    enums                           import (
    Awaiting, Callback, CallbackPrefix, ContactStatus, InviteResult, PeopleAction, RequestResult,
)
from    handlers.ui                     import AWAITING, RENAME_CONTACT_ID, render_menu


logger = logging.getLogger(__name__)

contacts = ContactRepository()
users = UserRepository()

INVITE_PREFIX = "inv_"      # /start payload of an invite link


def people_callback(action: PeopleAction, contact_id: int) -> str:
    return f"{CallbackPrefix.PEOPLE}{action}:{contact_id}"


def display(user) -> str:
    """How someone is shown to others: "Anna (@anna)", "Anna", "@anna" or "Someone"."""
    if user.first_name and user.username:
        return f"{user.first_name} (@{user.username})"
    return user.first_name or (f"@{user.username}" if user.username else "Someone")


async def tell(context: ContextTypes.DEFAULT_TYPE, user, text: str, reply_markup=None) -> bool:
    """Message another user in their private chat; False if Telegram refuses (e.g. they blocked the bot)."""
    try:
        await context.bot.send_message(chat_id=user.telegram_id, text=text, reply_markup=reply_markup)
        return True
    except TelegramError:
        logger.info("Couldn't message user %s", user.telegram_id)
        return False


# --- the 👥 People screen ----------------------------------------------------

def people_text(people, senders) -> str:
    lines = ["👥 People", ""]
    if people:
        lines.append("You can remind:")
        for contact, user in people:
            waiting = " ⏳ waiting for an answer" if contact.status == ContactStatus.PENDING else ""
            username = f" (@{user.username})" if user.username else ""
            lines.append(f"• {contact.name}{username}{waiting}")
    else:
        lines.append("You can't remind anyone yet: tap ➕ Invite.")
    if senders:
        lines += ["", "Can remind you:"]
        lines += [f"• {display(user)}" for _, user in senders]
    return "\n".join(lines)


def build_people_keyboard(people, senders):
    rows = [[InlineKeyboardButton(f"👤 {c.name}", callback_data=people_callback(PeopleAction.OPEN, c.id))]
            for c, _ in people]
    rows += [[InlineKeyboardButton(f"📨 {display(u)}", callback_data=people_callback(PeopleAction.SENDER, c.id))]
             for c, u in senders]
    rows.append([
        InlineKeyboardButton("➕ Invite", callback_data=Callback.NEW_INVITE),
        InlineKeyboardButton("↩️ Back", callback_data=Callback.MAIN_MENU),
    ])
    return InlineKeyboardMarkup(rows)


async def show_people(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = users.get_or_create(update.effective_user.id)
    people, senders = contacts.people_of(user.id), contacts.senders_of(user.id)
    await render_menu(update, context, people_text(people, senders), build_people_keyboard(people, senders))


async def on_people_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu → 👥 People (also ↩️ Back from a person's screen)."""
    await update.callback_query.answer()
    context.user_data.pop(AWAITING, None)
    await show_people(update, context)


BACK = InlineKeyboardButton("↩️ Back", callback_data=Callback.PEOPLE_MENU)


async def on_people_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A person's screen and its buttons; answers to a request by @username."""
    query = update.callback_query
    action, contact_id = query.data.removeprefix(CallbackPrefix.PEOPLE).split(":")
    action, contact_id = PeopleAction(action), int(contact_id)
    user = users.get_or_create(update.effective_user.id)
    contact = contacts.get(contact_id)

    if action in (PeopleAction.ALLOW, PeopleAction.DECLINE):
        await answer_request(update, context, user, contact_id, action == PeopleAction.ALLOW)
        return

    # Only the two people in it can see or change a contact.
    if contact is None or user.id not in (contact.owner_user_id, contact.contact_user_id):
        await query.answer("That's gone.")
        await show_people(update, context)
        return
    owner = user.id == contact.owner_user_id

    if action == PeopleAction.OPEN and owner:
        await query.answer()
        other = users.get_by_id(contact.contact_user_id)
        if contact.status == ContactStatus.PENDING:
            text, buttons = f"👤 {contact.name}\n\nWaiting for {display(other)} to answer.", [
                InlineKeyboardButton("🗑 Cancel request", callback_data=people_callback(PeopleAction.REMOVE, contact.id))]
        else:
            text, buttons = f"👤 {contact.name}\n{display(other)}\n\nYou can send them reminders.", [
                InlineKeyboardButton("✏️ Rename", callback_data=people_callback(PeopleAction.RENAME, contact.id)),
                InlineKeyboardButton("🗑 Remove", callback_data=people_callback(PeopleAction.REMOVE, contact.id))]
        await render_menu(update, context, text, InlineKeyboardMarkup([buttons, [BACK]]))

    elif action == PeopleAction.SENDER and not owner:
        await query.answer()
        other = users.get_by_id(contact.owner_user_id)
        await render_menu(update, context, f"📨 {display(other)}\n\nCan send you reminders.", InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Stop their reminders", callback_data=people_callback(PeopleAction.STOP, contact.id))],
            [BACK],
        ]))

    elif action == PeopleAction.RENAME and owner:
        await query.answer()
        context.user_data[AWAITING] = Awaiting.CONTACT_NAME
        context.user_data[RENAME_CONTACT_ID] = contact.id
        await query.message.reply_text(f"What should I call {contact.name}? e.g. “mom” or “Anna”.")

    elif action == PeopleAction.REMOVE and owner:
        contacts.remove(contact.id, user.id)
        await query.answer(f"Removed {contact.name}")
        await show_people(update, context)

    elif action == PeopleAction.STOP and not owner:
        contacts.remove(contact.id, user.id)
        await query.answer("Stopped")
        await tell(context, users.get_by_id(contact.owner_user_id),
                   f"🚫 {contact.name} stopped your reminders. Ones you'd set for them are cancelled.")
        await show_people(update, context)

    else:
        await query.answer()


# --- ✏️ Rename ----------------------------------------------------------------

async def on_contact_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """The answer to ✏️ Rename."""
    reply = update.effective_message.reply_text
    name = clean_name(text)
    if name is None:
        await reply("Use a name of up to 32 letters, digits, spaces, ' or -, starting with a letter (not “me”).")
        return
    user = users.get_or_create(update.effective_user.id)
    contact = contacts.get(context.user_data.get(RENAME_CONTACT_ID) or 0)
    if contact is None or contact.owner_user_id != user.id or contact.status == ContactStatus.DECLINED:
        # Removed meanwhile: there's nothing to rename any more.
        context.user_data.pop(AWAITING, None)
        context.user_data.pop(RENAME_CONTACT_ID, None)
        await reply("That person is no longer in your 👥 People.")
        return
    if contacts.rename(contact.id, user.id, name) is None:
        await reply(f"You already have someone called “{name}”. Pick another name.")
        return
    context.user_data.pop(AWAITING, None)
    context.user_data.pop(RENAME_CONTACT_ID, None)
    await reply(f"✏️ Renamed to {name}.")
    await show_people(update, context)


# --- ➕ Invite ----------------------------------------------------------------

async def on_new_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """👥 People → ➕ Invite: a single-use link, or their @username if they already use the bot."""
    await update.callback_query.answer()
    user = users.get_or_create(update.effective_user.id)
    invite = contacts.create_invite(user.id)
    link = f"https://t.me/{context.bot.username}?start={INVITE_PREFIX}{invite.token}"
    context.user_data[AWAITING] = Awaiting.CONTACT_USERNAME
    await render_menu(update, context, (
        "➕ Invite someone\n\n"
        "Send them this link. When they open it and tap ✅ Allow, you can send them reminders:\n\n"
        f"{link}\n\n"
        f"It works once, for {INVITE_LIFETIME.days} days.\n\n"
        "If they already use this bot, you can also just send me their @username."
    ), InlineKeyboardMarkup([[BACK]]))


async def on_start_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    """/start inv_<token>: someone opened an invite link. Ask them first."""
    reply = update.effective_message.reply_text
    invite = contacts.get_invite(token)
    user = users.get_or_create(update.effective_user.id)
    if invite is None or invite.used_at is not None:
        await reply("This invite link has already been used or doesn't exist. Ask for a new one.")
        return
    if invite.owner_user_id == user.id:
        await reply("That's your own invite link: send it to the person you want to remind.")
        return
    owner = users.get_by_id(invite.owner_user_id)
    await reply(
        f"👥 {display(owner)} wants to send you reminders.\n\n"
        "They'll see that you got them and whether you tapped ✅. "
        "You can stop it any time in 👥 People.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Allow", callback_data=f"{CallbackPrefix.INVITE}{PeopleAction.ALLOW}:{token}"),
            InlineKeyboardButton("❌ No", callback_data=f"{CallbackPrefix.INVITE}{PeopleAction.DECLINE}:{token}"),
        ]]),
    )


async def on_invite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✅ Allow / ❌ No on an invite."""
    query = update.callback_query
    action, token = query.data.removeprefix(CallbackPrefix.INVITE).split(":", 1)
    user = users.get_or_create(update.effective_user.id)

    if PeopleAction(action) == PeopleAction.DECLINE:
        await query.answer()
        owner = contacts.decline_invite(token, user)
        await query.edit_message_text("OK, not connected. Nobody can send you reminders without your OK.")
        if owner is not None:
            await tell(context, owner, f"{display(user)} declined your invite.")
        return

    accepted = contacts.use_invite(token, user)
    await query.answer()
    if accepted.result == InviteResult.ACCEPTED:
        await query.edit_message_text(
            f"✅ {display(accepted.owner)} can now send you reminders. Stop it any time in 👥 People."
        )
        await tell(context, accepted.owner,
                   f"✅ {display(user)} accepted your invite. They're in 👥 People as “{accepted.contact.name}”.")
    elif accepted.result == InviteResult.ALREADY:
        await query.edit_message_text(f"{display(accepted.owner)} can already send you reminders.")
    elif accepted.result == InviteResult.OWN:
        await query.edit_message_text("That's your own invite link: send it to the person you want to remind.")
    elif accepted.result == InviteResult.EXPIRED:
        await query.edit_message_text("This invite link has expired. Ask for a new one.")
    else:
        await query.edit_message_text("This invite link has already been used or doesn't exist. Ask for a new one.")


# --- requests by @username ----------------------------------------------------

async def on_contact_username_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """The @username of someone who already uses the bot: ask them."""
    reply = update.effective_message.reply_text
    username = text.strip().lstrip("@")
    owner = users.get_or_create(update.effective_user.id)
    other = users.get_by_username(username) if username and " " not in username else None
    if other is None:
        await reply(f"I don't know @{username}: they haven't used this bot yet. Send them the invite link instead.")
        return
    context.user_data.pop(AWAITING, None)
    if other.id == owner.id:
        await reply("That's you.")
        return
    result, contact = contacts.request(owner.id, other)
    if result == RequestResult.EXISTS:
        await reply(f"@{other.username} is already in your 👥 People (or hasn't answered yet).")
        return
    if result == RequestResult.DECLINED:
        await reply(f"@{other.username} said no recently. If they change their mind, send them the invite link.")
        return
    if result == RequestResult.TOO_MANY:
        await reply(f"That's {REQUESTS_PER_DAY} requests today. Try again tomorrow, or send the invite link.")
        return
    asked = await tell(context, other, f"👥 {display(owner)} wants to send you reminders.\n\n"
                       "They'll see that you got them and whether you tapped ✅. "
                       "You can stop it any time in 👥 People.",
                       InlineKeyboardMarkup([[
                           InlineKeyboardButton("✅ Allow", callback_data=people_callback(PeopleAction.ALLOW, contact.id)),
                           InlineKeyboardButton("❌ No", callback_data=people_callback(PeopleAction.DECLINE, contact.id)),
                       ]]))
    if not asked:
        contacts.remove(contact.id, owner.id)
        await reply(f"I can't message @{other.username} (they may have blocked the bot). Send them the invite link instead.")
        return
    await reply(f"📨 Asked @{other.username}. I'll tell you when they answer.")


async def answer_request(update: Update, context: ContextTypes.DEFAULT_TYPE, user, contact_id: int, allow: bool):
    query = update.callback_query
    contact = contacts.answer(contact_id, user.id, allow)
    await query.answer()
    if contact is None:
        await query.edit_message_text("This request is no longer open.")
        return
    owner = users.get_by_id(contact.owner_user_id)
    if allow:
        await query.edit_message_text(f"✅ {display(owner)} can now send you reminders. Stop it any time in 👥 People.")
        await tell(context, owner, f"✅ {display(user)} accepted. They're in 👥 People as “{contact.name}”.")
    else:
        await query.edit_message_text("OK, not connected. Nobody can send you reminders without your OK.")
        await tell(context, owner, f"{display(user)} declined your request.")
