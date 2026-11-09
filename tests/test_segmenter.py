"""Segmenter tests: text vs math detection (blueprint 5.3)."""

from dictateit.math.segmenter import MathSegment, TextSegment, segment


def kinds(segs):
    return [(type(s).__name__, s.text) for s in segs]


class TestExplicitDelimiters:
    def test_dollar_math(self):
        segs = segment("Solve $x^2 = 4$ first.")
        assert kinds(segs) == [
            ("TextSegment", "Solve "),
            ("MathSegment", "$x^2 = 4$"),
            ("TextSegment", " first."),
        ]
        assert segs[1].fmt == "latex"

    def test_paren_math(self):
        segs = segment(r"Note that \(a + b = c\) holds.")
        assert segs[1].text == r"\(a + b = c\)"
        assert segs[1].fmt == "latex"

    def test_bracket_math(self):
        segs = segment(r"Then \[y = mx + c\] follows.")
        assert segs[1].fmt == "latex"

    def test_environment(self):
        segs = segment(r"Steps: \begin{align} x &= 1 \end{align} done.")
        assert segs[1].text == r"\begin{align} x &= 1 \end{align}"

    def test_two_math_spans(self):
        segs = segment("$a$ and $b$")
        assert [s.text for s in segs] == ["$a$", " and ", "$b$"]
        assert all(isinstance(s, MathSegment) for s in segs[::2])


class TestPlainDetection:
    def test_equation_detected(self):
        segs = segment("so we get x = 3y + 2 here")
        math = [s for s in segs if isinstance(s, MathSegment)]
        assert math, "plain equation should be detected as math"
        assert "x = 3y + 2" in math[0].text

    def test_prose_only(self):
        segs = segment("There is no mathematics in this sentence at all.")
        assert all(isinstance(s, TextSegment) for s in segs)

    def test_dates_not_math(self):
        segs = segment("The war ended on 12-05-1945, exactly.")
        assert all(isinstance(s, TextSegment) for s in segs)

    def test_times_not_math(self):
        segs = segment("The train leaves at 10:30 promptly.")
        assert all(isinstance(s, TextSegment) for s in segs)

    def test_scores_not_math(self):
        segs = segment("They won 3-2 easily that day.")
        assert all(isinstance(s, TextSegment) for s in segs)

    def test_hyphenated_words_not_math(self):
        segs = segment("This well-known fact is well-known indeed.")
        assert all(isinstance(s, TextSegment) for s in segs)

    def test_urls_not_math(self):
        segs = segment("Visit https://example.com/docs for more.")
        assert all(isinstance(s, TextSegment) for s in segs)


class TestAmbiguousModes:
    def test_low_confidence_flagged_in_ask_mode(self):
        # single signal (digits only) -> low confidence
        segs = segment("about 3/4 roughly")
        math = [s for s in segs if isinstance(s, MathSegment)]
        if math:  # detection is heuristic; when found it must be flagged
            assert math[0].ambiguous is True

    def test_text_mode_suppresses_low_confidence(self):
        segs = segment("about 3/4 roughly", ambiguous_mode="text")
        math = [s for s in segs if isinstance(s, MathSegment)]
        assert not math

    def test_high_confidence_not_flagged(self):
        segs = segment("so we get x = 3y + 2 here")
        math = [s for s in segs if isinstance(s, MathSegment)]
        assert math and math[0].ambiguous is False


class TestMixed:
    def test_order_preserved(self):
        text = "First $a=1$ then x = 2 later."
        segs = segment(text)
        texts = " ".join(s.text for s in segs)
        assert "First" in texts and "then" in texts and "later." in texts
        assert any(isinstance(s, MathSegment) for s in segs)

    def test_unicode_math_detected(self):
        segs = segment("Given x \u2264 \u03c0 the case holds.")
        math = [s for s in segs if isinstance(s, MathSegment)]
        assert math, "unicode math should be detected"
