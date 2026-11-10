"""OMML and .docx loader tests: Word equations -> LaTeX -> shared AST."""

import io
import zipfile
from pathlib import Path

import pytest

from dictateit.loader import load_text
from dictateit.math.ast_nodes import (
    BinaryOp, Fraction, Greek, Number, Power, Relation, Root, Subscript,
    Variable,
)
from dictateit.math.omml import omml_to_latex, read_docx
from dictateit.math.parser import parse_math

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def xml(body: str) -> bytes:
    return (f'<?xml version="1.0"?>'
            f'<w:document xmlns:w="{W}" xmlns:m="{M}"><w:body>'
            f"{body}</w:body></w:document>").encode("utf-8")


def el(tag: str, *children, **attrs) -> str:
    ns = "m" if tag.split(":")[0] == "m" else "w"
    attrs_s = " ".join(f'm:{k}="{v}"' if ns == "m" else f'w:{k}="{v}"'
                       for k, v in attrs.items())
    inner = "".join(children)
    return f"<{ns}:{tag.split(':')[1]}{' ' + attrs_s if attrs_s else ''}>{inner}</{ns}:{tag.split(':')[1]}>"


def mr(text: str) -> str:
    return el("m:r", el("m:t", text))


def docx(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml(body))
    return path


def omml_of(body: str):
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml(body))
    el_ = root[0][0]            # w:body -> first child
    return el_


class TestOmmlToLatex:
    def test_run_text(self):
        body = el("m:oMath", mr("x"), mr("+"), mr("3"))
        assert omml_to_latex(omml_of(body)) == "x+3"

    def test_fraction(self):
        body = el("m:oMath", el("m:f",
                                el("m:num", mr("a")),
                                el("m:den", mr("b"))))
        assert omml_to_latex(omml_of(body)) == r"\frac{a}{b}"

    def test_superscript(self):
        body = el("m:oMath", el("m:sSup",
                                el("m:e", mr("x")),
                                el("m:sup", mr("2"))))
        assert omml_to_latex(omml_of(body)) == "{x}^{2}"

    def test_subscript(self):
        body = el("m:oMath", el("m:sSub",
                                el("m:e", mr("x")),
                                el("m:sub", mr("1"))))
        assert omml_to_latex(omml_of(body)) == "{x}_{1}"

    def test_sqrt(self):
        body = el("m:oMath", el("m:rad", el("m:deg"), el("m:e", mr("x"))))
        assert omml_to_latex(omml_of(body)) == r"\sqrt{x}"

    def test_nth_root(self):
        body = el("m:oMath", el("m:rad",
                                el("m:deg", mr("3")),
                                el("m:e", mr("8"))))
        assert omml_to_latex(omml_of(body)) == r"\sqrt[3]{8}"

    def test_unicode_operators_mapped(self):
        body = el("m:oMath", mr("x"), mr("\u2264"), mr("5"))
        latex = omml_to_latex(omml_of(body))
        assert latex == r"x\le5"
        assert parse_math(latex, "latex").ast is not None

    def test_nary_sum(self):
        body = el("m:oMath", el("m:nary",
                                el("m:naryPr", el("m:chr", **{"val": "\u2211"})),
                                el("m:sub", mr("i=1")),
                                el("m:sup", mr("n")),
                                el("m:e", mr("i"))))
        latex = omml_to_latex(omml_of(body))
        assert latex == r"\sum_{i=1}^{n} i"

    def test_matrix(self):
        body = el("m:oMath", el("m:m",
                                el("m:mr", el("m:e", mr("1")), el("m:e", mr("2"))),
                                el("m:mr", el("m:e", mr("3")), el("m:e", mr("4")))))
        latex = omml_to_latex(omml_of(body))
        assert latex == r"\begin{pmatrix}1 & 2\\ 3 & 4\end{pmatrix}"


class TestOmmlToAst:
    """The LaTeX OMML produces must hit the SAME parser as typed input."""

    def _ast(self, body):
        latex = omml_to_latex(omml_of(body))
        return parse_math(latex, "latex").ast.lines[0].nodes[0]

    def test_linear(self):
        body = el("m:oMath", mr("x"), mr("="), mr("7"))
        assert self._ast(body) == Relation("=", Variable("x"), Number("7"))

    def test_quadratic_radical(self):
        body = el("m:oMath",
                  el("m:f",
                     el("m:num", el("m:sSup", el("m:e", mr("x")), el("m:sup", mr("2")))),
                     el("m:den", mr("2"))))
        node = self._ast(body)
        assert node == Fraction(
            Power(Variable("x"), Number("2")), Number("2"))

    def test_unicode_minus(self):
        body = el("m:oMath", mr("x"), mr("\u2212"), mr("1"), mr("="), mr("0"))
        assert self._ast(body) == Relation(
            "=", BinaryOp("-", Variable("x"), Number("1")), Number("0"))

    def test_greek_run(self):
        body = el("m:oMath", mr("\u03c0"), mr(">"), mr("3"))
        result = parse_math(omml_to_latex(omml_of(body)), "latex")
        assert result.ast.lines[0].nodes[0].left == Greek("pi")


class TestDocxLoader:
    def test_text_and_math_mixed(self, tmp_path):
        body = (el("w:p", el("w:r", el("w:t", "Solve "))
                   + el("m:oMath", mr("x"), mr("="), mr("5")))
                + el("w:p", el("w:r", el("w:t", "done"))))
        path = docx(tmp_path, "t.docx", body)
        text = read_docx(path)
        assert "Solve $x=5$" in text.replace(" ", "") or "$x=5$" in text
        assert "done" in text

    def test_paragraph_breaks(self, tmp_path):
        body = (el("w:p", el("w:r", el("w:t", "one")))
                + el("w:p", el("w:r", el("w:t", "two"))))
        path = docx(tmp_path, "p.docx", body)
        text = read_docx(path)
        assert text.count("\n\n") == 1

    def test_full_pipeline_from_docx(self, tmp_path):
        body = el("w:p",
                  el("w:r", el("w:t", "Note "))
                  + el("m:oMath",
                       el("m:f", el("m:num", mr("1")), el("m:den", mr("2"))))
                  + el("w:r", el("w:t", " here")))
        path = docx(tmp_path, "m.docx", body)
        from dictateit.pipeline import build_chunks
        from dictateit.models import ChunkKind

        chunks = build_chunks(read_docx(path))
        assert any(c.kind is ChunkKind.MATH and
                   c.spoken_natural.startswith("fraction one over two")
                   for c in chunks)

    def test_load_text_dispatch(self, tmp_path):
        f = tmp_path / "n.txt"
        f.write_text("hello", encoding="utf-8")
        assert load_text(f) == "hello"
        with pytest.raises(ValueError):
            load_text(tmp_path / "x.rtf")

    def test_corrupt_docx_yields_empty(self, tmp_path):
        path = tmp_path / "bad.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", b"<not xml")
        assert read_docx(path) == ""
