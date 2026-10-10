"""Map trigger phrases in free text to bot actions.

Each intent lists the phrases that trigger it. A message triggers an intent
when it starts with one of its phrases (case-insensitive, whole words); the
rest of the message is handed to the action. To add a new free-text action,
add an Intent to INTENTS in intents/registry.py.
"""

import re

from dataclasses    import dataclass
from typing         import Awaitable, Callable, Optional

from telegram       import Update
from telegram.ext   import ContextTypes

# action(update, context, rest_of_message)
Action = Callable[[Update, ContextTypes.DEFAULT_TYPE, str], Awaitable[None]]

# Polite filler allowed before a trigger phrase: "please remind me ...",
# "hey, can you remind me ..."
FILLER = re.compile(r"^(?:(?:hey|hi|ok|okay|please|pls|can you|could you|would you)[\s,!]+)*", re.IGNORECASE)


@dataclass
class Intent:
    name: str
    phrases: list
    action: Action


@dataclass
class Match:
    intent: Intent
    rest: str


def match_intent(text: str, intents: list) -> Optional[Match]:
    """Return the intent whose longest phrase starts `text`, if any."""
    stripped = FILLER.sub("", text.strip())
    lowered = stripped.lower()

    best = None
    for intent in intents:
        for phrase in intent.phrases:
            phrase = phrase.lower()
            if not lowered.startswith(phrase):
                continue
            # Whole words only: "reminders" must not match "remind".
            after = lowered[len(phrase):len(phrase) + 1]
            if after and (after.isalnum() or after == "_"):
                continue
            if best is None or len(phrase) > len(best[1]):
                best = (intent, phrase)

    if best is None:
        return None

    intent, phrase = best
    return Match(intent=intent, rest=stripped[len(phrase):].strip())
