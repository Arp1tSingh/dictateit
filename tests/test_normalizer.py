from dictateit.normalizer import normalize_text


def test_whitespace_collapsed():
    assert normalize_text("hello   world\tagain") == "hello world again"


def test_smart_quotes():
    out = normalize_text("\u201chello\u201d \u2018world\u2019")
    assert out == '"hello" \'world\''


def test_expansion_eg():
    out = normalize_text("Use tools, e.g. a hammer, carefully.")
    assert "for example" in out


def test_expansion_ampersand():
    out = normalize_text("cats & dogs")
    assert out == "cats and dogs"


def test_em_dash():
    assert normalize_text("well\u2014known") == "well-known"
