"""Fix small typos in words the bot knows: "remid me", "tomorow", "wensday".

Only words of a known vocabulary are corrected, and only when one meaning is
clearly the closest; everything else is left as written. The parser and the
intent matcher use this as a second try, when a message isn't understood as
written, so it can't change how a correctly typed message is read.
"""

import re

from typing import Optional

# Common shorthand that's too far from the word for typo distance.
ALIASES = {"tonite": "tonight", "tmrw": "tomorrow", "tmr": "tomorrow", "2morrow": "tomorrow"}

# A word and the punctuation around it: "tomorow," -> ("", "tomorow", ",").
WORD_RE = re.compile(r"^(\W*)([\w']+)(\W*)$")


def distance(a: str, b: str) -> int:
    """Edits (insert, delete, replace, swap two neighbours) between a and b."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            row[j] = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], prev2[j - 2] + 1)
        prev2, prev = prev, row
    return prev[len(b)]


def max_typos(word: str, known: str) -> int:
    """How many edits make `word` a typo of `known`: none if it's under 4
    letters, 2 if either is 8 or more ("wensday" → "wednesday"), else 1."""
    if len(word) < 4:
        return 0
    return 1 if max(len(word), len(known)) < 8 else 2


class Vocabulary:
    """Known words, each with a meaning: words with the same meaning are
    interchangeable ("minute" and "minutes"), so a tie between them is fine."""

    def __init__(self, meanings: dict):
        self.meanings = {word.lower(): meaning for word, meaning in meanings.items()}

    def correct(self, word: str) -> Optional[str]:
        """The known word `word` is a typo of, or None."""
        word = word.lower()
        if word in self.meanings:
            return None
        # Numbers and times ("9am", "18") are never typos of a word.
        if not word.replace("'", "").isalpha():
            return None
        if word in ALIASES:
            return ALIASES[word]

        best, candidates = None, []
        for known in self.meanings:
            limit = max_typos(word, known)
            if abs(len(known) - len(word)) > limit:
                continue
            d = distance(word, known)
            if d > limit:
                continue
            if best is None or d < best:
                best, candidates = d, [known]
            elif d == best:
                candidates.append(known)
        # Two different meanings equally close: don't guess.
        if not candidates or len({self.meanings[c] for c in candidates}) != 1:
            return None
        return candidates[0]

    def fix(self, token: str) -> str:
        """`token` with its word corrected, keeping punctuation around it."""
        m = WORD_RE.match(token)
        if not m:
            return token
        fixed = self.correct(m.group(2))
        return token if fixed is None else m.group(1) + fixed + m.group(3)

    def fix_all(self, tokens: list) -> list:
        return [self.fix(t) for t in tokens]
