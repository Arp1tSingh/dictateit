"""Parser tests: precedence, ambiguity flags, structures, error handling."""

import pytest

from dictateit.math.ast_nodes import (
    Abs, BigOp, BinaryOp, Derivation, Fraction, Function, Group, Greek, Line,
    Matrix, Name, Number, Power, Relation, Root, Subscript, UnaryOp, Variable,
    MathParseError,
)
from dictateit.math.parser import parse_math


def ast(src, fmt="latex", **kw):
    return parse_math(src, fmt, **kw).ast


def first(ast):
    return ast.lines[0].nodes[0]


class TestBasics:
    def test_linear(self):
        node = first(ast("x + 3 = 7"))
        assert node == Relation("=", BinaryOp("+", Variable("x"), Number("3")), Number("7"))

    def test_number_decimal(self):
        assert first(ast("3.14")) == Number("3.14")

    def test_order_preserved_not_simplified(self):
        node = first(ast("3x + x^2"))
        # left-assoc: (3x) + (x^2), never reordered
        assert isinstance(node.left, BinaryOp) and node.left.implicit
        assert node.left == BinaryOp("*", Number("3"), Variable("x"), implicit=True)
        assert node.right == Power(Variable("x"), Number("2"))

    def test_left_assoc_subtraction(self):
        node = first(ast("a - b - c"))
        assert node == BinaryOp("-", BinaryOp("-", Variable("a"), Variable("b")), Variable("c"))


class TestPrecedence:
    def test_implicit_binds_tighter_than_explicit(self):
        # 2x/3 = (2x)/3 — decided convention
        node = first(ast("2x/3", fmt="plain"))
        assert isinstance(node, Fraction)
        assert node.numerator == BinaryOp("*", Number("2"), Variable("x"), implicit=True)
        assert node.denominator == Number("3")

    def test_division_left_to_right(self):
        node = first(ast("a/b/c", fmt="plain"))
        assert isinstance(node, Fraction)
        assert isinstance(node.numerator, Fraction)

    def test_unary_minus_vs_power(self):
        # -2^2 = -(2^2)
        node = first(ast("-2^2", fmt="plain"))
        assert node == UnaryOp("-", Power(Number("2"), Number("2")))

    def test_unary_minus_vs_explicit_mult(self):
        # -2*x = (-2)*x
        node = first(ast("-2*x", fmt="plain"))
        assert node == BinaryOp("*", UnaryOp("-", Number("2")), Variable("x"))

    def test_addition_binds_looser_than_multiplication(self):
        node = first(ast("1 + 2*3", fmt="plain"))
        assert node == BinaryOp("+", Number("1"), BinaryOp("*", Number("2"), Number("3")))


class TestAmbiguity:
    def test_half_x_flagged(self):
        r = parse_math("1/2x", "plain")
        assert r.ambiguous is True
        assert first(r.ast) == BinaryOp("*", Fraction(Number("1"), Number("2")),
                                        Variable("x"), implicit=True)

    def test_div_times_flagged(self):
        r = parse_math("a/b*c", "plain")
        assert r.ambiguous is True

    def test_plain_dy_dx_is_ambiguous_not_derivative(self):
        # agreed convention: strict left-to-right means plain dy/dx reads
        # (dy/d)·x and is flagged; the derivative pattern is recognised from
        # LaTeX \frac{dy}{dx} (see verbalizer tests)
        r = parse_math("dy/dx", "plain")
        assert r.ambiguous is True

    def test_parenthesised_division_not_flagged(self):
        assert parse_math("(a+b)/(c-d)", "plain").ambiguous is False

    def test_simple_division_not_flagged(self):
        assert parse_math("6/2", "plain").ambiguous is False

    def test_latex_frac_never_flagged(self):
        assert parse_math(r"\frac{1}{2}x", "latex").ambiguous is False


