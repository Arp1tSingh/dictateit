"""Math normalizer: map Unicode look-alikes to canonical forms
(blueprint section 5.4) before the LaTeX or plain-text parser sees them."""

from __future__ import annotations

import re

# Characters that must not survive into either parser.
_UNICODE_TO_LATEX = {
    "\u2212": "-",    # minus sign
    "\u2013": "-",    # en dash used as minus
    "\u00d7": "\\times",
    "\u22c5": "\\cdot",
    "\u2219": "\\cdot",
    "\u00b7": "\\cdot",
    "\u00f7": "\\div",
    "\u2264": "\\le",
    "\u2265": "\\ge",
    "\u2260": "\\ne",
    "\u2248": "\\approx",
    "\u00b1": "\\pm",
    "\u2213": "\\mp",
    "\u221e": "\\infty",
    "\u221a": "\\sqrt",
    "\u03c0": "\\pi",
    "\u2202": "\\partial",
    "\u2192": "\\to",
    "\u21d2": "\\implies",
    "\u2062": "",      # invisible times
}

_UNICODE_TO_PLAIN = {
    "\u2212": "-",
    "\u2013": "-",
    "\u00d7": "*",
    "\u22c5": "*",
    "\u2219": "*",
    "\u00b7": "*",
    "\u00f7": "/",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
    "\u2248": "~=",
    "\u00b1": "+-",
    "\u2213": "+-",
    "\u221e": "inf",
    "\u221a": "sqrt ",
    "\u03c0": "pi",
    "\u2202": "partial ",
    "\u2192": " to ",
    "\u2062": "",
}

_SUPERSCRIPTS = {
    "\u2070": "0", "\u00b9": "1", "\u00b2": "2", "\u00b3": "3", "\u2074": "4",
    "\u2075": "5", "\u2076": "6", "\u2077": "7", "\u2078": "8", "\u2079": "9",
    "\u207f": "n",
}

_SUBSCRIPTS = {
    "\u2080": "0", "\u2081": "1", "\u2082": "2", "\u2083": "3", "\u2084": "4",
    "\u2085": "5", "\u2086": "6", "\u2087": "7", "\u2088": "8", "\u2089": "9",
    "\u2099": "n",
}

_GREEK_NAMES = [
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta",
    "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron",
    "pi", "rho", "sigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
]

_GREEK_UNICODE = {
    "\u03b1": "alpha", "\u03b2": "beta", "\u03b3": "gamma", "\u03b4": "delta",
    "\u03b5": "epsilon", "\u03b6": "zeta", "\u03b7": "eta", "\u03b8": "theta",
    "\u03b9": "iota", "\u03ba": "kappa", "\u03bb": "lambda", "\u03bc": "mu",
    "\u03bd": "nu", "\u03be": "xi", "\u03bf": "omicron", "\u03c0": "pi",
    "\u03c1": "rho", "\u03c3": "sigma", "\u03c4": "tau", "\u03c5": "upsilon",
    "\u03c6": "phi", "\u03c7": "chi", "\u03c8": "psi", "\u03c9": "omega",
    # uppercase
    "\u0393": "Gamma", "\u0394": "Delta", "\u0398": "Theta", "\u039b": "Lambda",
    "\u03a3": "Sigma", "\u03a9": "Omega", "\u03a6": "Phi", "\u03a8": "Psi",
    "\u03a0": "Pi", "\u039e": "Xi",
}

_SUP_RE = re.compile("[" + "".join(_SUPERSCRIPTS) + "]")
_SUB_RE = re.compile("[" + "".join(_SUBSCRIPTS) + "]")


def normalize_latex(text: str) -> str:
    """Unicode math inside LaTeX input -> LaTeX macros."""
    out = text
    for ch, repl in _UNICODE_TO_LATEX.items():
        out = out.replace(ch, repl)
    for ch, repl in _GREEK_UNICODE.items():
        out = out.replace(ch, f"\\{repl.lower()}" if not repl[0].isupper()
                          else f"\\{repl}")
    out = _SUP_RE.sub(lambda m: f"^{{{_SUPERSCRIPTS[m.group()]}}}", out)
    out = _SUB_RE.sub(lambda m: f"_{{{_SUBSCRIPTS[m.group()]}}}", out)
    # common aliases
    out = out.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    out = out.replace("\\leq", "\\le").replace("\\geq", "\\ge")
    out = out.replace("\\neq", "\\ne")
    return out


def normalize_plain(text: str) -> str:
    """Unicode math inside plain text -> ASCII the plain parser understands."""
    out = text
    for ch, repl in _UNICODE_TO_PLAIN.items():
        out = out.replace(ch, repl)
    for ch, repl in _GREEK_UNICODE.items():
        out = out.replace(ch, repl)
    out = _SUP_RE.sub(lambda m: f"^{_SUPERSCRIPTS[m.group()]}", out)
    out = _SUB_RE.sub(lambda m: f"_{_SUBSCRIPTS[m.group()]}", out)
    return out


def has_unicode_math(text: str) -> bool:
    keys = list(_UNICODE_TO_PLAIN) + list(_GREEK_UNICODE) + list(_SUPERSCRIPTS) + list(_SUBSCRIPTS)
    return any(ch in text for ch in keys)
