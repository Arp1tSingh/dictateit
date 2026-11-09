"""Text chunker: turns prose into dictation-sized chunks (blueprint section 4).

Rules, in order:
1. Split into sentences first (abbreviation- and decimal-aware).
2. Within a sentence, split at commas, semicolons, colons and brackets.
3. Split over-long pieces at conjunctions or prepositions.
4. Never split inside numbers, dates, abbreviations, quotes or hyphenated words.
5. Merge pieces below the minimum length into a neighbour.

Spoken punctuation is attached to the *explicit* (slow) pass only, so the
first pass stays natural.
"""

from __future__ import annotations

import re

from .models import Chunk, ChunkKind

# Abbreviations that must not end a sentence. Case-insensitive.
ABBREVIATIONS = {
    "dr.", "mr.", "mrs.", "ms.", "prof.", "st.", "sr.", "jr.", "fig.", "no.",
    "vs.", "etc.", "al.", "e.g.", "i.e.", "u.s.", "u.k.", "a.m.", "p.m.",
    "ph.d.", "dept.", "vol.", "pp.", "approx.", "rev.", "hon.",
}

# Single capital initial ("J. F. Kennedy") does not end a sentence either.
_INITIAL_RE = re.compile(r"^[A-Z]\.$")

# Connectors used when an over-long piece must be split further. The
# connector stays at the start of the following chunk, which matches how
# people break lines when writing (blueprint 4.1 rule 3).
CONNECTORS = {
    "and", "but", "because", "which", "that", "or",
    "in", "of", "for", "with",
}

