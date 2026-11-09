"""Corpus test: LaTeX / plain / Unicode forms of the same formula produce
the same AST (after unwrapping redundant grouping), and a sympy-based
numeric equivalence spot-check (tests only; never used at runtime).
"""

import json
from pathlib import Path

import pytest

from dictateit.math.ast_nodes import (
    Abs, BigOp, BinaryOp, Derivation, Fraction, Function, Group, Greek, Line,
    Matrix, Number, Power, Relation, Root, Subscript, UnaryOp, Variable, Name,
)
from dictateit.math.parser import parse_math

CORPUS = json.loads(
    (Path(__file__).parent / "formulas_corpus.json").read_text(encoding="utf-8"))
FORMULAS = CORPUS["formulas"]


def norm(node):
    """Structural copy with pure grouping unwrapped (Group(body) -> body)."""
    if isinstance(node, Group):
        return norm(node.body)
    if isinstance(node, BinaryOp):
        return BinaryOp(node.op, norm(node.left), norm(node.right), node.implicit)
    if isinstance(node, UnaryOp):
        return UnaryOp(node.op, norm(node.operand))
    if isinstance(node, Fraction):
        return Fraction(norm(node.numerator), norm(node.denominator))
    if isinstance(node, Power):
        return Power(norm(node.base), norm(node.exponent))
    if isinstance(node, Subscript):
        return Subscript(norm(node.base), norm(node.subscript))
    if isinstance(node, Root):
        return Root(norm(node.radicand),
                    norm(node.index) if node.index is not None else None)
    if isinstance(node, Function):
        return Function(node.name, norm(node.arg),
                        norm(node.base) if node.base is not None else None)
    if isinstance(node, Relation):
        return Relation(node.op, norm(node.left), norm(node.right))
    if isinstance(node, Abs):
        return Abs(norm(node.body))
    if isinstance(node, BigOp):
        return BigOp(node.kind,
                     norm(node.lower) if node.lower is not None else None,
                     norm(node.upper) if node.upper is not None else None,
                     norm(node.body) if node.body is not None else None)
    if isinstance(node, Matrix):
        return Matrix([[norm(c) for c in row] for row in node.rows], node.kind)
    if isinstance(node, Line):
        return Line([norm(n) for n in node.nodes])
    if isinstance(node, Derivation):
        return Derivation([norm(l) for l in node.lines])
    return node


# -- sympy conversion (test-only) ----------------------------------------------

def to_sympy(node):
    import sympy

    if isinstance(node, Number):
        if node.value == "inf":
            return sympy.oo
        if "." in node.value:
            return sympy.Float(node.value)
        return sympy.Integer(node.value)
    if isinstance(node, Variable):
        return sympy.Symbol(node.name)
    if isinstance(node, Name):
        return sympy.Symbol(node.value)
    if isinstance(node, Greek):
        if node.name == "pi":
            return sympy.pi
        return sympy.Symbol(node.name)
    if isinstance(node, Group):
        return to_sympy(node.body)
    if isinstance(node, UnaryOp):
        return -to_sympy(node.operand)
    if isinstance(node, BinaryOp):
        a, b = to_sympy(node.left), to_sympy(node.right)
        return {"+": a + b, "-": a - b, "*": a * b, "/": a / b}[node.op]
    if isinstance(node, Fraction):
        return to_sympy(node.numerator) / to_sympy(node.denominator)
    if isinstance(node, Power):
        return to_sympy(node.base) ** to_sympy(node.exponent)
    if isinstance(node, Root):
        if node.index is None:
            return sympy.sqrt(to_sympy(node.radicand))
        return to_sympy(node.radicand) ** (1 / to_sympy(node.index))
    if isinstance(node, Function):
        inner = to_sympy(node.arg)
        fn = {"sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
              "exp": sympy.exp, "ln": sympy.ln}.get(node.name)
        if fn is not None:
            return fn(inner)
        if node.name == "log":
            return sympy.log(inner, to_sympy(node.base) if node.base else 10)
        return None
    return None


SAMPLE_VALUES = {"x": 0.7, "y": 1.3, "a": 1.9, "b": 2.1, "c": 3.7, "n": 2}


class TestCorpus:
    @pytest.mark.parametrize("entry", FORMULAS, ids=lambda e: e["id"])
    def test_all_forms_parse(self, entry):
        customs = entry.get("custom", ["cost"])
        result = parse_math(entry["latex"], "latex", custom_names=customs)
        assert result.ast.lines

    @pytest.mark.parametrize("entry", FORMULAS, ids=lambda e: e["id"])
    def test_forms_agree(self, entry):
        customs = entry.get("custom", ["cost"])
        reference = norm(parse_math(entry["latex"], "latex", customs).ast)
        for field in ("plain", "unicode"):
            src = entry.get(field)
            if not src:
                continue
            other = norm(parse_math(src, field, customs).ast)
            assert other == reference, f"{entry['id']}: {field} != latex"

    @pytest.mark.parametrize("entry", FORMULAS, ids=lambda e: e["id"])
    def test_numeric_equivalence(self, entry):
        """LaTeX and plain forms evaluate identically (where checkable)."""
        if "numeric" not in entry:
            return
        customs = entry.get("custom", ["cost"])
        subs = {v: SAMPLE_VALUES.get(v, 1.5) for v in entry["numeric"]}

        values = []
        for field in ("latex", "plain"):
            src = entry.get(field)
            if not src:
                continue
            ast = parse_math(src, field, customs).ast
            expr = to_sympy(ast.lines[0].nodes[0])
            if expr is None:
                return  # not convertible; structural test covers it
            values.append(float(expr.evalf(subs=subs)))
        if len(values) == 2:
            assert values[0] == pytest.approx(values[1], rel=1e-9, abs=1e-9)


def test_corpus_size():
    assert len(FORMULAS) >= 40
