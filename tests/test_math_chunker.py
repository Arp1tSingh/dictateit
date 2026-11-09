"""Math chunker tests: split points, markers, sizes (blueprint 5.7)."""

import pytest

from dictateit.math.math_chunker import chunk_math, FRACTION_SPLIT_TOKENS
from dictateit.math.parser import parse_math
from dictateit.math.verbalizer import Verbalizer
from dictateit.models import ChunkKind
from dictateit.settings import Settings
from dictateit.speech import load_pack


@pytest.fixture()
def env():
    settings = Settings()
    pack, letters = load_pack("en_uk")
    vz = Verbalizer(pack, letters, settings)
    return vz, settings


def chunks_for(src, fmt, env, **kw):
    vz, settings = env
    r = parse_math(src, fmt, **kw)
    return chunk_math(r.ast, vz, settings, segment_id=7)


class TestRelationChunking:
    def test_relation_ends_chunk(self, env):
        # "x equals" — the agreed convention
        cs = chunks_for("x = 5", "latex", env)
        assert cs[0].spoken_natural == "ex equals"
        assert cs[1].spoken_natural == "five"

    def test_rhs_separate_chunk(self, env):
        cs = chunks_for("y = 2x + 1", "latex", env)
        # y=...: "why equals" | "two ex plus one"
        assert cs[0].spoken_natural == "why equals"
        assert cs[1].spoken_natural == "two ex plus one"


class TestAdditiveSplitting:
    def test_unary_minus_lead(self, env):
        cs = chunks_for("-b + c + d + e + f + g", "latex", env)
        # 8+ tokens force the split; the leading unary minus is spoken
        assert cs[0].spoken_natural == "minus bee"
        assert cs[1].spoken_natural == "plus see"

    def test_short_expression_stays_whole(self, env):
        # rule 2 splitting only applies when the chunk would be over-long
        cs = chunks_for("-b + c", "latex", env)
        assert len(cs) == 1
        assert cs[0].spoken_natural == "minus bee plus see"

    def test_plus_minus_starts_chunk(self, env):
        cs = chunks_for("a + b \\pm c + d + e + f", "latex", env)
        nats = [c.spoken_natural for c in cs]
        assert "plus or minus see" in nats

    def test_long_expression_splits(self, env):
        cs = chunks_for("1 + 2 + 3 + 4 + 5 + 6", "latex", env)
        # each operator starts the next chunk
        assert cs[0].spoken_natural == "one"
        assert cs[1].spoken_natural == "plus two"
        assert cs[-1].spoken_natural == "plus six"


class TestFractionSplitting:
    def test_small_fraction_whole(self, env):
        cs = chunks_for(r"\frac{1}{2}", "latex", env)
        assert len(cs) == 1
        assert cs[0].spoken_natural == "fraction one over two end fraction"

    def test_natural_and_explicit_structure_words(self, env):
        cs = chunks_for(r"\frac{a+b}{c}", "latex", env)
        # 1 + 3 + 1 = 5 tokens <= 6 -> single chunk, but explicit pass
        # names numerator/denominator
        assert len(cs) == 1
        assert cs[0].spoken_natural == "fraction ay plus bee over see end fraction"
        assert cs[0].spoken_explicit == (
            "fraction, numerator, ay, plus, bee, over, denominator, see, end fraction")

    def test_big_fraction_splits(self, env):
        cs = chunks_for(r"\frac{a+b+c+d+e}{2}", "latex", env)
        assert len(cs) >= 2
        joined = " ".join(c.spoken_natural for c in cs)
        assert "over" in joined and "end fraction" in joined

    def test_multi_chunk_numerator_gets_end_numerator_lead(self, env):
        # numerator: x+y+z+w+v (9 tokens > 4) must split; denominator multi too
        cs = chunks_for(r"\frac{x+y+z+w+v}{p+q+r+s+t}", "latex", env)
        explices = [c.spoken_explicit for c in cs]
        # the first denominator piece leads with "end numerator, over, denominator"
        assert any(t.startswith("end numerator, over, denominator") for t in explices)
        # natural pass marks the switch with "over" only
        nats = [c.spoken_natural for c in cs]
        assert any(t.startswith("over") for t in nats)
        assert not any(t.startswith("end numerator") for t in nats)

    def test_fraction_split_token_constant(self):
        assert FRACTION_SPLIT_TOKENS == 4


class TestGroupSplitting:
    def test_small_group_whole(self, env):
        cs = chunks_for("(x + 1)^2", "latex", env)
        assert len(cs) == 1
        assert "open bracket" in cs[0].spoken_natural

    def test_big_group_splits_with_bracket_words(self, env):
        cs = chunks_for("(1 + 2 + 3 + 4 + 5 + 6)", "latex", env)
        assert len(cs) >= 2
        assert cs[0].spoken_natural.startswith("open bracket")
        assert cs[-1].spoken_natural.endswith("close bracket")


class TestBigOpsAndPowers:
    def test_bigop_head_then_body(self, env):
        cs = chunks_for(r"\sum_{i=1}^{n} i^2", "latex", env)
        assert cs[0].spoken_natural.startswith("sum from")
        assert cs[0].extra_gap_s > 0
        assert "eye squared" in cs[1].spoken_natural

    def test_compound_power_end_marker(self, env):
        cs = chunks_for("x^{n+1}", "latex", env)
        # whole thing fits in one chunk; end power present in both passes
        assert len(cs) == 1
        assert "end power" in cs[0].spoken_natural
        assert "end power" in cs[0].spoken_explicit


class TestMatrices:
    def test_matrix_rows_are_chunks(self, env):
        cs = chunks_for(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}", "latex", env)
        assert len(cs) == 3  # head + row one + row two
        assert "open matrix" in cs[0].spoken_natural
        assert "row one" in cs[1].spoken_natural
        assert "row two" in cs[2].spoken_natural
        assert "close matrix" in cs[2].spoken_natural

    def test_matrix_head_has_extra_gap(self, env):
        cs = chunks_for(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}", "latex", env)
        assert cs[0].extra_gap_s >= 1.0  # writer draws the bracket shape


class TestMultiLine:
    def test_line_markers(self, env):
        src = r"\begin{align} x &= 1 \\ y &= 2 \end{align}"
        cs = chunks_for(src, "latex", env)
        joined = " | ".join(c.spoken_natural for c in cs)
        assert "line one" in joined
        assert "line two" in joined
        # line markers come first on their line's first chunk
        assert cs[0].spoken_natural.startswith("line one")


class TestChunkFields:
    def test_kind_and_segment(self, env):
        cs = chunks_for("x = 1", "latex", env)
        assert all(c.kind is ChunkKind.MATH for c in cs)
        assert all(c.segment_id == 7 for c in cs)

    def test_display_latex_present(self, env):
        cs = chunks_for("x = 1", "latex", env)
        assert all(c.display_latex for c in cs)

    def test_symbols_populated(self, env):
        cs = chunks_for("x = 1", "latex", env)
        assert cs[0].spoken_symbols == ["ex", "equals"]
        assert cs[1].spoken_symbols == ["one"]

    def test_sizes_positive(self, env):
        cs = chunks_for("x = \\frac{a+b}{c}", "latex", env)
        assert all(c.size > 0 for c in cs)
