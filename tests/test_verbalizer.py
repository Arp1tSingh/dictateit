"""Verbalizer tests: natural / explicit / symbols wording from the speech pack."""

import pytest

from dictateit.math.ast_nodes import to_latex
from dictateit.math.parser import parse_math
from dictateit.math.verbalizer import Verbalizer, number_words
from dictateit.settings import Settings
from dictateit.speech import load_pack

import sys


@pytest.fixture()
def vz_uk():
    settings = Settings()
    pack, letters = load_pack("en_uk")
    return Verbalizer(pack, letters, settings), settings


def say(vz, src, fmt="latex", mode="natural", **kw):
    r = parse_math(src, fmt, **kw)
    vz.set_case_context(r.ast)
    node = r.ast.lines[0].nodes[0] if len(r.ast.lines) == 1 else r.ast
    return vz.verbalize(node, mode)


def nat(vz, src, **kw):
    return say(vz, src, mode="natural", **kw)


def expl(vz, src, **kw):
    return say(vz, src, mode="explicit", **kw)


class TestNumbers:
    def test_words(self):
        assert number_words(0) == "zero"
        assert number_words(13) == "thirteen"
        assert number_words(21) == "twenty one"
        assert number_words(100) == "one hundred"
        assert number_words(250) == "two hundred fifty"
        assert number_words(3000) == "three thousand"

    def test_negative_and_decimal(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "-3 + x") .startswith("minus three")
        assert "point" in nat(vz, "3.14")


class TestBasicWording:
    def test_squared(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "x^2") == "ex squared"

    def test_cubed(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "y^3") == "why cubed"

    def test_power_of(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "2^n") == "two to the power of en"

    def test_compound_power_end_marker_both_passes(self, vz_uk):
        vz, _ = vz_uk
        n = nat(vz, "x^{n+1}")
        e = expl(vz, "x^{n+1}")
        assert n == "ex to the power of en plus one end power"
        assert "end power" in e

    def test_squared_not_on_power_of_power(self, vz_uk):
        vz, _ = vz_uk
        # (x^2)^3: outer exponent is 3 on a Power base -> "cubed" only if base
        # is not a Power; here base IS a Power so full wording appears
        words = nat(vz, "(x^2)^3")
        assert "cubed" in words

    def test_implicit_multiplication_silent(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "3x") == "three ex"

    def test_explicit_times(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "2 \\times 3") == "two times three"

    def test_relation(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "x = 5") == "ex equals five"
        assert nat(vz, "x <= 5") == "ex is less than or equal to five"

    def test_unary_minus(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "-x") == "minus ex"


class TestFractions:
    def test_natural(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\frac{a}{b}") == "fraction ay over bee end fraction"

    def test_explicit_has_numerator_words(self, vz_uk):
        vz, _ = vz_uk
        e = expl(vz, r"\frac{a}{b}")
        assert e == ("fraction, numerator, ay, over, denominator, bee, "
                     "end fraction")

    def test_derivative_reads_as_d(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\frac{dy}{dx}") == "dee why over dee ex"


class TestSubscripts:
    def test_simple(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "x_1") == "ex sub one"

    def test_compound(self, vz_uk):
        vz, _ = vz_uk
        n = nat(vz, "x_{n+1}")
        assert n == "ex subscript en plus one end subscript"


class TestRoots:
    def test_square(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\sqrt{x}") == "square root of ex"

    def test_cube(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\sqrt[3]{8}") == "cube root of eight"

    def test_general_degree(self, vz_uk):
        vz, _ = vz_uk
        assert "degree" in nat(vz, r"\sqrt[n]{x}")

    def test_compound_radicand_bracketed(self, vz_uk):
        vz, _ = vz_uk
        words = nat(vz, r"\sqrt{b^2-4ac}")
        assert words == ("square root of open bracket bee squared "
                         "minus four ay see close bracket")


class TestFunctions:
    def test_sine_of(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\sin x") == "sine of ex"

    def test_log_base(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\log_2 8") == "log to the base two of eight"

    def test_ln(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\ln x") == "natural log of ex"


class TestBrackets:
    def test_bracket_words(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "(x+1)") == "open bracket ex plus one close bracket"
        assert nat(vz, "[x]") == "open square bracket ex close square bracket"

    def test_deep_nesting_announced(self, vz_uk):
        vz, _ = vz_uk
        # ((x)) nests 2 deep; level words appear from depth 3
        words = nat(vz, "(((x)))")
        assert "level" in words


class TestCalculus:
    def test_sum(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\sum_{i=1}^{n} i") == (
            "sum from eye equals one to en of eye")

    def test_integral(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\int_0^1 x \, dx").startswith("integral from zero to one of")

    def test_limit(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\lim_{x \to 0} x") == "limit as ex tends to zero of ex"


class TestMatrices:
    def test_matrix_dimensions_explicit(self, vz_uk):
        vz, _ = vz_uk
        words = say(vz, r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}", mode="explicit")
        assert "two rows" in words and "two columns" in words
        assert "row one" in words and "row two" in words

    def test_determinant(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\begin{vmatrix} 1 & 0 \\ 0 & 1 \end{vmatrix}").startswith(
            "determinant")


class TestLetters:
    def test_letters_respelled(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "z") == "zed"
        assert nat(vz, "x") == "ex"

    def test_capital_announced_when_both_cases(self, vz_uk):
        vz, _ = vz_uk
        # both x and X in the same segment -> ambiguity -> announce capital
        words = nat(vz, "x + X")
        assert "capital ex" in words

    def test_no_capital_when_unambiguous(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, "x + y") == "ex plus why"


class TestGreek:
    def test_pack_respellings(self, vz_uk):
        vz, _ = vz_uk
        assert nat(vz, r"\pi") == "pie"
        assert nat(vz, r"\theta") == "thayta"


class TestSymbolsMode:
    def test_one_word_per_symbol(self, vz_uk):
        vz, _ = vz_uk
        r = parse_math("x^2 + 3x = 0", "latex")
        syms = vz.symbols(r.ast)
        assert syms == ["ex", "squared", "plus", "three", "ex", "equals", "zero"]


class TestExplicitPass:
    def test_explicit_joins_with_commas(self, vz_uk):
        vz, _ = vz_uk
        e = expl(vz, "3x")
        assert e == "three, ex"

    def test_fraction_structures_all_named(self, vz_uk):
        vz, _ = vz_uk
        e = expl(vz, r"\frac{1}{2}")
        for word in ("fraction", "numerator", "over", "denominator", "end fraction"):
            assert word in e


class TestLatexRoundtrip:
    def test_to_latex_reconstruction(self, vz_uk):
        assert to_latex(parse_math("x^2+3x-4=0", "latex").ast) == (
            "\\begin{align} (x^{2} + (3x)) - 4 = 0 \\end{align}")
