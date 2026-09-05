"""Expand a documented subset of LaTeX into MathFmt's linear formula syntax.

This module is a pure text-to-text transform: it knows nothing about lxml,
MathML, or OMML. Anything outside the documented subset raises
:class:`~mathfmt.core.FormulaError` rather than being guessed at, so a wrong
rendering can never be produced from an unsupported macro — an unconverted
formula is reviewable, a silently wrong one is not.

:data:`KNOWN_MACROS` is the one inventory both directions read.
:func:`contains_latex_macro` is what promotes a span to a scan candidate and
:func:`expand_latex` is what that candidate is then parsed through, so a name
known to one but not the other would make the scanner report a formula that
can never convert. Adding a macro means adding it to both at once.

``core`` is imported for its error type only, and ``core`` imports this module
from inside ``formula_to_mathml`` rather than at module scope, so the cycle
never closes at import time.
"""

from __future__ import annotations

import re

from .core import FormulaError

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}  # fmt: skip

# Every character here must be one the tokenizer accepts, or the expansion
# merely moves the parse error somewhere less legible. The one deliberate
# exception is ∂: it is untokenizable on its own (see TOKEN_RE's note), so
# `\partial f / \partial x` converts through preprocess_formula's Leibniz
# handling while a standalone `\partial` reports a reviewable parse error
# instead of a guess at what the author meant.
OPERATORS = {
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "pm": "±", "mp": "∓", "times": "×",
    "cdot": "·", "div": "÷", "to": "→", "rightarrow": "→", "Rightarrow": "⇒",
    "leftrightarrow": "<->", "in": "∈", "notin": "∉", "subset": "⊂",
    "subseteq": "⊆", "cup": "∪", "cap": "∩", "infty": "∞", "partial": "∂",
    "nabla": "∇",
}  # fmt: skip

#: Macros whose LaTeX name is already MathFmt's own spelling, so expansion is
#: just dropping the backslash.
FUNCTIONS = {"sin", "cos", "tan", "log", "ln", "exp", "lim", "sum", "int", "prod", "sqrt"}

#: Spacing macros. LaTeX's widths have no linear equivalent and MathML
#: collapses runs anyway, so each becomes one space — enough to keep the
#: tokens on either side from merging, which is the only role they can play.
SPACING = {",", ";", "!", "quad", "qquad"}

# A macro is a backslash followed by letters (with LaTeX's optional starred
# form), or one of the single-character control symbols. The row separator
# `\\` is matched so that it is *seen*; it is not a known macro here, and only
# the environment pass gives it a meaning.
MACRO_RE = re.compile(r"\\(?:[A-Za-z]+\*?|[,;!\\])")

#: Every macro name this module can expand. See the module docstring.
KNOWN_MACROS = set(GREEK) | set(OPERATORS) | set(FUNCTIONS) | SPACING


def contains_latex_macro(text: str) -> bool:
    r"""True when the text contains at least one macro this module knows.

    Deliberately not "contains a backslash": a Windows path such as
    ``C:\Users\gml85`` is full of backslash-letter sequences and none of them
    name a macro, so it is not LaTeX and never becomes a scan candidate.
    """
    return any(_macro_name(match.group()) in KNOWN_MACROS for match in MACRO_RE.finditer(text))


def expand_latex(source: str) -> str:
    """Expand the supported LaTeX subset into MathFmt linear syntax."""
    return _expand_symbols(source)


def _macro_name(macro: str) -> str:
    return macro[1:]


def _reject(name: str, source: str, position: int) -> FormulaError:
    return FormulaError(
        f"MathFmt does not support the LaTeX macro \\{name}",
        position=position,
        expected="a supported LaTeX macro",
        found=f"\\{name}",
        source=source,
    )


def _expand_symbols(source: str) -> str:
    out: list[str] = []
    index = 0
    for match in MACRO_RE.finditer(source):
        out.append(source[index : match.start()])
        name = _macro_name(match.group())
        if name in SPACING:
            out.append(" ")
        elif name in GREEK:
            out.append(GREEK[name])
        elif name in OPERATORS:
            out.append(OPERATORS[name])
        elif name in FUNCTIONS:
            out.append(name)
        else:
            raise _reject(name, source, match.start())
        index = match.end()
    out.append(source[index:])
    return "".join(out)
