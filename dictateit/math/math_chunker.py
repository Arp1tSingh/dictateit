"""Math chunker: split the AST into dictation chunks (blueprint 5.7).

Chunking works on the AST, not the spoken string. Size is measured in
tokens; default maximum 6.

Split points, in priority order:
1. Relations END a chunk ("x equals") — agreed convention.
2. Top-level + and - START the next chunk ("... plus three x").
3. Fraction parts split when each exceeds 4 tokens; "end numerator" closes
   a multi-chunk numerator, "over" leads the denominator, "end fraction"
   closes the last piece.
4. Bracket groups of 6 tokens or fewer are never split; longer groups split
   inside, with the bracket words on the outer chunks.
5. Big operators: operator and limits form one chunk, then the body.
6. Multi-line derivations: every line starts with "line one", "line two".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ast_nodes import (
    Abs, BigOp, BinaryOp, Derivation, Fraction, Function, Group, Greek, Line,
    Matrix, Number, Power, Relation, Root, Subscript, UnaryOp, Variable, Name,
    token_count, to_latex,
)
from .verbalizer import number_words
from ..models import Chunk, ChunkKind

FRACTION_SPLIT_TOKENS = 4


@dataclass
class _Piece:
    nat: list[str] = field(default_factory=list)
    expl: list[str] = field(default_factory=list)
    syms: list[str] = field(default_factory=list)
    latex: list[str] = field(default_factory=list)
    tokens: int = 0
    extra_gap: float = 0.0
    line_no: int | None = None

    def add_words(self, words_nat: list[str], words_expl: list[str],
                  symbols: list[str]) -> None:
        self.nat.extend(words_nat)
        self.expl.extend(words_expl)
        self.syms.extend(symbols)


def chunk_math(derivation: Derivation, verbalizer, settings,
               segment_id: int) -> list[Chunk]:
    """Split a parsed math segment into ordered Chunks."""
    splitter = _Splitter(verbalizer, int(settings.get("math.max_chunk_tokens", 6)))
    multi_line = len(derivation.lines) > 1

    chunks: list[Chunk] = []
    for line_no, line in enumerate(derivation.lines, start=1):
        pieces = splitter.chunk_line(line)
        if multi_line and pieces:
            marker = f"line {number_words(line_no)}"
            pieces[0].nat.insert(0, marker)
            pieces[0].expl.insert(0, marker)
            pieces[0].syms.insert(0, marker)

        for piece in pieces:
            chunk = Chunk(
                kind=ChunkKind.MATH,
                index=-1,
                text=" ".join(piece.latex),
                spoken_natural=" ".join(piece.nat),
                spoken_explicit=", ".join(piece.expl),
                spoken_symbols=[s for s in piece.syms if s],
                display_latex=" ".join(piece.latex) or None,
                size=piece.tokens + len(piece.nat),
                segment_id=segment_id,
                extra_gap_s=piece.extra_gap,
            )
            chunks.append(chunk)
    return chunks


class _Splitter:
    def __init__(self, verbalizer, max_tokens: int):
        self.v = verbalizer
        self.max = max_tokens
        self.math = verbalizer.math

    # -- small helpers ------------------------------------------------------
    def _words(self, node, mode: str) -> list[str]:
        return [w for w, _ in self.v.words(node, mode)]

    def _symbols(self, node) -> list[str]:
        return self.v.symbols(node)

    def _op_word(self, op: str) -> str:
        return self.math.get("ops", {}).get(op, op)

    def _bracket_words(self, bracket: str) -> tuple[str, str]:
        b = self.math.get("brackets", {})
        if bracket == "[":
            return b.get("[", "open square bracket"), b.get("]", "close square bracket")
        if bracket == "{":
            return b.get("{", "open curly bracket"), b.get("}", "close curly bracket")
        return b.get("(", "open bracket"), b.get(")", "close bracket")

    # -- line level -----------------------------------------------------------
    def chunk_line(self, line: Line) -> list[_Piece]:
        seq = self._flatten_relations(line)
        pieces: list[_Piece] = []

        for item in seq:
            if isinstance(item, str):
                # relation word: attaches to the END of the previous chunk
                # ("x equals" — the agreed convention)
                if pieces:
                    pieces[-1].nat.append(item)
                    pieces[-1].expl.append(item)
                    pieces[-1].syms.append(item)
                    pieces[-1].tokens += 1
                else:
                    pieces.append(_Piece(nat=[item], expl=[item], syms=[item], tokens=1))
                continue
            side = item
            if token_count(side) <= self.max:
                pieces.append(self._whole_piece(side))
            else:
                pieces.extend(self.split_expr(side))
        return pieces

    def _whole_piece(self, node) -> _Piece:
        p = _Piece()
        p.add_words(self._words(node, "natural"),
                    self._words(node, "explicit"),
                    self._symbols(node))
        p.latex = [to_latex(node)]
        p.tokens = token_count(node)
        return p

    def _flatten_relations(self, line: Line) -> list:
        """Line nodes -> [expr, 'rel word', expr, ...] in written order."""
        out: list = []
        for node in line.nodes:
            self._flatten_side(node, out)
        return out

    def _flatten_side(self, node, out: list) -> None:
        if isinstance(node, Relation):
            self._flatten_side(node.left, out)
            out.append(self._op_word(node.op))
            self._flatten_side(node.right, out)
        else:
            out.append(node)

    # -- expression splitting ----------------------------------------------------
    def split_expr(self, node) -> list[_Piece]:
        if isinstance(node, BinaryOp) and node.op in ("+", "-", "+-") and not node.implicit:
            return self._split_additive(node)
        if isinstance(node, UnaryOp) and node.op == "-":
            inner = node.operand
            if token_count(inner) > self.max:
                pieces = self.split_expr(inner)
                pieces[0].nat.insert(0, self._op_word("unary_minus"))
                pieces[0].expl.insert(0, self._op_word("unary_minus"))
                pieces[0].syms.insert(0, self._op_word("unary_minus"))
                return pieces
            return [self._whole_piece(node)]
        if isinstance(node, Fraction):
            return self._split_fraction(node)
        if isinstance(node, Group):
            return self._split_group(node)
        if isinstance(node, Power):
            return self._split_power(node)
        if isinstance(node, BigOp):
            return self._split_bigop(node)
        if isinstance(node, Matrix):
            return self._split_matrix(node)
        # not splittable: keep whole even if over-long
        return [self._whole_piece(node)]

    @staticmethod
    def _additive_terms(node) -> list[tuple[str | None, object]]:
        """Flatten a left-assoc +/- chain into [(sign, term), ...].

        The first term carries sign "-" when the expression starts with a
        unary minus (so "-b + c" still speaks "minus bee"); subsequent terms
        carry the operator that leads their chunk ("+", "-", "+-").
        """
        if isinstance(node, BinaryOp) and node.op in ("+", "-", "+-") and not node.implicit:
            left = _Splitter._additive_terms(node.left)
            left.append((node.op, node.right))
            return left
        if isinstance(node, UnaryOp) and node.op == "-":
            return [("-", node.operand)]
        return [(None, node)]

    def _split_additive(self, node: BinaryOp) -> list[_Piece]:
        """Top-level +/-: each operator starts a new chunk (rule 2)."""
        terms = self._additive_terms(node)
        pieces: list[_Piece] = []
        for i, (sign, term) in enumerate(terms):
            lead: list[str] = []
            if i == 0:
                if sign == "-":
                    lead = [self._op_word("unary_minus")]
            elif sign:
                lead = [self._op_word(sign)]
            if token_count(term) > self.max:
                sub = self.split_expr(term)
                if lead:
                    sub[0].nat[:0] = lead
                    sub[0].expl[:0] = lead
                    sub[0].syms[:0] = lead
                    sub[0].tokens += 1
                pieces.extend(sub)
            else:
                p = self._whole_piece(term)
                p.nat[:0] = lead
                p.expl[:0] = lead
                p.syms[:0] = lead
                p.tokens += len(lead)
                pieces.append(p)
        return pieces

    def _split_fraction(self, node: Fraction) -> list[_Piece]:
        # derivatives (dy/dx) stay whole: "dee why over dee ex" is one idea
        if self.v._is_derivative(node):
            return [self._whole_piece(node)]
        frac = self.math.get("fraction", {})
        pieces: list[_Piece] = []

        num, den = node.numerator, node.denominator
        num_multi = token_count(num) > FRACTION_SPLIT_TOKENS
        den_multi = token_count(den) > FRACTION_SPLIT_TOKENS

        num_pieces = self.split_expr(num) if num_multi else [self._whole_piece(num)]
        den_pieces = self.split_expr(den) if den_multi else [self._whole_piece(den)]

        num_pieces[0].nat[:0] = [frac.get("open", "fraction")]
        num_pieces[0].expl[:0] = [frac.get("open", "fraction"),
                                  frac.get("numerator", "numerator")]
        num_pieces[0].syms[:0] = [frac.get("open", "fraction")]
        num_pieces[0].tokens += 2 if num_multi else 1
        num_pieces[0].extra_gap += 0.5

        den_pieces[0].nat[:0] = [frac.get("over", "over")]
        den_lead = [frac.get("over", "over"), frac.get("denominator", "denominator")]
        if num_multi:
            den_lead.insert(0, frac.get("end_numerator", "end numerator"))
        den_pieces[0].expl[:0] = den_lead
        den_pieces[0].syms[:0] = [frac.get("over", "over")]
        den_pieces[0].tokens += len(den_lead)
        den_pieces[-1].nat.append(frac.get("end", "end fraction"))
        den_pieces[-1].expl.append(frac.get("end", "end fraction"))
        den_pieces[-1].syms.append(frac.get("end", "end fraction"))
        den_pieces[-1].tokens += 1

        pieces.extend(num_pieces)
        pieces.extend(den_pieces)
        return pieces

    def _split_group(self, node: Group) -> list[_Piece]:
        body = node.body
        if token_count(body) <= self.max:
            return [self._whole_piece(node)]
        open_word, close_word = self._bracket_words(node.bracket)
        inner = self.split_expr(body)
        inner[0].nat.insert(0, open_word)
        inner[0].expl.insert(0, open_word)
        inner[0].syms.insert(0, open_word)
        inner[-1].nat.append(close_word)
        inner[-1].expl.append(close_word)
        inner[-1].syms.append(close_word)
        inner[0].tokens += 1
        return inner

    def _split_power(self, node: Power) -> list[_Piece]:
        base, exp = node.base, node.exponent
        base_big = token_count(base) > self.max
        exp_big = token_count(exp) > self.max
        if not base_big and not exp_big:
            return [self._whole_piece(node)]

        pw = self.math.get("power", {})
        pieces: list[_Piece] = []
        if base_big:
            pieces.extend(self.split_expr(base))
        else:
            pieces.append(self._whole_piece(base))

        exp_pieces = self.split_expr(exp) if exp_big else [self._whole_piece(exp)]
        exp_pieces[0].nat[:0] = [pw.get("of", "to the power of")]
        exp_pieces[0].expl[:0] = [pw.get("of", "to the power of")]
        exp_pieces[0].syms[:0] = [pw.get("of", "to the power of")]
        exp_pieces[0].tokens += 1
        exp_pieces[-1].nat.append(pw.get("end", "end power"))
        exp_pieces[-1].expl.append(pw.get("end", "end power"))
        exp_pieces[-1].syms.append(pw.get("end", "end power"))
        exp_pieces[-1].tokens += 1
        pieces.extend(exp_pieces)
        return pieces

    def _split_bigop(self, node: BigOp) -> list[_Piece]:
        head = BigOp(node.kind, node.lower, node.upper, None)
        pieces = [self._whole_piece(head)]
        pieces[0].extra_gap += 0.5
        if node.body is None:
            return pieces
        if token_count(node.body) <= self.max:
            pieces.append(self._whole_piece(node.body))
        else:
            pieces.extend(self.split_expr(node.body))
        return pieces

    def _split_matrix(self, node: Matrix) -> list[_Piece]:
        m = self.math.get("matrix", {})
        pieces: list[_Piece] = []

        head = _Piece(extra_gap=1.0)
        if node.kind == "vmatrix":
            head.nat = [m.get("determinant", "determinant")]
            head.expl = [m.get("determinant", "determinant")]
        else:
            head.nat = [m.get("open", "open matrix")]
            head.expl = [m.get("open", "open matrix")]
        head.syms = list(head.nat)
        if node.kind != "vmatrix":
            rows_n = max(len(node.rows), 1)
            cols = max(len(r) for r in node.rows) if node.rows else 0
            head.expl.append(f"{number_words(rows_n)} {m.get('rows', 'rows')}")
            head.expl.append(f"{number_words(cols)} {m.get('columns', 'columns')}")
        head.tokens = 1
        pieces.append(head)

        for i, row in enumerate(node.rows, start=1):
            rp = _Piece()
            lead = f"{m.get('row', 'row')} {number_words(i)}"
            rp.nat.append(lead + ":")
            rp.expl.append(lead + ":")
            rp.syms.append(lead)
            for cell in row:
                rp.add_words(self._words(cell, "natural"),
                             self._words(cell, "explicit"),
                             self._symbols(cell))
                rp.latex.append(to_latex(cell))
                rp.tokens += token_count(cell) + 1
            pieces.append(rp)

        if node.kind != "vmatrix":
            pieces[-1].nat.append(m.get("close", "end matrix"))
            pieces[-1].expl.append(m.get("close", "end matrix"))
            pieces[-1].syms.append(m.get("close", "end matrix"))
        return pieces
