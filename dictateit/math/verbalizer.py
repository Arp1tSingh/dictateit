"""Verbalizer: AST -> natural / explicit / symbol-by-symbol speech.

Blueprint sections 5.5 and 5.6. All wording comes from the locale pack
(speech_data/*.json); new notation is added by editing data, not code.

Pass 1 (natural) is compact: "squared" where unambiguous, structure words
kept but spoken fluidly.
Pass 2 (explicit) makes every structural boundary a comma-separated item:
"fraction, numerator, a plus b, over, denominator, c, end fraction".
Pass 3 (symbols) is one word per item, requested on demand.

Decisions implemented (v2 review): compound exponents use "end power" in
both passes; the natural pass uses spaces rather than the blueprint's
stylistic commas; pauses in the explicit pass are marked per word.
"""

from __future__ import annotations

from .ast_nodes import (
    Abs, BigOp, BinaryOp, Derivation, Fraction, Function, Group, Greek, Line,
    Matrix, Number, Power, Relation, Root, Subscript, UnaryOp, Variable, Name,
    walk,
)

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
         "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def number_words(n: int) -> str:
    """0 .. 999,999,999,999 in English words."""
    if n < 0:
        return "minus " + number_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + number_words(n % 100) if n % 100 else "")
    for value, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand")):
        if n >= value:
            return number_words(n // value) + f" {name}" + (
                " " + number_words(n % value) if n % value else "")
    return str(n)


