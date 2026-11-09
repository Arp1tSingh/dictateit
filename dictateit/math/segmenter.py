r"""Segmenter: split input into text and math segments (blueprint 5.3).

Explicit delimiters ($...$, \(...\), \begin{...}) are always math.
Plain-text math is detected heuristically with a confidence check, and
low-confidence matches follow the "ambiguous_detection" setting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize_math import has_unicode_math


@dataclass
class TextSegment:
    text: str
    span: tuple[int, int]
    fmt: str = field(default="text", init=False)


@dataclass
class MathSegment:
    text: str
    span: tuple[int, int]
    fmt: str                     # "latex" | "plain" | "unicode"
    ambiguous: bool = False      # low-confidence detection
    marked: bool = False         # user marked it as math manually


# explicit delimiters, longest first
_EXPLICIT = [
    ("$$", "$$"),
    ("\\[", "\\]"),
    ("\\(", "\\)"),
    ("$", "$"),
]

_ENV_RE = re.compile(
    r"\\begin\{(\w+\*?)\}.*?\\end\{\1\}", re.DOTALL)

# operator between two operands (blueprint 5.3); unicode ops included
_PLAIN_CANDIDATE = re.compile(
    r"[\w\)\]]\s*[=<>+\-*/^]\s*[\w\(\[]"
    r"|[\w\)\]]\s*[≤≥≠≈]\s*[\w\(\[]"
    r"|[±×÷]\s*[\w\(]"
    r"|√\s*[\w\(]"
)

_MATH_RUN_CHARS = set("0123456789+-*/^=<>()[].,| \t≤≥≠≈±×÷√∞")

_DATE_RE = re.compile(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b")
_RANGE_RE = re.compile(r"^\d+\s*[-\u2013]\s*\d+$")
_HYPHEN_WORD_RE = re.compile(r"^[A-Za-z]+-[A-Za-z]+$")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_SCORE_RE = re.compile(r"^\d+\s*[-\u2013]\s*\d+\s*(win|loss|draw|lead)?$", re.IGNORECASE)
_URL_HINT = re.compile(r"(://|www\.|\.(com|org|net|edu)\b)", re.IGNORECASE)

_SINGLE_LETTER_VAR = re.compile(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])")


def segment(text: str, ambiguous_mode: str = "ask") -> list:
    """Split input into an ordered list of TextSegment / MathSegment.

    ambiguous_mode: "ask" -> include low-confidence math flagged ambiguous;
    "text" -> treat as text; "math" -> treat as math (unflagged).
    """
    segments: list = []
    spans = _explicit_math_spans(text)

    last = 0
    for start, end, fmt in spans:
        if start > last:
            segments.extend(_plain_math_segments(text, last, start, ambiguous_mode))
        segments.append(MathSegment(text[start:end], (start, end), fmt))
        last = end
    if last < len(text):
        segments.extend(_plain_math_segments(text, last, len(text), ambiguous_mode))

    # merge adjacent text segments (from skipped low-confidence runs)
    merged: list = []
    for seg in segments:
        if (merged and isinstance(seg, TextSegment)
                and isinstance(merged[-1], TextSegment)):
            prev = merged[-1]
            merged[-1] = TextSegment(
                text=prev.text + seg.text,
                span=(prev.span[0], seg.span[1]),
            )
        else:
            merged.append(seg)
    return merged


def _explicit_math_spans(text: str) -> list[tuple[int, int, str]]:
    """Find $...$, \\(...\\), \\[...\\] and \\begin{...} spans, longest first."""
    spans: list[tuple[int, int, str]] = []

    for m in _ENV_RE.finditer(text):
        spans.append((m.start(), m.end(), "latex"))

    used = [(s, e) for s, e, _ in spans]

    def overlaps(a: int, b: int) -> bool:
        return any(not (b <= s or a >= e) for s, e in used)

    for opener, closer in _EXPLICIT:
        pos = 0
        while True:
            start = text.find(opener, pos)
            if start == -1:
                break
            end = text.find(closer, start + len(opener))
            if end == -1:
                pos = start + 1
                continue
            end += len(closer)
            if opener == "$" and text[start:start + 2] == "$$":
                pos = start + 1
                continue
            if not overlaps(start, end):
                spans.append((start, end, "latex"))
                used.append((start, end))
            pos = end
    spans.sort()
    return spans


def _plain_math_segments(text: str, start: int, end: int, ambiguous_mode: str) -> list:
    """Heuristic plain-text / Unicode math detection inside a text region."""
    region = text[start:end]
    out: list = []
    last = 0

    # a region containing a URL is prose ("example.com/x" is not a fraction)
    if _URL_HINT.search(region):
        return [TextSegment(text[start:end], (start, end))]

    for m in _PLAIN_CANDIDATE.finditer(region):
        run_start, run_end = _math_run_bounds(region, m)
        if run_start is None:
            continue
        run = region[run_start:run_end].strip()
        if not run or not _is_math_run(run):
            continue
        confidence = _confidence(run)
        if confidence == "no":
            continue

        absolute = (start + run_start, start + run_end)
        if out and run_start <= out[-1].span[1] - start:
            continue

        if confidence == "low":
            if ambiguous_mode == "text":
                continue
            seg = MathSegment(region[run_start:run_end], absolute, "plain",
                              ambiguous=(ambiguous_mode != "math"))
        else:
            seg = MathSegment(region[run_start:run_end], absolute, "plain")
        out.append(seg)

        if run_end > last:
            last = run_end

    if not out:
        return [TextSegment(text[start:end], (start, end))]

    # rebuild: text before/between/after the math runs
    result: list = []
    cursor = start
    for seg in out:
        if seg.span[0] > cursor:
            result.append(TextSegment(text[cursor:seg.span[0]], (cursor, seg.span[0])))
        result.append(seg)
        cursor = seg.span[1]
    if cursor < end:
        result.append(TextSegment(text[cursor:end], (cursor, end)))
    return result


def _math_run_bounds(region: str, m: re.Match) -> tuple[int | None, int | None]:
    """Extend a candidate match outward to the full math run.

    Extends over math characters, whitespace and *single* letters (variable
    names like the y in 3y) but stops at words of 2+ letters.
    """
    s, e = m.start(), m.end()

    def extend(index: int, step: int) -> int:
        while True:
            nxt = index + step
            if nxt < 0 or nxt >= len(region):
                return index
            ch = region[nxt]
            if ch in _MATH_RUN_CHARS:
                index = nxt
                continue
            if ch.isalpha():
                run = _alpha_run(region, nxt, step)
                if len(run) == 1:
                    index = nxt + step * (len(run) - 1)
                    continue
            return index

    s = extend(s, -1)
    e = extend(e - 1, 1) + 1

    run = region[s:e]
    stripped = run.strip()
    if not stripped:
        return None, None
    off = run.find(stripped)
    return s + off, s + off + len(stripped)


def _alpha_run(text: str, start: int, step: int) -> str:
    """The maximal run of letters starting at `start` (going backwards if step < 0)."""
    out = []
    i = start
    while 0 <= i < len(text) and text[i].isalpha():
        out.append(text[i])
        i += step
    return "".join(out) if step > 0 else "".join(reversed(out))


def _is_math_run(run: str) -> bool:
    if _DATE_RE.search(run) or _TIME_RE.search(run):
        return False
    if _URL_HINT.search(run):
        return False
    core = run.strip()
    if _RANGE_RE.match(core) or _SCORE_RE.match(core) or _HYPHEN_WORD_RE.match(core):
        return False
    if "=" in core and core.count("=") == 1 and len(core) <= 2:
        return False
    if not _has_math_signal(core):
        return False
    return True


def _has_math_signal(run: str) -> bool:
    if any(ch.isdigit() for ch in run):
        return True
    if "=" in run:
        return True
    if _SINGLE_LETTER_VAR.search(run):
        return True
    if has_unicode_math(run):
        return True
    return False


def _confidence(run: str) -> str:
    """High / low / no."""
    signals = 0
    if any(ch.isdigit() for ch in run):
        signals += 1
    if "=" in run:
        signals += 1
    if _SINGLE_LETTER_VAR.search(run):
        signals += 1
    if re.search(r"\^|_|sqrt|\\frac", run):
        signals += 1
    if signals >= 2:
        return "high"
    if signals == 1:
        return "low"
    return "no"
