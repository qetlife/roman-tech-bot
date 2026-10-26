"""A reply as it should be said out loud (the web app's spoken replies).

"⏰ Got it: call mom\n🗓 Tomorrow, 09:00 (in 9 h)" → "Got it: call mom. Tomorrow, 9:00, in 9 hours."
Emoji go, lines become sentences, short units are said in full. No Telegram, no database.
"""

import re
import unicodedata


# The speech-service takes up to 1000 characters
MAX_CHARS = 900

UNITS = {"h": "hours", "min": "minutes", "d": "days", "w": "weeks"}
UNIT = re.compile(r"\b(\d+)\s?(h|min|d|w)\b")
CLOCK = re.compile(r"\b0(\d):(\d\d)\b")


def _is_symbol(char: str) -> bool:
    # Emoji and pictographs (So), their joiners and variation selectors
    return unicodedata.category(char) in ("So", "Sk", "Cf") or 0xFE00 <= ord(char) <= 0xFE0F


def speakable(text: str) -> str:
    """The reply without emoji and symbols, one sentence per line, cut to MAX_CHARS."""
    sentences = []
    for line in text.splitlines():
        line = "".join(" " if _is_symbol(c) else c for c in line)
        line = line.replace("“", "").replace("”", "").replace("•", "")
        line = re.sub(r"\(([^)]*)\)", r", \1", line)
        line = UNIT.sub(lambda m: f"{m.group(1)} {UNITS[m.group(2)]}", line)
        line = CLOCK.sub(r"\1:\2", line)
        line = re.sub(r"\s+,", ",", " ".join(line.split())).strip(" ,")
        if not line:
            continue
        line = line[0].upper() + line[1:]
        if line[-1] not in ".!?:":
            line += "."
        sentences.append(line)
    spoken = " ".join(sentences)
    if len(spoken) > MAX_CHARS:
        spoken = spoken[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return spoken