class TestStructures:
    def test_fraction(self):
        node = first(ast(r"\frac{a+b}{c}"))
        assert node == Fraction(BinaryOp("+", Variable("a"), Variable("b")), Variable("c"))

    def test_sqrt(self):
        assert first(ast(r"\sqrt{b^2-4ac}")) == Root(
            BinaryOp("-", Power(Variable("b"), Number("2")),
                     BinaryOp("*", BinaryOp("*", Number("4"), Variable("a"), implicit=True),
                              Variable("c"), implicit=True)))

    def test_nth_root(self):
        assert first(ast(r"\sqrt[3]{8}")) == Root(Number("8"), Number("3"))

    def test_plain_sqrt(self):
        assert first(ast("sqrt(x)", fmt="plain")) == Root(Group("(", Variable("x")))

    def test_compound_power(self):
        node = first(ast("(x+1)^{n-1}"))
        # the parenthesised base keeps its Group: the verbalizer speaks
        # "open bracket ... close bracket" for it
        assert node == Power(Group("(", BinaryOp("+", Variable("x"), Number("1"))),
                             BinaryOp("-", Variable("n"), Number("1")))

    def test_subscript(self):
        assert first(ast("x_1 + x_2", fmt="plain")) == BinaryOp(
            "+", Subscript(Variable("x"), Number("1")), Subscript(Variable("x"), Number("2")))

    def test_relation_chain(self):
        node = first(ast("a < b <= c", fmt="plain"))
        assert node == Relation("<=", Relation("<", Variable("a"), Variable("b")), Variable("c"))

    def test_abs(self):
        node = first(ast("|x - 1| <= 3", fmt="plain"))
        assert node == Relation("<=", Abs(BinaryOp("-", Variable("x"), Number("1"))), Number("3"))

    def test_latex_abs(self):
        assert first(ast(r"|x - 1| \le 3")) == Relation(
            "<=", Abs(BinaryOp("-", Variable("x"), Number("1"))), Number("3"))

    def test_log_base(self):
        node = first(ast(r"\log_2 8"))
        assert node == Function("log", Number("8"), base=Number("2"))

    def test_function_power(self):
        node = first(ast(r"\sin^2 x + \cos^2 x = 1"))
        # (sin x)^2 + (cos x)^2 = 1
        assert isinstance(node, Relation)
        assert node.left == BinaryOp("+", Power(Function("sin", Variable("x")), Number("2")),
                                     Power(Function("cos", Variable("x")), Number("2")))

    def test_greek(self):
        assert first(ast(r"\pi")) == Greek("pi")
        assert first(ast(r"\Delta")) == Greek("delta", upper=True)

    def test_plain_greek(self):
        assert first(ast("alpha + beta", fmt="plain")) == BinaryOp(
            "+", Greek("alpha"), Greek("beta"))

    def test_unicode_format(self):
        node = first(ast("x\u00b2 + \u221ay \u2264 \u03c0", fmt="unicode"))
        assert node == Relation("<=",
                                BinaryOp("+", Power(Variable("x"), Number("2")),
                                         Root(Variable("y")), implicit=False),
                                Greek("pi"))

    def test_custom_name_latex(self):
        assert first(ast(r"\text{cost} = 3x")) == Relation(
            "=", Name("cost"), BinaryOp("*", Number("3"), Variable("x"), implicit=True))

    def test_custom_name_plain(self):
        node = first(ast("cost = 3x", fmt="plain", custom_names=["cost"]))
        assert node == Relation("=", Name("cost"),
                                BinaryOp("*", Number("3"), Variable("x"), implicit=True))

    def test_without_custom_name_letters_split(self):
        node = first(ast("cost = 3x", fmt="plain", custom_names=[]))
        # c-o-s-t implicit product
        assert isinstance(node.left, BinaryOp)


class TestEnvironments:
    def test_align_lines(self):
        d = ast(r"\begin{align} 2x + 3 &= 11 \\ 2x &= 8 \end{align}")
        assert len(d.lines) == 2
        assert d.lines[0].nodes[0] == Relation("=", BinaryOp("+", BinaryOp(
            "*", Number("2"), Variable("x"), implicit=True), Number("3")), Number("11"))

    def test_matrix(self):
        node = first(ast(r"A = \begin{pmatrix}1&2\\3&4\end{pmatrix}"))
        assert isinstance(node, Relation)
        mat = node.right
        assert isinstance(mat, Matrix) and len(mat.rows) == 2
        assert mat.rows[0][0] == Number("1") and mat.rows[1][1] == Number("4")

    def test_determinant(self):
        node = first(ast(r"\begin{vmatrix} a & b \\ c & d \end{vmatrix}"))
        assert isinstance(node, Matrix) and node.kind == "vmatrix"

    def test_cases(self):
        node = first(ast(r"f(x) = \begin{cases} x & x \ge 0 \\ -x & x < 0 \end{cases}"))
        assert isinstance(node, Relation)
        assert isinstance(node.right, Matrix)

    def test_bigops(self):
        node = first(ast(r"\sum_{i=1}^{n} i^2"))
        assert node == BigOp("sum", Relation("=", Variable("i"), Number("1")),
                             Variable("n"), Power(Variable("i"), Number("2")))

    def test_integral(self):
        node = first(ast(r"\int_0^1 x^2 \, dx"))
        assert isinstance(node, BigOp) and node.kind == "int"
        assert node.lower == Number("0") and node.upper == Number("1")

    def test_limit(self):
        node = first(ast(r"\lim_{x \to 0} \frac{\sin x}{x}"))
        assert isinstance(node, BigOp) and node.kind == "lim"
        assert node.lower == Relation("to", Variable("x"), Number("0"))

    def test_infinity(self):
        node = first(ast(r"x \to \infty"))
        assert node == Relation("to", Variable("x"), Number("inf"))


class TestErrors:
    def test_unclosed_bracket(self):
        with pytest.raises(MathParseError):
            parse_math("(x + 1", "plain")

    def test_unsupported_command(self):
        with pytest.raises(MathParseError):
            parse_math(r"\foo{x}", "latex")

    def test_empty(self):
        with pytest.raises(MathParseError):
            parse_math("   ", "plain")

    def test_trailing_operator(self):
        with pytest.raises(MathParseError):
            parse_math("x +", "plain")


class TestLineBreaks:
    def test_plain_multiline(self):
        d = ast("x = 1\ny = 2", fmt="plain")
        assert len(d.lines) == 2

    def test_thousands_separator(self):
        assert first(ast("1,000 + 2,000.5", fmt="plain")) == BinaryOp(
            "+", Number("1000"), Number("2000.5"))
