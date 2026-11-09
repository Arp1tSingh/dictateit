"""Shared data model: the Chunk object produced by both the text and math pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChunkKind(str, Enum):
    TEXT = "text"
    MATH = "math"


@dataclass
class Chunk:
    """One dictation unit.

    kind              "text" or "math" (engine picks the timing profile from this)
    index             position in the full chunk sequence
    text              original source text for this chunk
    spoken_natural    pass 1: how a teacher would naturally say it
    spoken_explicit   pass 2 (slow): every structural boundary made explicit
    spoken_symbols    optional pass 3: one symbol at a time
    display_latex     LaTeX for the preview window (math chunks)
    size              words (text) or tokens (math); drives the write gap
    ambiguous         flagged ambiguous plain-text math (parser convention)
    segment_id        groups chunks that belong to one math segment/equation
    extra_gap_s       extra write gap for structure the writer must draw
    """

    kind: ChunkKind
    index: int
    text: str
    spoken_natural: str
    spoken_explicit: str
    spoken_symbols: list[str] = field(default_factory=list)
    display_latex: str | None = None
    size: int = 0
    ambiguous: bool = False
    segment_id: int = -1
    extra_gap_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "index": self.index,
            "text": self.text,
            "spoken_natural": self.spoken_natural,
            "spoken_explicit": self.spoken_explicit,
            "spoken_symbols": list(self.spoken_symbols),
            "display_latex": self.display_latex,
            "size": self.size,
            "ambiguous": self.ambiguous,
            "segment_id": self.segment_id,
            "extra_gap_s": self.extra_gap_s,
        }
