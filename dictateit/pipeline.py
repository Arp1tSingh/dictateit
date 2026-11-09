"""Pipeline: text/math input -> ordered, renumbered chunk list.

    normalize -> segment (text | math) -> chunk each segment -> renumber

Math segments are parsed (LaTeX / plain / Unicode); a MathParseError falls
back to reading the raw text symbol-by-symbol, flagged ambiguous, so the
dictation never dies on bad input (agreed fallback behaviour).
"""

from __future__ import annotations

from .chunker import chunk_text
from .math.ast_nodes import MathParseError, token_count, to_latex
from .math.math_chunker import chunk_math
from .math.parser import parse_math
from .math.segmenter import MathSegment, segment
from .models import Chunk, ChunkKind
from .normalizer import normalize_text
from .settings import Settings
from .speech import load_pack


def build_chunks(text: str, settings: Settings | None = None,
                 pack: dict | None = None, letters: dict | None = None) -> list[Chunk]:
    """Turn free-form input (prose + math) into the final chunk list."""
    settings = settings or Settings()
    if pack is None or letters is None:
        pack, letters = load_pack(settings.get("locale", "en_uk"))

    text = normalize_text(text)
    ambiguous_mode = settings.get("math.ambiguous_detection", "ask")

    chunks: list[Chunk] = []
    segment_id = 0
    for seg in segment(text, ambiguous_mode):
        if isinstance(seg, MathSegment):
            chunks.extend(_math_chunks(seg, settings, pack, letters, segment_id))
            segment_id += 1
        else:
            chunks.extend(chunk_text(
                seg.text,
                max_words=int(settings.get("text.max_chunk_words", 8)),
                min_words=int(settings.get("text.min_chunk_words", 2)),
                say_punctuation=bool(settings.get("text.say_punctuation", True)),
                punct_map=pack.get("punctuation", {}),
            ))

    chunks = _fold_punctuation_chunks(chunks)
    for i, chunk in enumerate(chunks):
        chunk.index = i
    return chunks


def _fold_punctuation_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Merge chunks that are pure punctuation into a neighbour.

    Inline math leaves a lone '.' behind ("$x=1$. Note..."); a one-word
    chunk saying just "full stop" would get its own double take. Its words
    are appended to the previous chunk instead (or the next, if first).
    """
    def is_punct(c: Chunk) -> bool:
        return c.kind is ChunkKind.TEXT and all(
            ch in ".,;:!?)('\"[]" for ch in c.text.replace(" ", "")) and bool(c.text.strip())

    out: list[Chunk] = []
    for chunk in chunks:
        if is_punct(chunk) and out:
            prev = out[-1]
            # punctuation is announced on the explicit pass only
            prev.spoken_explicit += " " + chunk.spoken_explicit
            prev.spoken_symbols.extend(
                s for s in chunk.spoken_symbols if any(ch.isalnum() for ch in s))
            prev.size += chunk.size
            continue
        out.append(chunk)
    # a leading punctuation chunk merges forward
    while len(out) > 1 and is_punct(out[0]):
        first, nxt = out[0], out[1]
        nxt.spoken_explicit = first.spoken_explicit + " " + nxt.spoken_explicit
        nxt.spoken_symbols[:0] = [
            s for s in first.spoken_symbols if any(ch.isalnum() for ch in s)]
        del out[0]
    return out


def _math_chunks(seg: MathSegment, settings: Settings, pack: dict,
                 letters: dict, segment_id: int) -> list[Chunk]:
    from .math.verbalizer import Verbalizer

    fmt = seg.fmt if seg.fmt in ("latex", "plain", "unicode") else "plain"
    try:
        result = parse_math(seg.text, fmt, settings.get("custom_names") or [])
    except MathParseError:
        return _fallback_chunks(seg, settings, segment_id)

    verbalizer = Verbalizer(pack, letters, settings)
    verbalizer.set_case_context(result.ast)
    chunks = chunk_math(result.ast, verbalizer, settings, segment_id)
    ambiguous = seg.ambiguous or result.ambiguous
    if ambiguous:
        for chunk in chunks:
            chunk.ambiguous = True
    return chunks


def _fallback_chunks(seg: MathSegment, settings: Settings,
                     segment_id: int) -> list[Chunk]:
    """Parser failed: read the raw text symbol by symbol, flagged ambiguous."""
    symbols = _raw_symbols(seg.text)
    max_symbols = int(settings.get("math.max_chunk_tokens", 6)) * 3
    chunks: list[Chunk] = []
    for i in range(0, len(symbols), max_symbols):
        part = symbols[i:i + max_symbols]
        chunks.append(Chunk(
            kind=ChunkKind.MATH,
            index=-1,
            text=" ".join(part),
            spoken_natural=" ".join(part),
            spoken_explicit=", ".join(part),
            spoken_symbols=part,
            display_latex=None,
            size=len(part),
            ambiguous=True,
            segment_id=segment_id,
            extra_gap_s=1.0,   # raw reading is hard to write; be generous
        ))
    if not chunks:
        chunks.append(Chunk(
            kind=ChunkKind.MATH, index=-1, text=seg.text,
            spoken_natural=seg.text, spoken_explicit=seg.text,
            spoken_symbols=[seg.text], size=1, ambiguous=True,
            segment_id=segment_id, extra_gap_s=1.0,
        ))
    return chunks


def _raw_symbols(text: str) -> list[str]:
    """Split raw math text into spoken symbols (words, digits, operators)."""
    out: list[str] = []
    token = ""
    for ch in text:
        if ch.isalnum() or ch == ".":
            token += ch
        elif ch.isspace():
            if token:
                out.append(token)
                token = ""
        else:
            if token:
                out.append(token)
                token = ""
            out.append(_SYMBOL_WORDS.get(ch, ch))
    if token:
        out.append(token)
    return out


_SYMBOL_WORDS = {
    "+": "plus", "-": "minus", "*": "times", "/": "over", "=": "equals",
    "<": "less than", ">": "greater than", "^": "power", "_": "subscript",
    "(": "open bracket", ")": "close bracket", "[": "open square bracket",
    "]": "close square bracket", "{": "open curly bracket",
    "}": "close curly bracket", "|": "modulus", "&": "and", ",": "comma",
    ";": "semicolon", "!": "not", "\\": "backslash", "$": "dollar",
}
