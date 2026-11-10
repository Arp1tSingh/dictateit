"""Input loader: .txt / .md / .docx files -> dictation text (blueprint 7).

`.docx` equations become inline `$latex$` spans (via math/omml.py), so
the rest of the pipeline is unchanged: the segmenter sees explicit
delimiters, the parser sees LaTeX. Only the stdlib is used — a .docx
is a zip with XML inside, which does not justify a python-docx
dependency for one read path.
"""

from __future__ import annotations

from pathlib import Path


def load_text(path) -> str:
    """Read a document by extension. Raises ValueError for unknown types."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md", ".markdown", ".tex"):
        return path.read_text(encoding="utf-8-sig")
    if suffix == ".docx":
        from .math.omml import read_docx

        return read_docx(path)
    raise ValueError(f"unsupported file type: {suffix!r} "
                     "(supported: .txt .md .tex .docx)")


def append_extension(path, suffix: str) -> Path:
    """'notes' + '.txt' -> notes.txt (used for future export helpers)."""
    return Path(path).with_suffix(suffix)
