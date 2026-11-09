"""AST node types for the math pipeline (blueprint section 5.4).

The parser is order-preserving: it never simplifies, expands or reorders.
`3x + x^2` is dictated exactly as written.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class Node:
    """Base class; provides generic traversal helpers."""

    def children(self) -> list["Node"]:
        return []


@dataclass
class Number(Node):
    value: str                      # canonical: "3", "3.14", "1000", "inf"

    def children(self):
        return []


@dataclass
class Variable(Node):
    name: str                       # single letter: "x", "A"

    def children(self):
        return []


@dataclass
class Name(Node):
    """Multi-letter custom name (function or variable), e.g. `cost`, `Var`."""

    value: str

    def children(self):
        return []


@dataclass
class Greek(Node):
    name: str                       # canonical greek name: "pi", "delta"
    upper: bool = False

    def children(self):
        return []


@dataclass
class BinaryOp(Node):
    op: str                         # "+", "-", "*", "/", "=", "<", "<=", ...
    left: Node
    right: Node
    implicit: bool = False          # True for juxtaposition (3x, ab)

    def children(self):
        return [self.left, self.right]


@dataclass
class UnaryOp(Node):
    op: str                         # "-", "+"
    operand: Node

    def children(self):
        return [self.operand]


@dataclass
class Fraction(Node):
    numerator: Node
    denominator: Node

    def children(self):
        return [self.numerator, self.denominator]


@dataclass
class Power(Node):
    base: Node
    exponent: Node

    def children(self):
        return [self.base, self.exponent]


@dataclass
class Subscript(Node):
    base: Node
    subscript: Node

    def children(self):
        return [self.base, self.subscript]


@dataclass
class Root(Node):
    radicand: Node
    index: Node | None = None       # None -> square root

    def children(self):
        return [self.radicand] + ([self.index] if self.index else [])


@dataclass
class Function(Node):
    name: str                       # canonical: "sin", "log", ...
    arg: Node
    base: Node | None = None        # log to the base b

    def children(self):
        return [self.arg] + ([self.base] if self.base else [])


@dataclass
class Group(Node):
    bracket: str                    # "(", "[", "{"
    body: Node

    def children(self):
        return [self.body]


@dataclass
class Relation(Node):
    op: str                         # "=", "<", "<=", ">=", "!=", "~=", "to"
    left: Node
    right: Node

    def children(self):
        return [self.left, self.right]


@dataclass
class BigOp(Node):
    kind: str                       # "int", "sum", "prod", "lim"
    lower: Node | None = None
    upper: Node | None = None
    body: Node | None = None

    def children(self):
        return [n for n in (self.lower, self.upper, self.body) if n is not None]


@dataclass
class Matrix(Node):
    rows: list[list[Node]]
    kind: str = "pmatrix"           # pmatrix|bmatrix|vmatrix|matrix|cases

    def children(self):
        return [cell for row in self.rows for cell in row]


@dataclass
class Abs(Node):
    body: Node

    def children(self):
        return [self.body]


@dataclass
class Line(Node):
    """One line of a (possibly multi-line) derivation."""

    nodes: list[Node] = field(default_factory=list)

    def children(self):
        return list(self.nodes)


@dataclass
class Derivation(Node):
    """A whole math segment: one or more Lines (align environments etc.)."""

    lines: list[Line] = field(default_factory=list)

    def children(self):
        return list(self.lines)


class MathParseError(ValueError):
    """Raised when math input cannot be parsed; callers fall back to
    symbol-by-symbol reading of the raw text."""


# ---------------------------------------------------------------------------
# traversal helpers

def walk(node: Node):
    yield node
    for child in node.children():
        yield from walk(child)


def token_count(node: Node) -> int:
    """Tokens for chunk sizing (number, variable, operator, bracket; 5.7)."""
    if isinstance(node, (Number, Variable, Name, Greek)):
        return 1
    if isinstance(node, (BinaryOp, Relation)):
        return 1 + sum(token_count(c) for c in node.children())
    if isinstance(node, (UnaryOp,)):
        return 1 + token_count(node.operand)
    if isinstance(node, Fraction):
        return 1 + token_count(node.numerator) + token_count(node.denominator)
    if isinstance(node, Power):
        return 1 + token_count(node.base) + token_count(node.exponent)
    if isinstance(node, Subscript):
        return 1 + token_count(node.base) + token_count(node.subscript)
    if isinstance(node, Root):
        return 1 + sum(token_count(c) for c in node.children())
    if isinstance(node, Function):
        return 1 + token_count(node.arg)
    if isinstance(node, Group):
        return 1 + token_count(node.body)
    if isinstance(node, Abs):
        return 1 + token_count(node.body)
    if isinstance(node, BigOp):
        return 2 + sum(token_count(c) for c in node.children())
    if isinstance(node, Matrix):
        cells = sum(token_count(c) for c in node.children())
        return 2 + len(node.rows) + cells
    if isinstance(node, Line):
        return sum(token_count(n) for n in node.nodes)
    if isinstance(node, Derivation):
        return sum(token_count(l) for l in node.lines)
    return 1


# ---------------------------------------------------------------------------
# LaTeX serialization (for the preview window)

_GREEK_LATEX = {
    "alpha": "\\alpha", "beta": "\\beta", "gamma": "\\gamma", "delta": "\\delta",
    "epsilon": "\\epsilon", "varepsilon": "\\varepsilon", "zeta": "\\zeta",
    "eta": "\\eta", "theta": "\\theta", "vartheta": "\\vartheta", "iota": "\\iota",
    "kappa": "\\kappa", "lambda": "\\lambda", "mu": "\\mu", "nu": "\\nu",
    "xi": "\\xi", "omicron": "o", "pi": "\\pi", "rho": "\\rho", "sigma": "\\sigma",
    "tau": "\\tau", "upsilon": "\\upsilon", "phi": "\\phi", "varphi": "\\varphi",
    "chi": "\\chi", "psi": "\\psi", "omega": "\\omega", "partial": "\\partial",
}

_REL_LATEX = {"=": "=", "<": "<", ">": ">", "<=": "\\le", ">=": "\\ge",
              "!=": "\\ne", "~=": "\\approx", "+-": "\\pm", "to": "\\to",
              "implies": "\\implies", "iff": "\\iff"}


def _need_braces(node: Node) -> bool:
    return not isinstance(node, (Number, Variable, Name, Greek, Group, Abs))


def to_latex(node: Node) -> str:
    if isinstance(node, Number):
        return node.value
    if isinstance(node, Variable):
        return node.name
    if isinstance(node, Name):
        return f"\\mathrm{{{node.value}}}"
    if isinstance(node, Greek):
        base = _GREEK_LATEX.get(node.name, node.name)
        if node.upper:
            return _GREEK_UPPER.get(node.name, base)
        return base
    if isinstance(node, BinaryOp):
        if node.implicit:
            return f"{_operand(node.left)}{_operand(node.right)}"
        op = {"+": "+", "-": "-", "*": "\\times", "/": "/", "+-": "\\pm",
              "to": "\\to"}.get(node.op, node.op)
        return f"{_operand(node.left)} {op} {_operand(node.right)}"
    if isinstance(node, UnaryOp):
        return f"{node.op}{_operand(node.operand)}"
    if isinstance(node, Fraction):
        return f"\\frac{{{to_latex(node.numerator)}}}{{{to_latex(node.denominator)}}}"
    if isinstance(node, Power):
        base = to_latex(node.base)
        if _need_braces(node.base):
            base = f"({base})"
        return f"{base}^{{{to_latex(node.exponent)}}}"
    if isinstance(node, Subscript):
        base = to_latex(node.base)
        if _need_braces(node.base):
            base = f"({base})"
        return f"{base}_{{{to_latex(node.subscript)}}}"
    if isinstance(node, Root):
        if node.index is not None:
            return f"\\sqrt[{to_latex(node.index)}]{{{to_latex(node.radicand)}}}"
        return f"\\sqrt{{{to_latex(node.radicand)}}}"
    if isinstance(node, Function):
        name = node.name if node.name.isalpha() else node.name
        if node.base is not None:
            return f"\\log_{{{to_latex(node.base)}}} {to_latex(node.arg)}"
        return f"\\{name} {to_latex(node.arg)}"
    if isinstance(node, Group):
        inner = to_latex(node.body)
        if node.bracket == "(":
            return f"({inner})"
        if node.bracket == "[":
            return f"[{inner}]"
        return f"{{{inner}}}"
    if isinstance(node, Relation):
        op = _REL_LATEX.get(node.op, node.op)
        return f"{to_latex(node.left)} {op} {to_latex(node.right)}"
    if isinstance(node, BigOp):
        sym = {"int": "\\int", "sum": "\\sum", "prod": "\\prod", "lim": "\\lim"}[node.kind]
        out = sym
        if node.kind != "lim":
            if node.lower is not None:
                out += f"_{{{to_latex(node.lower)}}}"
            if node.upper is not None:
                out += f"^{{{to_latex(node.upper)}}}"
        else:
            if node.lower is not None:
                out += f"_{{{to_latex(node.lower)}}}"
        if node.body is not None:
            out += f" {to_latex(node.body)}"
        return out
    if isinstance(node, Matrix):
        env = node.kind if node.kind in ("pmatrix", "bmatrix", "vmatrix", "matrix", "cases") else "pmatrix"
        body = " \\\\ ".join(" & ".join(to_latex(c) for c in row) for row in node.rows)
        return f"\\begin{{{env}}} {body} \\end{{{env}}}"
    if isinstance(node, Abs):
        return f"\\left|{to_latex(node.body)}\\right|"
    if isinstance(node, Line):
        return " ".join(to_latex(n) for n in node.nodes)
    if isinstance(node, Derivation):
        body = " \\\\\n".join(to_latex(l) for l in node.lines)
        return f"\\begin{{align}} {body} \\end{{align}}"
    return "?"


def _operand(node: Node) -> str:
    s = to_latex(node)
    if isinstance(node, (BinaryOp, Relation)):
        return f"({s})"
    return s


_GREEK_UPPER = {
    "gamma": "\\Gamma", "delta": "\\Delta", "theta": "\\Theta", "lambda": "\\Lambda",
    "sigma": "\\Sigma", "omega": "\\Omega", "phi": "\\Phi", "psi": "\\Psi",
    "pi": "\\Pi", "xi": "\\Xi", "upsilon": "\\Upsilon",
}
