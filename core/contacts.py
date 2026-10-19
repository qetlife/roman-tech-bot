"""Contact names: what you call the people you can remind ("anna", "mom").

No Telegram, no database: db/repositories/contact.py stores them.
"""

import re

from datetime    import datetime
from typing      import Optional

from core.parser import TIME_VOCABULARY, MissingText, ParseError, parse_reminder

NAME_LIMIT = 32
NAME_RE = re.compile(r"^[^\W\d_][\w' -]*$")
# Words that mean someone else in "remind … to …"
RESERVED = {"me", "myself", "us", "everyone", "all", "to", "about"}


def clean_name(text: str) -> Optional[str]:
    """A valid contact name from what was typed ("  Aunt  Mary " → "Aunt Mary"), or None.

    Letters first, then letters, digits, spaces, ' and -; at most 32 characters;
    not a word that means someone else ("me").
    """
    name = " ".join(text.strip().lstrip("@").split())
    if not name or len(name) > NAME_LIMIT or not NAME_RE.match(name) or name.lower() in RESERVED:
        return None
    return name


def unique_name(name: str, taken) -> str:
    """`name`, or "name 2", "name 3" … if one of `taken` already has it (case-insensitive)."""
    taken = {t.lower() for t in taken}
    if name.lower() not in taken:
        return name
    n = 2
    while f"{name} {n}".lower() in taken:
        n += 1
    return f"{name} {n}"


def default_name(first_name: Optional[str], username: Optional[str]) -> str:
    """The name a new contact gets: their Telegram first name, else their @username."""
    for candidate in (first_name, username):
        if candidate and (name := clean_name(candidate)):
            return name
    return "Contact"


# --- "remind anna …" -----------------------------------------------------------

def split_name(text: str, names) -> Optional[tuple]:
    """(the name `text` starts with, the rest) for the longest of `names` that it does, or None.

    Case-insensitive and whole words: with "anna", "Anna tomorrow at 9" is
    ("anna", "tomorrow at 9") but "annabel …" and "anna's …" aren't.
    """
    lowered = text.lower()
    best = None
    for name in names:
        n = len(name)
        if lowered.startswith(name.lower()) and (len(text) == n or text[n] in " ,:") \
                and (best is None or n > len(best)):
            best = name
    if best is None:
        return None
    return best, text[len(best):].lstrip(" ,:")


# Words that can follow "remind" without being someone ("remind in 2 hours …", "remind every day …").
NOT_NAMES = RESERVED | {
    "in", "at", "on", "by", "for", "this", "the", "a", "an", "of", "from", "until", "till", "that",
    "later", "soon", "again", "once",
}
# Words that start the reminder text right after a name: "anna to …".
TEXT_STARTS = ("to", "that", "about")


def unknown_name(text: str, now: datetime) -> Optional[str]:
    """The first word of `text` if it looks like someone's name ("anna to …"), else None.

    For "remind <text>" when <text> starts with none of the user's contacts.
    A name is followed by "to …" or a comma, or by a reminder that only makes sense
    without it ("anna tomorrow at 9 to …"). "remind call mom tomorrow" is a
    reminder as it stands, so "call" isn't a name.
    """
    words = text.split()
    if len(words) < 2:
        return None
    first = words[0].rstrip(",:")
    if first.startswith("@") and first[1:]:
        # "remind @anna …": someone's @username
        return first
    if not first.isalpha() or first.lower() in NOT_NAMES \
            or TIME_VOCABULARY.fix(first.lower()) in TIME_VOCABULARY.meanings:
        return None
    if words[1].lower() in TEXT_STARTS or words[0][-1] in ",:":
        # "anna to …", "anna, …"
        return first
    if not _is_reminder(text, now) and _is_reminder(" ".join(words[1:]), now):
        return first
    return None


def _is_reminder(text: str, now: datetime) -> bool:
    """Whether `text` is a reminder (or a time, which the bot asks the text for)."""
    try:
        parse_reminder(text, now)
    except MissingText:
        return True
    except ParseError:
        return False
    return True
