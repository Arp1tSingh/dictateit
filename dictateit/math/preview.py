"""Formula preview: LaTeX -> PNG for the UI (blueprint 6, 9).

`matplotlib.mathtext` renders a subset of LaTeX. It has no environment
support (`\\begin{align}`, matrices), so those are pre-stripped where
possible and failures degrade to `None` — the UI then shows the chunk
text instead of a rendered image. Rendering is cached: the state callback
fires many times per chunk and mathtext is not cheap.
"""

from __future__ import annotations

import io
import re

_ENVIRONMENTS = ("align", "align*", "equation", "equation*", "gather", "gather*")


def _mathtext_source(latex: str) -> str:
    """Adapt display_latex to what mathtext can render."""
    src = latex.strip()
    # top-level align/equation wrappers: keep the body, row breaks become spaces
    for env in _ENVIRONMENTS:
        begin, end = f"\\begin{{{env}}}", f"\\end{{{env}}}"
        if src.startswith(begin) and src.endswith(end):
            src = src[len(begin):-len(end)]
            break
    src = src.replace("\\\\", "  ")   # row/line separators: no environments
    src = src.replace("\\begin{pmatrix}", "").replace("\\end{pmatrix}", "")
    src = src.replace("\\begin{vmatrix}", "").replace("\\end{vmatrix}", "")
    src = src.replace("\\begin{cases}", "").replace("\\end{cases}", "")
    src = src.replace("&", "  ")      # cell separators
    # mathtext knows \leq/\geq but not the TeX aliases \le/\ge
    src = re.sub(r"\\le(?![A-Za-z])", r"\\leq", src)
    src = re.sub(r"\\ge(?![A-Za-z])", r"\\geq", src)
    return f"${src}$"


def render_png(latex: str, dpi: float = 160, color: str = "#1a1a1a",
               font_size: float = 13) -> bytes | None:
    """Render `latex` to PNG bytes, or None if it cannot be rendered.

    Bad input and a missing matplotlib both degrade to None rather than
    raising: the preview is a nicety, never a dictation blocker.
    """
    if not latex or not latex.strip():
        return None
    try:
        from matplotlib import font_manager, mathtext

        prop = font_manager.FontProperties(size=font_size)
        buf = io.BytesIO()
        mathtext.math_to_image(_mathtext_source(latex), buf,
                               prop=prop, dpi=dpi, format="png", color=color)
        return buf.getvalue()
    except Exception:  # ValueError from mathtext, ImportError, ...
        return None


class PreviewCache:
    """Keyed cache so each formula renders at most once per window."""

    def __init__(self):
        self._cache: dict[tuple, bytes | None] = {}

    def get(self, latex: str | None, dpi: float = 160, color: str = "#1a1a1a",
            font_size: float = 13) -> bytes | None:
        if not latex:
            return None
        key = (latex, dpi, color, font_size)
        if key not in self._cache:
            self._cache[key] = render_png(latex, dpi, color, font_size)
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()
