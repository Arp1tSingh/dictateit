"""Math parser: LaTeX, plain-text and Unicode input -> one order-preserving AST.

Blueprint section 5.4. Never simplifies, expands or reorders.

Conventions implemented (agreed for v2):
- Relations END a chunk ("x equals") — decided with the user.
- Division is left-to-right with explicit operators: 1/2x = (1/2)x, a/b*c =
  (a/b)c. Ambiguous cases are flagged on the ParseResult, never silently guessed.
- Implicit multiplication binds tighter than explicit * and / (2x/3 = (2x)/3).
- Unary minus binds tighter than explicit multiplication, looser than powers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import normalize_math
from .ast_nodes import (
    Abs, BigOp, BinaryOp, Derivation, Fraction, Function, Group, Greek, Line,
    MathParseError, Matrix, Name, Number, Power, Relation, Root, Subscript,
    UnaryOp, Variable,
)

# ---------------------------------------------------------------------------
# tokens

NUM, LETTER, NAME, FUNC, GREEK, OP, REL, OPEN, CLOSE, BAR, CARROT, UNDER, \
    AMP, ROWBREAK, ENVCMD, ENDENV, TEXTARG, BIGOP, PARTIAL = (
        "num", "letter", "name", "func", "greek", "op", "rel", "open", "close",
        "bar", "carrot", "under", "amp", "rowbreak", "envcmd", "endenv",
        "textarg", "bigop", "partial")

OP_PREC = {"+": 2, "-": 2, "+-": 2, "*": 4, "/": 4}
PREC_REL, PREC_ADD, PREC_IMPL, PREC_EXPL, PREC_UNARY = 1, 2, 3, 4, 5

FUNCTIONS = {"sin", "cos", "tan", "sec", "csc", "cosec", "cot", "arcsin",
             "arccos", "arctan", "sinh", "cosh", "tanh", "exp", "log", "ln",
             "lg", "max", "min", "det", "sqrt"}

BIGOPS = {"int": "int", "sum": "sum", "prod": "prod", "lim": "lim"}

LATEX_OP_CMD = {"times": "*", "cdot": "*", "div": "/", "pm": "+-", "mp": "+-"}
LATEX_REL_CMD = {"le": "<=", "leq": "<=", "ge": ">=", "geq": ">=", "ne": "!=",
                 "neq": "!=", "approx": "~=", "to": "to", "rightarrow": "to",
                 "longrightarrow": "to", "implies": "implies", "iff": "iff"}

LATEX_GREEK = {name: name for name in normalize_math._GREEK_NAMES}
LATEX_GREEK.update({"Gamma": "Gamma", "Delta": "Delta", "Theta": "Theta",
                    "Lambda": "Lambda", "Sigma": "Sigma", "Omega": "Omega",
                    "Phi": "Phi", "Psi": "Psi", "Pi": "Pi", "Xi": "Xi",
                    "Upsilon": "Upsilon"})

MULTI_LINE_ENVS = {"align", "align*", "gather", "gather*", "eqnarray",
                   "eqnarray*", "alignat", "aligned"}
MATRIX_ENVS = {"pmatrix", "bmatrix", "vmatrix", "Vmatrix", "Bmatrix",
               "matrix", "smallmatrix", "cases"}

SKIP_COMMANDS = {"quad", "qquad", "displaystyle", "limits", "nolimits",
                 "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr"}


@dataclass
class ParseResult:
    ast: Derivation
    ambiguous: bool = False


@dataclass
class _Tok:
    kind: str
    value: str = ""
    pos: int = 0


# ---------------------------------------------------------------------------
# lexers

_LATEX_TOKEN = re.compile(
    r"\\\\"
    r"|\\[a-zA-Z]+"
    r"|\\[,;:!]"
    r"|\d+\.\d+|\d+"
    r"|[A-Za-z]"
    r"|[+\-*/=<>|&^_]"
    r"|[()\[\]{}]"
    r"|\s+"
)

_PLAIN_TOKEN = re.compile(
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"   # 1,000 / 1,234.56
    r"|\d+\.\d+|\d+"
    r"|[A-Za-z]+"
    r"|<=|>=|!=|~=|\+-|->"
    r"|[+\-*/=<>|,;.^_]"
    r"|[()\[\]{}]"
    r"|\s+"
)


def _lex_latex(src: str) -> list[_Tok]:
    src = normalize_math.normalize_latex(src)
    # ASCII-style relations typed inside math mode still read correctly
    src = src.replace("<=", "\\le").replace(">=", "\\ge").replace("!=", "\\ne")
    src = src.replace("~~", "\\approx")
    src = re.sub(r"\\left\s*([(\[{|])", r"\1", src)
    src = re.sub(r"\\right\s*([)\]}|])", r"\1", src)
    src = re.sub(r"\\left\s*\.\s*", "", src)
    src = re.sub(r"\\right\s*\.\s*", "", src)
    src = src.replace("\\{", "{").replace("\\}", "}").replace("\\|", "|")

    toks: list[_Tok] = []
    for m in _LATEX_TOKEN.finditer(src):
        raw = m.group()
        pos = m.start()
        if raw == "\\\\":
            toks.append(_Tok(ROWBREAK, "\\\\", pos))
            continue
        if raw.isspace():
            continue
        if raw.startswith("\\"):
            cmd = raw[1:]
            if raw in ("\\,", "\\;", "\\!", "\\:") or cmd in SKIP_COMMANDS:
                continue
            if cmd in LATEX_REL_CMD:
                toks.append(_Tok(REL, LATEX_REL_CMD[cmd], pos))
            elif cmd in LATEX_OP_CMD:
                toks.append(_Tok(OP, LATEX_OP_CMD[cmd], pos))
            elif cmd in FUNCTIONS:
                toks.append(_Tok(FUNC, cmd, pos))
            elif cmd in BIGOPS:
                toks.append(_Tok(BIGOP, BIGOPS[cmd], pos))
            elif cmd in LATEX_GREEK:
                toks.append(_Tok(GREEK, LATEX_GREEK[cmd], pos))
            elif cmd == "infty":
                toks.append(_Tok(NUM, "inf", pos))
            elif cmd == "frac":
                toks.append(_Tok("frac", "frac", pos))
            elif cmd == "partial":
                toks.append(_Tok(PARTIAL, "partial", pos))
            elif cmd in ("text", "mathrm", "mathbf", "mathit", "operatorname"):
                toks.append(_Tok(TEXTARG, cmd, pos))
            elif cmd == "begin":
                toks.append(_Tok(ENVCMD, "begin", pos))
            elif cmd == "end":
                toks.append(_Tok(ENDENV, "end", pos))
            else:
                raise MathParseError(f"unsupported LaTeX command \\{cmd} at {pos}")
        elif raw in "+-*":
            toks.append(_Tok(OP, raw, pos))
        elif raw == "/":
            toks.append(_Tok(OP, "/", pos))
        elif raw in "=<>":
            toks.append(_Tok(REL, raw, pos))
        elif raw in "([":
            toks.append(_Tok(OPEN, raw, pos))
        elif raw in ")]":
            toks.append(_Tok(CLOSE, raw, pos))
        elif raw == "{":
            toks.append(_Tok(OPEN, "{", pos))
        elif raw == "}":
            toks.append(_Tok(CLOSE, "}", pos))
        elif raw == "|":
            toks.append(_Tok(BAR, "|", pos))
        elif raw == "^":
            toks.append(_Tok(CARROT, raw, pos))
        elif raw == "_":
            toks.append(_Tok(UNDER, raw, pos))
        elif raw == "&":
            toks.append(_Tok(AMP, raw, pos))
        elif raw.isalpha():
            toks.append(_Tok(LETTER, raw, pos))
        else:
            toks.append(_Tok(NUM, raw, pos))
    return toks


def _lex_plain(src: str) -> list[_Tok]:
    src = normalize_math.normalize_plain(src)
    toks: list[_Tok] = []
    for m in _PLAIN_TOKEN.finditer(src):
        raw = m.group()
        pos = m.start()
        if raw.isspace():
            if "\n" in raw:
                toks.append(_Tok(ROWBREAK, "\\n", pos))
            continue
        if raw[0].isdigit():
            toks.append(_Tok(NUM, raw.replace(",", ""), pos))
        elif raw.isalpha():
            if raw in FUNCTIONS:
                toks.append(_Tok(FUNC, raw, pos))
            elif raw.lower() in normalize_math._GREEK_NAMES:
                toks.append(_Tok(GREEK, raw, pos))  # case kept for upper flag
            elif raw.lower() == "to":
                toks.append(_Tok(REL, "to", pos))
            elif raw.lower() in ("inf", "infinity"):
                toks.append(_Tok(NUM, "inf", pos))
            else:
                toks.append(_Tok(LETTER, raw, pos))
        elif raw in ("+", "-", "*", "/"):
            toks.append(_Tok(OP, raw, pos))
        elif raw == "->":
            toks.append(_Tok(REL, "to", pos))
        elif raw == "^":
            toks.append(_Tok(CARROT, raw, pos))
        elif raw == "_":
            toks.append(_Tok(UNDER, raw, pos))
        elif raw in ("<=", ">=", "!=", "~="):
            toks.append(_Tok(REL, raw, pos))
        elif raw == "+-":
            toks.append(_Tok(OP, "+-", pos))
        elif raw in "=<>":
            toks.append(_Tok(REL, raw, pos))
        elif raw in "([":
            toks.append(_Tok(OPEN, raw, pos))
        elif raw in ")]":
            toks.append(_Tok(CLOSE, raw, pos))
        elif raw == "{":
            toks.append(_Tok(OPEN, "{", pos))
        elif raw == "}":
            toks.append(_Tok(CLOSE, "}", pos))
        elif raw == "|":
            toks.append(_Tok(BAR, "|", pos))
        elif raw in ",;":
            toks.append(_Tok(AMP, raw, pos))
        else:
            toks.append(_Tok(OP, raw, pos))
    return toks


# ---------------------------------------------------------------------------
# parser core (Pratt)

_VALUE_START = {NUM, LETTER, NAME, FUNC, GREEK, OPEN, BAR, TEXTARG, PARTIAL,
                BIGOP, ENVCMD, "frac"}


class _Core:
    def __init__(self, toks: list[_Tok], custom_names: list[str] | None = None):
        self.toks = toks
        self.i = 0
        self.custom = set(custom_names or [])
        self.ambiguous = False

    def peek(self, ahead: int = 0) -> _Tok | None:
        j = self.i + ahead
        return self.toks[j] if j < len(self.toks) else None

    def advance(self) -> _Tok | None:
        t = self.peek()
        if t is not None:
            self.i += 1
        return t

    def expect_close(self, opener: str) -> None:
        t = self.peek()
        want = {"(": ")", "[": "]", "{": "}"}[opener]
        if t is None or t.kind != CLOSE or t.value != want:
            raise MathParseError(f"expected {want!r} to close {opener!r}")
        self.advance()

    # -- entry --------------------------------------------------------------
    def parse_document(self) -> Derivation:
        t = self.peek()
        if t is not None and t.kind == ENVCMD:
            env = self._read_env_name()
            if env in MATRIX_ENVS:
                mat = self._parse_matrix_env(env)
                if self.peek() is not None:
                    raise MathParseError(
                        f"unexpected token {self.peek().value!r} after environment")
                return Derivation([Line([mat])])
            if env in MULTI_LINE_ENVS:
                lines = self._parse_align_body()
                if self.peek() is not None:
                    raise MathParseError(
                        f"unexpected token {self.peek().value!r} after environment")
                return Derivation(lines)
            raise MathParseError(f"unsupported environment {env!r}")

        has_env = any(tk.kind == ENVCMD for tk in self.toks)
        if has_env:
            # a matrix/align environment used as a value (A = \begin{pmatrix}...)
            node = self.parse_expression(0)
            if self.peek() is not None:
                raise MathParseError(
                    f"unexpected token {self.peek().value!r} after expression")
            return Derivation([Line([node])])

        lines: list[Line] = []
        rows: list[list[_Tok]] = [[]]
        for tok in self.toks[self.i:]:
            if tok.kind == ROWBREAK:
                rows.append([])
            else:
                rows[-1].append(tok)
        for row in rows:
            row_toks = [tk for tk in row if tk.kind != AMP]
            if not row_toks:
                continue
            sub = _Core(row_toks, self.custom)
            node = sub.parse_expression(0)
            if sub.ambiguous:
                self.ambiguous = True
            if sub.peek() is not None:
                raise MathParseError(
                    f"unexpected token {sub.peek().value!r} after expression")
            lines.append(Line([node]))
        if not lines:
            raise MathParseError("empty math input")
        return Derivation(lines)

    def _read_env_name(self) -> str:
        self.advance()  # \begin / \end
        t = self.peek()
        if t is None or t.kind != OPEN or t.value != "{":
            raise MathParseError("expected { after \\begin/\\end")
        self.advance()
        letters: list[str] = []
        while (t := self.peek()) is not None and t.kind in (LETTER, NUM):
            letters.append(t.value)
            self.advance()
        if t is None or t.kind != CLOSE:
            raise MathParseError("expected } after environment name")
        self.advance()
        return "".join(letters)

    def _parse_align_body(self) -> list[Line]:
        """Parse rows of align/gather: split on ROWBREAK, cells on AMP."""
        lines: list[Line] = []
        row: list[_Tok] = []

        def flush_row(row_toks: list[_Tok]) -> None:
            cells: list[list[_Tok]] = [[]]
            for tok in row_toks:
                if tok.kind == AMP:
                    cells.append([])
                else:
                    cells[-1].append(tok)
            if all(not c for c in cells):
                return
            parsed: list = []
            for idx, cell in enumerate(cells):
                if not cell:
                    continue
                # alignment "&= 11": the relation binds the previous cell
                if idx > 0 and cell[0].kind == REL:
                    op = cell[0].value
                    sub = _Core(cell[1:], self.custom)
                    right = sub.parse_expression(0)
                    if sub.peek() is not None:
                        raise MathParseError("unexpected tokens after aligned relation")
                    if parsed:
                        parsed[-1] = Relation(op, parsed[-1], right)
                    else:
                        parsed.append(right)
                else:
                    sub = _Core(cell, self.custom)
                    node = sub.parse_expression(0)
                    if sub.ambiguous:
                        self.ambiguous = True
                    if sub.peek() is not None:
                        raise MathParseError(
                            f"unexpected token {sub.peek().value!r} after expression")
                    parsed.append(node)
            if parsed:
                lines.append(Line(parsed))

        while (t := self.peek()) is not None:
            if t.kind == ENDENV:
                name = self._read_env_name()
                if name in MULTI_LINE_ENVS:
                    break
                continue
            if t.kind == ROWBREAK:
                flush_row(row)
                row = []
                self.advance()
            else:
                row.append(t)
                self.advance()
        flush_row(row)
        if not lines:
            raise MathParseError("empty align environment")
        return lines

    def _parse_matrix_env(self, env: str) -> Matrix:
        rows: list[list] = [[]]
        while (t := self.peek()) is not None:
            if t.kind == ENDENV:
                self._read_env_name()
                break
            if t.kind == ROWBREAK:
                self.advance()
                rows.append([])
            elif t.kind == AMP:
                self.advance()
            else:
                rows[-1].append(self.parse_expression(0))
        rows = [r for r in rows if r]
        if not rows:
            raise MathParseError(f"empty {env} environment")
        kind = {"vmatrix": "vmatrix", "Vmatrix": "vmatrix", "bmatrix": "bmatrix",
                "Bmatrix": "bmatrix", "smallmatrix": "matrix"}.get(env, env)
        return Matrix(rows=rows, kind=kind)

    # -- expressions ----------------------------------------------------------
    def parse_expression(self, min_prec: int):
        left = self.parse_prefix()
        while True:
            t = self.peek()
            if t is None:
                break
            if t.kind == OP:
                prec = OP_PREC.get(t.value)
                if prec is None or prec < min_prec:
                    break
                self.advance()
                right = self.parse_expression(prec + 1)
                if t.value == "/":
                    left = self._divide(left, right)
                else:
                    left = BinaryOp(t.value, left, right, implicit=False)
            elif t.kind == REL:
                if PREC_REL < min_prec:
                    break
                self.advance()
                right = self.parse_expression(PREC_REL + 1)
                left = Relation(t.value, left, right)
            elif t.kind in (ROWBREAK, AMP, CLOSE, ENDENV):
                break
            elif self._starts_value(t):
                if PREC_IMPL < min_prec:
                    break
                # right operand of implicit multiplication only takes
                # postfix-level factors, so 2x/3 reads (2x)/3, not 2x/3 mis-split
                right = self.parse_expression(PREC_EXPL + 1)
                left = BinaryOp("*", left, right, implicit=True)
            else:
                break
        return left

    def _starts_value(self, t: _Tok) -> bool:
        if t.kind == BAR:
            # | starts a value only when a matching close exists later on
            return any(tk.kind == BAR for tk in self.toks[self.i + 1:])
        return t.kind in _VALUE_START

    def _divide(self, left, right):
        # ambiguity: division followed by more multiplication (1/2x, a/b*c)
        t = self.peek()
        if t is not None and (self._starts_value(t) or (t.kind == OP and t.value == "*")):
            self.ambiguous = True
        return Fraction(left, right)

    def parse_prefix(self):
        t = self.peek()
        if t is None:
            raise MathParseError("unexpected end of math input")

        if t.kind == NUM:
            self.advance()
            node = Number(t.value)
        elif t.kind == LETTER:
            self.advance()
            node = Variable(t.value)
        elif t.kind == NAME:
            self.advance()
            node = Name(t.value)
        elif t.kind == GREEK:
            self.advance()
            node = Greek(t.value.lower(), upper=t.value[0].isupper())
        elif t.kind == PARTIAL:
            self.advance()
            node = Greek("partial")
        elif t.kind == TEXTARG:
            node = self._parse_text_arg()
        elif t.kind == "frac":
            self.advance()
            num = self._postfix_arg_node()
            den = self._postfix_arg_node()
            node = Fraction(num, den)
        elif t.kind == BIGOP:
            node = self._parse_bigop()
        elif t.kind == FUNC:
            node = self._parse_function()
        elif t.kind == ENVCMD:
            env = self._read_env_name()
            if env in MATRIX_ENVS:
                node = self._parse_matrix_env(env)
            elif env in MULTI_LINE_ENVS:
                lines = self._parse_align_body()
                node = Line([Derivation(lines)])
            else:
                raise MathParseError(f"unsupported environment {env!r}")
        elif t.kind == OPEN:
            self.advance()
            node = self._parse_group_body(t.value)
        elif t.kind == BAR:
            self.advance()
            body = self.parse_expression(0)
            close = self.peek()
            if close is None or close.kind != BAR:
                raise MathParseError("unmatched | in modulus")
            self.advance()
            node = Abs(body)
        elif t.kind == OP and t.value in ("-", "+"):
            self.advance()
            operand = self.parse_expression(PREC_UNARY)
            node = UnaryOp("-", operand) if t.value == "-" else operand
        else:
            raise MathParseError(f"unexpected token {t.value!r}")

        return self._postfix(node)

    def _parse_group_body(self, opener: str):
        """Group body; comma-separated cells become a Line (f(a, b))."""
        cells = [self.parse_expression(0)]
        while self.peek() is not None and self.peek().kind == AMP:
            self.advance()
            cells.append(self.parse_expression(0))
        self.expect_close(opener)
        if len(cells) == 1:
            body = cells[0]
        else:
            body = Line(cells)
        if opener == "{":
            return body          # braces group invisibly
        return Group(opener, body)

    def _parse_text_arg(self) -> Name:
        self.advance()  # \text command
        t = self.peek()
        if t is None or t.kind != OPEN or t.value != "{":
            raise MathParseError("expected { after \\text")
        self.advance()
        words: list[_Tok] = []
        while (t := self.peek()) is not None and t.kind != CLOSE:
            words.append(t)
            self.advance()
        if t is None:
            raise MathParseError("unterminated \\text argument")
        self.advance()
        text = "".join(tk.value for tk in words if tk.kind != ROWBREAK).strip()
        return Name(text)

    def _parse_bigop(self) -> BigOp:
        t = self.advance()  # bigop token
        kind = t.value
        lower = upper = None
        if self.peek() is not None and self.peek().kind == UNDER:
            self.advance()
            lower = self._postfix_arg_node()
        if self.peek() is not None and self.peek().kind == CARROT:
            self.advance()
            upper = self._postfix_arg_node()
        body = None
        if self.peek() is not None and self._starts_value(self.peek()):
            body = self.parse_expression(PREC_IMPL)
        return BigOp(kind, lower, upper, body)

    def _parse_function(self):
        t = self.advance()  # FUNC token
        name = t.value
        exp = None
        base = None
        if self.peek() is not None and self.peek().kind == CARROT:
            self.advance()
            exp = self._postfix_arg_node()
        if self.peek() is not None and self.peek().kind == UNDER:
            self.advance()
            base = self._postfix_arg_node()

        if name == "sqrt":
            if self.peek() is not None and self.peek().kind == OPEN and self.peek().value == "[":
                self.advance()
                index = self.parse_expression(0)
                close = self.peek()
                if close is None or close.kind != CLOSE or close.value != "]":
                    raise MathParseError("expected ] to close root index")
                self.advance()
                radicand = self._postfix_arg_node()
                node = Root(radicand, index)
            else:
                radicand = self._postfix_arg_node()
                node = Root(radicand)
        else:
            arg = self.parse_expression(PREC_IMPL)
            node = Function(name, arg, base=base)
        if exp is not None:
            node = Power(node, exp)
        return node

    def _postfix_arg_node(self):
        t = self.peek()
        if t is None:
            raise MathParseError("expected an argument")
        if t.kind == OPEN and t.value == "{":
            self.advance()
            node = self.parse_expression(0)
            self.expect_close("{")
            return node
        if t.kind == NUM:
            self.advance()
            return Number(t.value)
        if t.kind == LETTER:
            self.advance()
            return Variable(t.value)
        if t.kind == NAME:
            self.advance()
            return Name(t.value)
        if t.kind == GREEK:
            self.advance()
            return Greek(t.value.lower(), upper=t.value[0].isupper())
        if t.kind == FUNC:
            return self._parse_function()
        if t.kind == BIGOP:
            return self._parse_bigop()
        if t.kind == OP and t.value == "-":
            self.advance()
            return UnaryOp("-", self._postfix_arg_node())
        if t.kind == OPEN:
            self.advance()
            return self._parse_group_body(t.value)
        raise MathParseError(f"unexpected token {t.value!r} in argument")

    def _postfix(self, node):
        while self.peek() is not None and self.peek().kind in (CARROT, UNDER):
            t = self.advance()
            arg = self._postfix_arg_node()
            if t.kind == CARROT:
                node = Power(node, arg)
            else:
                node = Subscript(node, arg)
        return node


# ---------------------------------------------------------------------------
# public API

def parse_math(source: str, fmt: str, custom_names: list[str] | None = None) -> ParseResult:
    """Parse a math segment. fmt: 'latex' | 'plain' | 'unicode'.

    Raises MathParseError when the input cannot be parsed; callers fall back
    to symbol-by-symbol reading of the raw text.
    """
    if fmt == "latex":
        toks = _lex_latex(source)
    else:
        toks = _lex_plain(source)
        toks = _split_letter_runs(toks, custom_names or [])

    core = _Core(toks, custom_names)
    ast = core.parse_document()
    return ParseResult(ast, ambiguous=core.ambiguous)


def _split_letter_runs(toks: list[_Tok], custom_names: list[str]) -> list[_Tok]:
    """Plain-text letter runs become variables or custom names.

    'ab' -> a·b (implicit product) unless listed in custom_names ('cost').
    """
    out: list[_Tok] = []
    customs = sorted(set(custom_names), key=len, reverse=True)
    for tok in toks:
        if tok.kind != LETTER:
            out.append(tok)
            continue
        remaining = tok.value
        buffer = ""
        while remaining:
            match = next((c for c in customs if remaining.startswith(c)), None)
            if match:
                if buffer:
                    out.extend(_letter_tokens(buffer, tok.pos))
                    buffer = ""
                out.append(_Tok(NAME, match, tok.pos))
                remaining = remaining[len(match):]
            else:
                buffer += remaining[0]
                remaining = remaining[1:]
        if buffer:
            out.extend(_letter_tokens(buffer, tok.pos))
    return out


def _letter_tokens(letters: str, pos: int) -> list[_Tok]:
    return [_Tok(LETTER, ch, pos) for ch in letters]
