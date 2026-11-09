"""Normalizer: clean text before chunking.

Collapses whitespace, straightens smart quotes, expands tokens that read
badly ("e.g." -> "for example", "&" -> "and").
"""

from __future__ import annotations

import re

# Tokens that read badly when spoken, mapped to what should be said instead.
# Case-insensitive on the word itself.
EXPANSIONS = {
    "e.g.": "for example",
    "e.g": "for example",
    "i.e.": "that is",
    "i.e": "that is",
    "etc.": "etcetera",
    "etc": "etcetera",
    "w/": "with",
    "&": "and",
    "→": "to",
}

# Characters replaced one-for-one before anything else.
CHAR_MAP = {
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2026": "...",
    "\u00a0": " ",  # no-break space
}


def normalize_text(text: str) -> str:
    text = "".join(CHAR_MAP.get(ch, ch) for ch in text)
    text = _expand_tokens(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _expand_tokens(text: str) -> str:
    words = text.split(" ")
    out = []
    for word in words:
        stripped = word.strip("(),;:!?\u2019\"'")
        lower = stripped.lower()
        if lower in EXPANSIONS:
            replacement = EXPANSIONS[lower]
            prefix = word[: len(word) - len(word.lstrip("(),;:!?\u2019\"'"))]
            suffix = word[len(prefix) + len(stripped):]
            out.append(prefix + replacement + suffix)
        else:
            out.append(word)
    return " ".join(out)
