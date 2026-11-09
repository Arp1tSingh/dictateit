"""Preview tests: mathtext rendering degrades gracefully (blueprint 6, 9)."""

import pytest

pytest.importorskip("matplotlib", reason="matplotlib not installed")

from dictateit.math.preview import PreviewCache, render_png


class TestRender:
    def test_simple_expression_renders(self):
        png = render_png("x^{2} + (3x) - 4 = 0")
        assert png is not None
        assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic

    def test_fraction_renders(self):
        assert render_png(r"\frac{-b \pm \sqrt{b^{2} - ((4a)c)}}{2a}") is not None

    def test_align_wrapper_stripped(self):
        latex = r"\begin{align} x = 1 \end{align}"
        assert render_png(latex) is not None

    def test_matrix_body_renders_degraded(self):
        # mathtext has no environment support; the preprocessor strips the
        # matrix wrapper so the cell contents still preview (no exception)
        result = render_png(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}")
        assert result is None or result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_garbage_degrades_to_none(self):
        assert render_png(r"\foo{bar baz}}{{{") is None

    def test_empty(self):
        assert render_png("") is None
        assert render_png("   ") is None

    def test_unicode_relation(self):
        # to_latex output uses \le etc., which mathtext knows
        assert render_png(r"x \le \pi") is not None


class TestCache:
    def test_same_key_rendered_once(self, monkeypatch):
        calls = []
        monkeypatch.setattr("dictateit.math.preview.render_png",
                            lambda *a, **kw: calls.append(1) or b"png")
        cache = PreviewCache()
        assert cache.get("x^2") == b"png"
        assert cache.get("x^2") == b"png"
        assert len(calls) == 1

    def test_none_latex_short_circuits(self):
        cache = PreviewCache()
        assert cache.get(None) is None
        assert cache.get("") is None

    def test_clear(self, monkeypatch):
        monkeypatch.setattr("dictateit.math.preview.render_png", lambda *a, **kw: b"x")
        cache = PreviewCache()
        cache.get("x")
        cache.clear()
        cache.get("x")  # must render again without error
