"""What a handler did, for the web app's assistant view (#61): steps, result cards, follow-ups.

Telegram shows none of it (the reply's text already says it all), so these
calls do nothing there. A request from the web app (handlers/webapp.py)
comes with a `Report` on its update, and what's collected goes back as JSON:

    step(update, "Saved the event “padel”")
    sent = await update.effective_message.reply_text(...)
    card(update, sent, CardKind.EVENT, title=..., ...)
    suggest(update, "move it to 20:00", "the same next week")

Suggestions must be phrases the bot understands.
"""

import  re

from    enums       import CardKind


class Report:
    def __init__(self):
        self.steps = []
        # message id → the card shown in place of that message's text
        self.cards = {}
        self.suggestions = []


def when(text: str) -> str:
    """A time as the bot shows it, for a step: "Tomorrow, 09:00 (in 9 h)" → "tomorrow at 09:00"."""
    text = text.split(" (in ")[0]
    text = re.sub(r"^(Today|Tomorrow)\b", lambda m: m.group(1).lower(), text)
    return re.sub(r", (?=\d)", " at ", text, count=1)


def _report(update):
    return getattr(update, "report", None)


def step(update, text: str):
    report = _report(update)
    if report is not None:
        report.steps.append(text)


def card(update, message, kind: CardKind, **fields):
    """Show `message` (one just sent, or the one a button is on) as a card."""
    report = _report(update)
    if report is not None and message is not None:
        report.cards[message.message_id] = {"kind": kind, **fields}


def suggest(update, *phrases: str):
    report = _report(update)
    if report is not None:
        report.suggestions.extend(p for p in phrases if p not in report.suggestions)