_SENTENCE_SPLIT_RE = re.compile(r"([.!?]+)")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, protecting abbreviations and initials."""
    tokens = text.split(" ")
    sentences: list[str] = []
    current: list[str] = []

    for i, token in enumerate(tokens):
        current.append(token)
        if _ends_sentence(token, tokens[i + 1] if i + 1 < len(tokens) else ""):
            sentences.append(" ".join(current))
            current = []
    if current:
        sentences.append(" ".join(current))
    return sentences


def _ends_sentence(token: str, next_token: str) -> bool:
    if not token:
        return False
    last = token[-1]
    if last not in ".!?":
        return False
    lowered = token.lower()
    if lowered in ABBREVIATIONS:
        return False
    if _INITIAL_RE.match(token):
        return False
    if last == "." and len(token) > 1 and token[-2].isdigit():
        return False  # "3." at end of a number like "3." — treated as sentence end
    # "word)." and "word?" etc. are genuine sentence ends; nothing else to guard.
    _ = next_token
    return True


def split_clauses(sentence: str) -> list[str]:
    """Split a sentence at commas, semicolons, colons and brackets.

    Never splits inside quoted terms. Numbers like 1,000 stay intact
    because they contain no spaces (splitting is token-based).
    """
    tokens = sentence.split(" ")
    pieces: list[list[str]] = []
    current: list[str] = []
    in_quotes = False

    for token in tokens:
        starts_bracket = token.startswith("(") or token.startswith("[")
        ends_bracket = token.endswith(")") or token.endswith("]")

        if starts_bracket and current:
            pieces.append(current)
            current = [token]
        elif ends_bracket and current:
            current.append(token)
            pieces.append(current)
            current = []
        else:
            current.append(token)

            # Split after clause punctuation, but only if this token also
            # closed its quotes (e.g. he said "stop",) — the writer needs the
            # quote term complete before the break.
            split_after = (
                not in_quotes
                and _ends_with_clause_punct(token)
                and _comma_is_separator(token)
            )
            for ch in token:
                if ch == '"':
                    in_quotes = not in_quotes
            if split_after and not in_quotes:
                pieces.append(current)
                current = []

    if current:
        pieces.append(current)

    out = [" ".join(p).strip() for p in pieces if p and " ".join(p).strip()]
    return out


_CLAUSE_PUNCT = (",", ";", ":")


def _ends_with_clause_punct(token: str) -> bool:
    return token.endswith(_CLAUSE_PUNCT)


def _comma_is_separator(token: str) -> bool:
    """A trailing comma is a separator unless the token is a number like '1,' ."""
    if token.endswith(",") and len(token) > 1 and token[-2].isdigit():
        # "1," followed by a digit-only token would be a broken number; be safe.
        return False
    return True


def split_long_piece(piece: str, max_words: int) -> list[str]:
    """Recursively split an over-long piece at connectors, nearest to the middle."""
    tokens = piece.split(" ")
    if len(tokens) <= max_words:
        return [piece]

    candidates = [i for i, t in enumerate(tokens[1:], start=1)
                  if t.lower().strip(",.;:!?'\"") in CONNECTORS]
    if not candidates:
        # No connector: hard-split at the word boundary nearest the middle.
        mid = max(1, len(tokens) // 2)
        candidates = [mid]
    # Candidates point at the connector token; the split goes *before* it,
    # so the connector starts the next chunk.
    middle = len(tokens) / 2
    best = min(candidates, key=lambda i: abs(i - middle))
    left = " ".join(tokens[:best]).strip()
    right = " ".join(tokens[best:]).strip()
    if not left or not right:
        return [piece]
    return split_long_piece(left, max_words) + split_long_piece(right, max_words)


def _trailing_punct_words(token: str, punct_map: dict) -> list[str]:
    """Punctuation words for the trailing marks of a token, in written order."""
    marks = []
    for ch in reversed(token):
        if ch in ",.;:!?)]}\"":
            marks.append(ch)
        else:
            break
    marks.reverse()  # written order
    words = []
    for ch in marks:
        if ch in ")]}":
            words.append(punct_map.get(")", "close bracket"))
        elif ch == '"':
            words.append(punct_map.get("close_quote", "close quote"))
        else:
            words.append(punct_map.get(ch, ""))
    return [w for w in words if w]


def _leading_punct_words(token: str, punct_map: dict) -> list[str]:
    words = []
    for ch in token:
        if ch == "(":
            words.append(punct_map.get("(", "open bracket"))
        elif ch == "[":
            words.append(punct_map.get("(", "open bracket"))
        elif ch == '"':
            words.append(punct_map.get("open_quote", "open quote"))
        else:
            break
    return [w for w in words if w]


def chunk_text(
    text: str,
    *,
    max_words: int = 8,
    min_words: int = 2,
    say_punctuation: bool = True,
    punct_map: dict | None = None,
) -> list[Chunk]:
    """Turn one text segment into Chunk objects (index -1; renumbered later)."""
    punct = punct_map or {}
    chunks: list[Chunk] = []

    paragraphs = re.split(r"\n\s*\n", text)
    for para in paragraphs:
        lines = [l.strip() for l in para.split("\n")]
        for line_no, line in enumerate(lines):
            if not line:
                continue

            line_chunks: list[Chunk] = []
            for sentence in split_sentences(line):
                pieces: list[str] = []
                for raw_piece in split_clauses(sentence):
                    pieces.extend(split_long_piece(raw_piece, max_words))
                pieces = merge_short_pieces(pieces, min_words)

                for piece in pieces:
                    tokens = [t for t in piece.split(" ") if t]
                    if not tokens:
                        continue

                    first, last = tokens[0], tokens[-1]
                    lead_words = _leading_punct_words(first, punct)
                    trail_words = _trailing_punct_words(last, punct)

                    core = " ".join(tokens)
                    explicit = core
                    if say_punctuation:
                        explicit = " ".join(lead_words + [core] + trail_words)

                    line_chunks.append(
                        Chunk(
                            kind=ChunkKind.TEXT,
                            index=-1,
                            text=core,
                            spoken_natural=core,
                            spoken_explicit=explicit,
                            spoken_symbols=[t.strip(",.;:!?\"'()") for t in tokens],
                            size=len(tokens),
                        )
                    )

            if not line_chunks:
                continue

            # Structural layout markers are spoken in BOTH passes (the writer
            # needs them even on the fast pass); they are not punctuation.
            if line_no > 0:
                nl = punct.get("newline", "new line")
                first = line_chunks[0]
                first.spoken_natural = f"{nl} {first.spoken_natural}"
                first.spoken_explicit = f"{nl} {first.spoken_explicit}"
            marker = punct.get("paragraph", "new paragraph")
            last_chunk = line_chunks[-1]
            last_chunk.spoken_natural = f"{last_chunk.spoken_natural} {marker}"
            last_chunk.spoken_explicit = f"{last_chunk.spoken_explicit} {marker}"

            chunks.extend(line_chunks)
    return chunks


def merge_short_pieces(pieces: list[str], min_words: int) -> list[str]:
    """Merge pieces under the minimum word count into a neighbour (rule 5)."""
    if min_words <= 1 or len(pieces) <= 1:
        return pieces

    def word_count(p: str) -> int:
        return len([w for w in p.split(" ") if w])

    out = list(pieces)
    changed = True
    while changed and len(out) > 1:
        changed = False
        for i, piece in enumerate(out):
            if word_count(piece) < min_words:
                if i + 1 < len(out):
                    out[i] = piece + " " + out[i + 1]
                    del out[i + 1]
                else:
                    out[i - 1] = out[i - 1] + " " + piece
                    del out[i]
                changed = True
                break
    return out