class Verbalizer:
    def __init__(self, pack: dict, letters: dict, settings=None):
        self.math = pack.get("math", {})
        self.letters = letters
        self.settings = settings
        self._segment_letters: set[str] = set()  # for case announcement

    # -- context ----------------------------------------------------------
    def set_case_context(self, node) -> None:
        """Collect the letters used in the segment, for announce_case."""
        mode = "when_ambiguous"
        if self.settings is not None:
            mode = self.settings.get("math.announce_case", "when_ambiguous")
        self._both_cases: set[str] = set()
        self._segment_letters = set()
        if mode != "when_ambiguous":
            return
        lower: set[str] = set()
        upper: set[str] = set()
        for n in walk(node):
            if isinstance(n, Variable) and n.name.isalpha():
                if n.name[0].isupper():
                    upper.add(n.name[0].lower())
                else:
                    lower.add(n.name[0].lower())
        self._both_cases = lower & upper
        self._segment_letters = lower | upper

    # -- public API ----------------------------------------------------------
    def verbalize(self, node, mode: str) -> str:
        """mode: 'natural' | 'explicit'. Returns the spoken string."""
        words = self.words(node, mode)
        if mode == "explicit":
            return ", ".join(w for w, _ in words)
        return " ".join(w for w, _ in words)

    def symbols(self, node) -> list[str]:
        return [w for w, _ in self.words(node, "symbols")]

    def words(self, node, mode: str) -> list[tuple[str, bool]]:
        """Flat list of (word, pause_before) for the given pass.

        In 'symbols' mode every word gets pause_before=True.
        """
        out: list[tuple[str, bool]] = []
        self._emit(node, mode, out, top=True)
        return out

    # -- emission ----------------------------------------------------------
    def _w(self, out, word: str, pause: bool = True) -> None:
        out.append((word, pause))

    def _emit(self, node, mode, out, top: bool = False) -> None:
        sym = mode == "symbols"

        if isinstance(node, Number):
            self._emit_number(node, mode, out)
        elif isinstance(node, Variable):
            self._emit_variable(node, mode, out)
        elif isinstance(node, Name):
            self._w(out, node.value, pause=sym)
        elif isinstance(node, Greek):
            self._emit_greek(node, mode, out)
        elif isinstance(node, UnaryOp):
            word = self._op_word("unary_minus" if node.op == "-" else node.op)
            self._w(out, word, pause=sym or top)
            self._emit(node.operand, mode, out)
        elif isinstance(node, BinaryOp):
            self._emit_binary(node, mode, out, top)
        elif isinstance(node, Fraction):
            self._emit_fraction(node, mode, out)
        elif isinstance(node, Power):
            self._emit_power(node, mode, out)
        elif isinstance(node, Subscript):
            self._emit_subscript(node, mode, out)
        elif isinstance(node, Root):
            self._emit_root(node, mode, out)
        elif isinstance(node, Function):
            self._emit_function(node, mode, out)
        elif isinstance(node, Group):
            self._emit_group(node, mode, out)
        elif isinstance(node, Relation):
            self._emit_binary_relation(node, mode, out, top)
        elif isinstance(node, BigOp):
            self._emit_bigop(node, mode, out)
        elif isinstance(node, Matrix):
            self._emit_matrix(node, mode, out)
        elif isinstance(node, Abs):
            self._w(out, self.math["brackets"]["mod_open"])
            self._emit(node.body, mode, out)
            self._w(out, self.math["brackets"]["mod_close"])
        elif isinstance(node, Line):
            for child in node.nodes:
                self._emit(child, mode, out)
        elif isinstance(node, Derivation):
            for line in node.lines:
                self._emit(line, mode, out)

    # -- numbers -----------------------------------------------------------
    def _emit_number(self, node: Number, mode, out) -> None:
        value = node.value
        style = "words"
        if self.settings is not None:
            style = self.settings.get("math.number_style", "words")
        if value == "inf":
            self._w(out, self.math["calculus"]["infinity"])
            return
        if "." in value:
            whole, _, frac = value.partition(".")
            words = number_words(int(whole)) if whole else "zero"
            point = self.math["misc"]["point"]
            digits = " ".join(_ONES[int(d)] for d in frac)
            self._w(out, f"{words} {point} {digits}", pause=(mode == "symbols"))
        elif style == "digits" and len(value) > 1:
            digits = " ".join(_ONES[int(d)] for d in value)
            self._w(out, digits, pause=(mode == "symbols"))
        else:
            self._w(out, number_words(int(value)), pause=(mode == "symbols"))

    # -- variables and letters ------------------------------------------------
    def _emit_variable(self, node: Variable, mode, out) -> None:
        word = self.letters.get(node.name.lower(), node.name.lower())
        if self._announce_capital(node.name):
            self._w(out, self.math["misc"]["capital"], pause=(mode == "symbols"))
        self._w(out, word, pause=(mode == "symbols"))

    def _announce_capital(self, name: str) -> bool:
        mode = "when_ambiguous"
        if self.settings is not None:
            mode = self.settings.get("math.announce_case", "when_ambiguous")
        if mode == "always":
            return name[0].isupper()
        if mode == "never":
            return False
        # both cases of this letter appear in the segment -> announce
        return name[0].isupper() and name[0].lower() in getattr(self, "_both_cases", set())

    def _emit_greek(self, node: Greek, mode, out) -> None:
        name = node.name.lower()
        if name == "partial":
            self._w(out, self.math["calculus"]["partial"], pause=(mode == "symbols"))
            return
        word = self.math["greek"].get(name, name)
        if node.upper:
            self._w(out, self.math["misc"]["capital"], pause=(mode == "symbols"))
        self._w(out, word, pause=(mode == "symbols"))

    # -- operators -------------------------------------------------------------
    def _op_word(self, op: str) -> str:
        return self.math["ops"].get(op, op)

    def _emit_binary(self, node: BinaryOp, mode, out, top: bool) -> None:
        sym = mode == "symbols"
        self._emit(node.left, mode, out)
        if node.implicit:
            # juxtaposition: no word, just the tiny gap (3x -> "three x")
            self._emit(node.right, mode, out)
            return
        word = self._op_word(node.op)
        self._w(out, word, pause=sym or top)
        self._emit(node.right, mode, out)

    def _emit_binary_relation(self, node: Relation, mode, out, top: bool) -> None:
        sym = mode == "symbols"
        self._emit(node.left, mode, out)
        word = self._op_word(node.op)
        self._w(out, word, pause=sym or top)
        self._emit(node.right, mode, out)

    # -- structures --------------------------------------------------------------
    def _emit_fraction(self, node: Fraction, mode, out) -> None:
        sym = mode == "symbols"
        frac = self.math["fraction"]
        # dy/dx pattern
        if self._is_derivative(node):
            self._emit(node.numerator, mode, out)
            self._w(out, frac["over"], pause=sym)
            self._emit(node.denominator, mode, out)
            return
        self._w(out, frac["open"], pause=sym)
        if mode == "explicit":
            self._w(out, frac["numerator"], pause=sym)
        self._emit(node.numerator, mode, out)
        self._w(out, frac["over"], pause=sym)
        if mode == "explicit":
            self._w(out, frac["denominator"], pause=sym)
        self._emit(node.denominator, mode, out)
        self._w(out, frac["end"], pause=sym)

    @staticmethod
    def _is_derivative(node: Fraction) -> bool:
        def is_d_x(n) -> bool:
            return (isinstance(n, BinaryOp) and n.implicit
                    and isinstance(n.left, Variable) and n.left.name.lower() == "d"
                    and isinstance(n.right, Variable))
        return is_d_x(node.numerator) and is_d_x(node.denominator)

    def _emit_power(self, node: Power, mode, out) -> None:
        sym = mode == "symbols"
        p = self.math["power"]
        self._emit(node.base, mode, out)
        exp = node.exponent
        if isinstance(exp, Number) and exp.value == "2" and not isinstance(node.base, Power):
            self._w(out, p["squared"], pause=sym)
            return
        if isinstance(exp, Number) and exp.value == "3" and not isinstance(node.base, Power):
            self._w(out, p["cubed"], pause=sym)
            return
        self._w(out, p["of"], pause=sym)
        if not isinstance(exp, (Number, Variable, Name, Greek)):
            # compound exponent: "end power" in BOTH passes (blueprint 5.6)
            self._emit_power_compound(exp, mode, out, p)
        else:
            self._emit(exp, mode, out)

    def _emit_power_compound(self, exp, mode, out, p) -> None:
        # spoken as: to the power of, <exp>, end power
        words = self.words(exp, "explicit" if mode != "symbols" else "symbols")
        out.extend((w, pause) for w, pause in words)
        self._w(out, p["end"], pause=(mode != "symbols"))

    def _emit_subscript(self, node: Subscript, mode, out) -> None:
        sym = mode == "symbols"
        s = self.math["subscript"]
        self._emit(node.base, mode, out)
        if isinstance(node.subscript, (Number, Variable, Greek, Name)):
            self._w(out, s["of"], pause=sym)
            self._emit(node.subscript, mode, out)
        else:
            # compound: "x subscript, n plus one, end subscript"
            self._w(out, s.get("word", "subscript"), pause=sym)
            self._emit(node.subscript, mode, out)
            self._w(out, s["end"], pause=sym)

    def _emit_root(self, node: Root, mode, out) -> None:
        sym = mode == "symbols"
        r = self.math["root"]
        if node.index is None:
            self._w(out, r["square"], pause=sym)
        elif isinstance(node.index, Number) and node.index.value == "3":
            self._w(out, r["cube"], pause=sym)
        elif isinstance(node.index, Number) and node.index.value == "n":
            self._w(out, r["general"], pause=sym)
        else:
            self._w(out, r["general"], pause=sym)
            self._w(out, r["degree"], pause=sym)
            self._emit(node.index, mode, out)
        # multi-token radicands are bracketed in speech (the writer draws the
        # radical); single atoms are not
        if isinstance(node.radicand, (Number, Variable, Name, Greek)):
            self._emit(node.radicand, mode, out)
        else:
            self._w(out, self.math["brackets"]["("], pause=sym)
            self._emit(node.radicand, mode, out)
            self._w(out, self.math["brackets"][")"], pause=sym)

    def _emit_function(self, node: Function, mode, out) -> None:
        sym = mode == "symbols"
        funcs = self.math["functions"]
        if node.base is not None:
            self._w(out, funcs.get("log_base", "log to the base"), pause=sym)
            self._emit(node.base, mode, out)
            self._w(out, funcs.get("log_of", "of"), pause=sym)
            self._emit(node.arg, mode, out)
            return
        word = funcs.get(node.name, node.name + " of")
        self._w(out, word, pause=sym)
        self._emit(node.arg, mode, out)

    def _emit_group(self, node: Group, mode, out) -> None:
        sym = mode == "symbols"
        b = self.math["brackets"]
        open_word, close_word = self._bracket_words(node.bracket)
        self._w(out, open_word, pause=sym)
        # deep nesting is announced so the writer can track levels
        depth = self._bracket_depth(node)
        if depth >= 3:
            self._w(out, b["level"], pause=sym)
            self._w(out, number_words(depth), pause=False)
        self._emit(node.body, mode, out)
        self._w(out, close_word, pause=sym)

    def _bracket_words(self, bracket: str):
        b = self.math["brackets"]
        if bracket == "(":
            return b["("], b[")"]
        if bracket == "[":
            return b["["], b["]"]
        return b["{"], b["}"]

    @staticmethod
    def _bracket_depth(node: Group, depth: int = 1) -> int:
        best = depth
        for child in node.children():
            if isinstance(child, Group):
                best = max(best, Verbalizer._bracket_depth(child, depth + 1))
            elif isinstance(child, (BinaryOp, Relation, Fraction, Power, Subscript,
                                    Root, Function, Abs, BigOp, Line)):
                for sub in child.children():
                    if isinstance(sub, Group):
                        best = max(best, Verbalizer._bracket_depth(sub, depth + 1))
        return best

    # -- calculus and matrices -----------------------------------------------------
    def _emit_bigop(self, node: BigOp, mode, out) -> None:
        sym = mode == "symbols"
        c = self.math["calculus"]
        word = c.get({"int": "integral", "sum": "sum", "prod": "product",
                      "lim": "limit"}[node.kind])
        self._w(out, word, pause=sym)
        if node.kind == "lim":
            if node.lower is not None:
                self._w(out, c.get("as", "as"), pause=sym)
                self._emit(node.lower, mode, out)
            self._w(out, c["of"], pause=sym)
            if node.body is not None:
                self._emit(node.body, mode, out)
            return
        if node.lower is not None:
            self._w(out, c["from"], pause=sym)
            self._emit(node.lower, mode, out)
        if node.upper is not None:
            self._w(out, c["to"], pause=sym)
            self._emit(node.upper, mode, out)
        self._w(out, c["of"], pause=sym)
        if node.body is not None:
            self._emit(node.body, mode, out)

    def _emit_matrix(self, node: Matrix, mode, out) -> None:
        sym = mode == "symbols"
        m = self.math["matrix"]
        if node.kind == "vmatrix":
            self._w(out, m["determinant"], pause=sym)
        else:
            self._w(out, m["open"], pause=sym)
        if mode == "explicit":
            self._w(out, f"{number_words(len(node.rows))} {m['rows']}", pause=sym)
            cols = max(len(r) for r in node.rows)
            self._w(out, f"{number_words(cols)} {m['columns']}", pause=sym)
        for i, row in enumerate(node.rows, start=1):
            self._w(out, f"{m['row']} {number_words(i)}", pause=True)
            for j, cell in enumerate(row):
                self._emit(cell, mode, out)
        if node.kind != "vmatrix":
            self._w(out, m["close"], pause=sym)
