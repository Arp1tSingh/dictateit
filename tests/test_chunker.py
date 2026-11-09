"""Tests for the text chunker (blueprint section 4)."""

from dictateit.chunker import (
    chunk_text,
    merge_short_pieces,
    split_clauses,
    split_long_piece,
    split_sentences,
)

UK_PUNCT = {
    ",": "comma", ".": "full stop", "?": "question mark", "!": "exclamation mark",
    ":": "colon", ";": "semicolon", "(": "open bracket", ")": "close bracket",
    "open_quote": "open quote", "close_quote": "close quote",
    "newline": "new line", "paragraph": "new paragraph",
}


def make(text, **kw):
    defaults = dict(max_words=8, min_words=2, say_punctuation=True, punct_map=UK_PUNCT)
    defaults.update(kw)
    return chunk_text(text, **defaults)


class TestSentenceSplitting:
    def test_simple(self):
        s = split_sentences("The sky is blue. Grass is green!")
        assert s == ["The sky is blue.", "Grass is green!"]

    def test_abbreviation_not_sentence_end(self):
        s = split_sentences("Dr. Smith arrived. He was late.")
        assert len(s) == 2
        assert s[0].startswith("Dr. Smith")

    def test_abbreviation_us(self):
        s = split_sentences("The U.S. signed the treaty. Peace followed.")
        assert len(s) == 2
        assert s[0].startswith("The U.S.")

    def test_decimal_not_sentence_end(self):
        s = split_sentences("Pi is about 3.14 exactly? No, 3.14159.")
        assert len(s) == 2

    def test_single_initial(self):
        s = split_sentences("J. F. Kennedy spoke. The crowd listened.")
        assert len(s) == 2


class TestClauseSplitting:
    def test_commas(self):
        pieces = split_clauses("The industrial revolution, which began in Britain, transformed the world.")
        assert pieces[0] == "The industrial revolution,"
        assert pieces[1] == "which began in Britain,"
        assert pieces[2].startswith("transformed")

    def test_number_with_thousands_comma_not_split(self):
        pieces = split_clauses("The total was 1,000 pounds in total.")
        assert len(pieces) == 1
        assert "1,000" in pieces[0]

    def test_no_split_inside_quotes(self):
        pieces = split_clauses('He said "stop, please", and left.')
        joined = " ".join(pieces)
        assert '"stop, please"' in joined


class TestLongPieceSplitting:
    def test_split_at_connector(self):
        pieces = split_long_piece("the big red factory made lots of very noisy cars", 4)
        assert all(len(p.split(" ")) <= 4 for p in pieces)
        assert len(pieces) == 3
        assert pieces[1].startswith("factory")
        assert pieces[2].startswith("of")

    def test_connector_starts_next_chunk(self):
        pieces = split_long_piece("one two three four which five six seven eight", 4)
        assert pieces[1].startswith("which")

    def test_hyphenated_word_stays_intact(self):
        pieces = split_long_piece("this well-known fact remains true today always", 3)
        assert any("well-known" in p for p in pieces)


class TestMerging:
    def test_short_piece_merged(self):
        out = merge_short_pieces(["hello there", "oh", "the world turns"], 2)
        assert all(len(p.split(" ")) >= 2 for p in out)
        assert len(out) == 2

    def test_last_piece_merges_backwards(self):
        out = merge_short_pieces(["hello there friend", "oh"], 2)
        assert len(out) == 1


class TestChunking:
    def test_blueprint_example(self):
        chunks = make("The industrial revolution, which began in Britain, transformed the global economy.")
        texts = [c.text for c in chunks]
        assert texts == [
            "The industrial revolution,",
            "which began in Britain,",
            "transformed the global economy.",
        ]

    def test_punctuation_on_explicit_pass_only(self):
        chunks = make("The industrial revolution, which began in Britain, transformed the world.")
        first = chunks[0]
        assert first.spoken_natural == "The industrial revolution,"
        assert "comma" in first.spoken_explicit
        assert "comma" not in first.spoken_natural

    def test_punctuation_toggle(self):
        chunks = make("Hello, world.", say_punctuation=False)
        assert chunks[0].spoken_natural == chunks[0].spoken_explicit
        assert "comma" not in chunks[0].spoken_explicit

    def test_question_mark(self):
        chunks = make("How does this work?")
        assert "question mark" in chunks[0].spoken_explicit

    def test_paragraph_marker(self):
        chunks = make("First paragraph here.\n\nSecond paragraph here.")
        # every paragraph end is announced so the writer starts a new line
        assert "new paragraph" in chunks[0].spoken_explicit
        assert "new paragraph" in chunks[-1].spoken_explicit
        assert len(chunks) == 2

    def test_newline_marker_in_both_passes(self):
        chunks = make("Line one of the text.\nLine two of the text.")
        assert chunks[0].spoken_natural.startswith("new line") is False
        assert any(c.spoken_natural.startswith("new line") for c in chunks)
        assert any(c.spoken_explicit.startswith("new line") for c in chunks)

    def test_sizes(self):
        chunks = make("The industrial revolution, which began in Britain, transformed the global economy.")
        assert chunks[0].size == 3
        assert chunks[2].size == 4

    def test_no_empty_chunks(self):
        chunks = make("One. Two! Three? Four.")
        assert all(c.text.strip() for c in chunks)

    def test_dates_and_numbers_stay_intact(self):
        chunks = make("The war ended on 12-05-1945, exactly, at last.")
        assert any("12-05-1945" in c.text for c in chunks)
