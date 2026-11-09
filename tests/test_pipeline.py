"""Pipeline tests: full input -> chunks, renumbering, fallback."""

from dictateit.models import ChunkKind
from dictateit.pipeline import build_chunks
from dictateit.settings import Settings


def test_prose_only():
    chunks = build_chunks("The sky is blue. Grass is green!")
    assert [c.kind for c in chunks] == [ChunkKind.TEXT] * len(chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_mixed_prose_and_math():
    chunks = build_chunks("Remember that x = 5 always. Then add $\\frac{1}{2}$.")
    kinds = [c.kind for c in chunks]
    assert ChunkKind.TEXT in kinds and ChunkKind.MATH in kinds
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # order preserved: text first
    assert kinds[0] is ChunkKind.TEXT


def test_math_segment_id_groups_equation():
    chunks = build_chunks("Solve $x + 1 = 2$ now.")
    math = [c for c in chunks if c.kind is ChunkKind.MATH]
    assert math
    assert all(c.segment_id == math[0].segment_id for c in math)


def test_two_equations_different_segments():
    chunks = build_chunks("$a = 1$ and $b = 2$")
    math = [c for c in chunks if c.kind is ChunkKind.MATH]
    assert len({c.segment_id for c in math}) == 2


def test_parse_failure_falls_back_to_symbols():
    chunks = build_chunks(r"$\foo{bar}$")
    assert len(chunks) == 1
    c = chunks[0]
    assert c.ambiguous is True
    assert c.kind is ChunkKind.MATH
    assert c.spoken_symbols  # raw symbols present
    assert any("backslash" in s or "foo" in s for s in c.spoken_symbols)


def test_ambiguous_math_flagged_through_pipeline():
    chunks = build_chunks("$1/2x$")
    assert all(c.ambiguous for c in chunks)


def test_normalization_applied():
    chunks = build_chunks("cats & dogs")
    assert any("and" in c.text for c in chunks)


def test_unicode_math_chunked():
    chunks = build_chunks("Given x \u2264 \u03c0 done.")
    assert any(c.kind is ChunkKind.MATH for c in chunks)


def test_renumbering_is_contiguous_across_kinds():
    chunks = build_chunks("Text intro here.\n$x=1$\nMore text follows here.")
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_empty_input():
    assert build_chunks("") == []


def test_settings_respected_max_words():
    settings = Settings()
    settings.set("text.max_chunk_words", 3)
    chunks = build_chunks("one two three four five six seven", settings)
    assert all(c.size <= 3 + 2 for c in chunks)  # +2: merge tolerance
