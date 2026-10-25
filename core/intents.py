"""Map trigger phrases in free text to bot actions.

Each intent lists the phrases that trigger it. A message triggers an intent
when it starts with one of its phrases (case-insensitive, whole words); the
rest of the message is handed to the action. To add a new free-text action,
add an Intent to INTENTS in handlers/intents.py.
"""

import re

from dataclasses import dataclass
from typing      import Awaitable, Callable, Optional

from core.typos  import Vocabulary

# action(update, context, rest_of_message): a Telegram handler in handlers/
Action = Callable[..., Awaitable[None]]

# Polite filler allowed before a trigger phrase: "please remind me ...",
# "hey, can you remind me ...", "also remind me ..."
FILLER = re.compile(r"^(?:(?:hey|hi|ok|okay|please|pls|can you|could you|would you|also|and|again)[\s,!]+)*",
                    re.IGNORECASE)

# Dropped from the end of a word when fixing typos: "remid me," → "remind me".
PUNCTUATION = ",.!?:;"


@dataclass
class Intent:
    name: str
    phrases: list
    action: Action
    # Whether typos of its phrases are fixed: not for "move", which "movie" is 1 letter from.
    typos: bool = True


@dataclass
class Match:
    intent: Intent
    rest: str


def match_intent(text: str, intents: list) -> Optional[Match]:
    """Return the intent whose longest phrase starts `text`, if any.

    If none does as written, small typos in the phrase are fixed and it is
    tried again ("remid me" → "remind me"); the rest keeps the original words.
    """
    stripped = FILLER.sub("", text.strip())
    return _match_exact(stripped, intents) or _match_with_typos(stripped, intents)


def _match_with_typos(stripped: str, intents: list) -> Optional[Match]:
    """Word by word, with typos of the phrases' words fixed; only if one was fixed."""
    intents = [intent for intent in intents if intent.typos]
    vocabulary = Vocabulary({w: w for intent in intents for p in intent.phrases for w in p.lower().split()})
    tokens = list(re.finditer(r"\S+", stripped))
    words = [t.group().lower().rstrip(PUNCTUATION) for t in tokens]
    fixed = [vocabulary.fix(w) for w in words]

    best = None
    for intent in intents:
        for phrase in intent.phrases:
            n = len(phrase.split())
            if fixed[:n] == phrase.lower().split() and fixed[:n] != words[:n] \
                    and (best is None or n > best[1]):
                best = (intent, n)
    if best is None:
        return None
    intent, n = best
    return Match(intent=intent, rest=stripped[tokens[n - 1].end():].strip())


def _match_exact(stripped: str, intents: list) -> Optional[Match]:
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
