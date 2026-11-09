"""Spell a word letter by letter (blueprint feature 6)."""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[A-Za-z0-9]")


def spell_word(word: str, letters: dict, capital_word: str = "capital") -> list[str]:
    """Return the spoken sequence for `word`.

    Handles apostrophes ("don't" -> doe, en, tee, apostrophe), hyphens
    ("well-known" -> both halves with "hyphen" between) and announces
    capital letters, since spelling exists to remove ambiguity.
    """
    word = word.strip().strip(",.;:!?\"'()")
    out: list[str] = []
    for ch in word:
        if ch == "'":
            out.append("apostrophe")
        elif ch == "-":
            out.append("hyphen")
        elif ch.isdigit():
            out.append(_digit_word(ch))
        elif ch.isalpha():
            if ch.isupper():
                out.append(capital_word)
            out.append(letters.get(ch.lower(), ch.lower()))
        # anything else (punctuation inside the word) is skipped
    return out


def last_word_of(text: str) -> str:
    """The last alphabetic run in a chunk, for 'spell that'."""
    matches = _WORD_RE.findall(text)
    if not matches:
        return ""
    # find the trailing run of word characters (letters, digits, ' and -)
    tail = re.search(r"[A-Za-z0-9'-]+", text[::-1])
    if not tail:
        return ""
    return tail.group(0)[::-1]


def _digit_word(ch: str) -> str:
    return {
        "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
        "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    }[ch]
