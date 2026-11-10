"""OMML -> LaTeX for Word equation objects (blueprint phase 10).

Word stores equations as Office Math Markup Language inside
`word/document.xml`. Rather than adding python-docx (a heavy
dependency for one format), the loader reads the zip with the stdlib
and this module converts each `m:oMath` element to LaTeX, which feeds
the existing parser — one AST, one verbalizer, one chunker, all
shared with the LaTeX/plain/Unicode paths.

Covered OMML constructs: runs, fractions, superscripts/subscripts
(including sSubSup), radicals (with optional degree), delimiters with
custom begin/end characters, n-ary operators (sum, integral, product),
functions, limits, accents (hat/bar/vec are passed through when the
parser knows them), matrices, and boxed text runs. Anything exotic
degrades to its raw text; the normal MathParseError fallback then
reads it symbol by symbol, flagged ambiguous.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# unicode operators that appear in m:t runs -> LaTeX the parser knows
_TEXT_MAP = {
    "\u2264": r"\le", "\u2265": r"\ge", "\u2260": r"\ne",
    "\u00d7": r"\times", "\u00f7": r"\div", "\u00b1": r"\pm",
    "\u2212": "-", "\u2013": "-", "\u221e": r"\infty",
    "\u2192": r"\to", "\u2248": r"\approx", "\u2026": "...",
    "\u03b1": r"\alpha", "\u03b2": r"\beta", "\u03b3": r"\gamma",
    "\u03b4": r"\delta", "\u03b8": r"\theta", "\u03bb": r"\lambda",
    "\u03bc": r"\mu", "\u03c0": r"\pi", "\u03c3": r"\sigma",
    "\u03c6": r"\phi", "\u03c9": r"\omega",
    "\u0394": r"\Delta", "\u03a3": r"\Sigma", "\u03a9": r"\Omega",
    "\u00b2": "^2", "\u00b3": "^3", "\u00bd": r"\frac{1}{2}",
}

_NARY_CHR = {"\u2211": "sum", "\u222b": "int", "\u220f": "prod",
             "\u222e": "int", "\u22c3": "sum", "\u22c0": "prod"}

_DELIM_BRACKETS = {"(": "(", ")": ")", "[": "[", "]": "]",
                   "{": "\\{", "}": "\\}", "|": "|"}

_FUNCTIONS = {"sin", "cos", "tan", "sec", "csc", "cot", "log", "ln", "exp",
              "max", "min", "det", "lim", "mod"}


def _local(tag: str) -> str:
    """`{namespace}name` -> `name`."""
    return tag.rsplit("}", 1)[-1]


def _children(el) -> list:
    return list(el)


def _first(el, name: str):
    for child in el:
        if _local(child.tag) == name:
            return child
    return None


def _all(el, name: str) -> list:
    return [child for child in el if _local(child.tag) == name]


def _escape_text(text: str) -> str:
    out = []
    for ch in text:
        if ch in _TEXT_MAP:
            out.append(_TEXT_MAP[ch])
        elif ch == "\\":
            out.append(r"\backslash")  # parser reads it symbol-wise on fallback
        else:
            out.append(ch)
    return "".join(out)


class _Converter:
    def convert(self, el) -> str:
        handler = getattr(self, f"_do_{_local(el.tag)}", self._do_fallback)
        return handler(el)

    # -- leaf runs ----------------------------------------------------------
    def _do_t(self, el) -> str:
        return _escape_text("".join(el.itertext()))

    def _do_r(self, el) -> str:
        # an m:r run holds m:t text plus run properties
        parts = [self.convert(t) for t in _all(el, "t")]
        return "".join(parts)

    def _do_fallback(self, el) -> str:
        # unknown structure: flatten its runs so simple math still reads
        parts = []
        for child in el:
            parts.append(self.convert(child))
        return "".join(parts)

    # -- structures -----------------------------------------------------------
    def _do_oMath(self, el) -> str:
        return "".join(self.convert(child) for child in el)

    def _do_f(self, el) -> str:
        num_el = _first(el, "num")
        den_el = _first(el, "den")
        num = self.convert(num_el) if num_el is not None else ""
        den = self.convert(den_el) if den_el is not None else ""
        return r"\frac{%s}{%s}" % (num, den)

    def _do_sSup(self, el) -> str:
        base = self.convert(_first(el, "e")) if _first(el, "e") is not None else ""
        sup = self.convert(_first(el, "sup")) if _first(el, "sup") is not None else ""
        return "{%s}^{%s}" % (base, sup)

    def _do_sSub(self, el) -> str:
        base = self.convert(_first(el, "e")) if _first(el, "e") is not None else ""
        sub = self.convert(_first(el, "sub")) if _first(el, "sub") is not None else ""
        return "{%s}_{%s}" % (base, sub)

    def _do_sSubSup(self, el) -> str:
        base = self.convert(_first(el, "e")) if _first(el, "e") is not None else ""
        sub = self.convert(_first(el, "sub")) if _first(el, "sub") is not None else ""
        sup = self.convert(_first(el, "sup")) if _first(el, "sup") is not None else ""
        return "{%s}_{%s}^{%s}" % (base, sub, sup)

    def _do_rad(self, el) -> str:
        deg = _first(el, "deg")
        body_el = _first(el, "e")
        body = self.convert(body_el) if body_el is not None else ""
        if deg is not None:
            deg_hidden = _first(deg, "degHide") is not None
            deg_text = "".join(deg.itertext()).strip()
            if not deg_hidden and deg_text:
                return r"\sqrt[%s]{%s}" % (self.convert(deg), body)
        return r"\sqrt{%s}" % body

    def _do_d(self, el) -> str:
        beg, end = "(", ")"
        props = _first(el, "dPr")
        if props is not None:
            beg_el = _first(props, "begChar")
            end_el = _first(props, "endChar")
            if beg_el is not None:
                beg = beg_el.get(f"{{{M_NS}}}val", "(")
            if end_el is not None:
                end = end_el.get(f"{{{M_NS}}}val", ")")
        bodies = [self.convert(e) for e in _all(el, "e")]
        inner = "; ".join(bodies)   # multiple m:e children are separated
        open_b = _DELIM_BRACKETS.get(beg, beg)
        close_b = _DELIM_BRACKETS.get(end, end)
        return "%s%s%s" % (open_b, inner, close_b)

    def _do_nary(self, el) -> str:
        props = _first(el, "naryPr")
        char = "\u2211"
        if props is not None:
            chr_el = _first(props, "chr")
            if chr_el is not None:
                char = chr_el.get(f"{{{M_NS}}}val", "\u2211")
        kind = _NARY_CHR.get(char, "sum")
        sub = self.convert(_first(el, "sub")) if _first(el, "sub") is not None else ""
        sup = self.convert(_first(el, "sup")) if _first(el, "sup") is not None else ""
        body = self.convert(_first(el, "e")) if _first(el, "e") is not None else ""
        return "\\%s_{%s}^{%s} %s" % (kind, sub, sup, body)

    def _do_func(self, el) -> str:
        name = self.convert(_first(el, "fName")) if _first(el, "fName") is not None else ""
        arg = self.convert(_first(el, "e")) if _first(el, "e") is not None else ""
        return "%s %s" % (name, arg)

    def _do_limLow(self, el) -> str:
        base = self.convert(_first(el, "e")) if _first(el, "e") is not None else ""
        lim = self.convert(_first(el, "lim")) if _first(el, "lim") is not None else ""
        return "%s_{%s}" % (base, lim)

    def _do_limUpp(self, el) -> str:
        base = self.convert(_first(el, "e")) if _first(el, "e") is not None else ""
        lim = self.convert(_first(el, "lim")) if _first(el, "lim") is not None else ""
        return "%s^{%s}" % (base, lim)

    def _do_acc(self, el) -> str:
        acc_char = "\u0302"
        props = _first(el, "accPr")
        if props is not None:
            chr_el = _first(props, "chr")
            if chr_el is not None:
                acc_char = chr_el.get(f"{{{M_NS}}}val", acc_char)
        body = self.convert(_first(el, "e")) if _first(el, "e") is not None else ""
        accent = {"\u0302": r"\hat", "\u0304": r"\bar",
                  "\u0303": r"\tilde", "\u20d7": r"\vec"}.get(acc_char)
        if accent is None:
            return body
        return "%s{%s}" % (accent, body)

    def _do_m(self, el) -> str:
        rows = []
        for mr_el in _all(el, "mr"):
            cells = [self.convert(e) for e in _all(mr_el, "e")]
            rows.append(" & ".join(cells))
        return r"\begin{pmatrix}" + r"\\ ".join(rows) + r"\end{pmatrix}"


_CONVERTER = _Converter()


def omml_to_latex(omml_el) -> str:
    """One m:oMath element -> LaTeX source."""
    return _CONVERTER.convert(omml_el)


def read_docx(path) -> str:
    """The text of a .docx with equations inline as `$...$`.

    Paragraph breaks become blank lines so the normalizer treats them
    as "new paragraph" markers. Only `word/document.xml` is read; a
    malformed file yields whatever text can be salvaged.
    """
    with zipfile.ZipFile(path) as z:
        xml_bytes = z.read("word/document.xml")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""

    lines: list[str] = []
    for para in root.iter(f"{{{W_NS}}}p"):
        parts: list[str] = []
        for child in para.iter():
            tag = _local(child.tag)
            if tag == "t" and child.text:
                parts.append(child.text)
            elif tag == "oMath":
                latex = omml_to_latex(child)
                if latex.strip():
                    parts.append(f"${latex}$")
        line = "".join(parts)
        lines.append(line)
    return "\n\n".join(lines)
