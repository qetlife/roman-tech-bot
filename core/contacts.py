"""Contact names: what you call the people you can remind ("anna", "mom").

No Telegram, no database: db/repositories/contact.py stores them.
"""

import re

from typing import Optional

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
