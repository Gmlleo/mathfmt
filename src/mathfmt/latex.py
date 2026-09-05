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

#: LaTeX accent macro -> MathFmt accent kind. The values are checked against
#: ``accents.ACCENT_CHARS`` by a test: a typo here would expand cleanly and
#: then fail at parse time, pointing at the expanded text rather than at the
#: macro the author actually wrote.
ACCENT_MACROS = {
    "bar": "bar",
    "overline": "bar",
    "hat": "hat",
    "vec": "vec",
    "dot": "dot",
    "ddot": "ddot",
}

#: All three spell the same fraction; LaTeX's display/text sizing has no linear
#: equivalent, and MathML sizes from context anyway.
FRACTION_MACROS = {"frac", "dfrac", "tfrac"}

#: Upright text. Both become MathFmt's quoted text atom.
TEXT_MACROS = {"text", "mathrm"}

#: Sizing prefixes. The delimiter that follows is kept verbatim, so
#: ``\left( a \right)`` is just ``( a )`` — MathML stretches fences on its own.
SIZING_MACROS = {"left", "right"}

# A macro is a backslash followed by letters (with LaTeX's optional starred
# form), or one of the single-character control symbols. The row separator
# `\\` is matched so that it is *seen*; it is not a known macro here, and only
# the environment pass gives it a meaning.
MACRO_RE = re.compile(r"\\(?:[A-Za-z]+\*?|[,;!\\])")

#: Every macro name this module can expand. See the module docstring.
KNOWN_MACROS = (
    set(GREEK)
    | set(OPERATORS)
    | set(FUNCTIONS)
    | SPACING
    | set(ACCENT_MACROS)
    | FRACTION_MACROS
    | TEXT_MACROS
    | SIZING_MACROS
)


def contains_latex_macro(text: str) -> bool:
    r"""True when the text contains at least one macro this module knows.

    Deliberately not "contains a backslash": a Windows path such as
    ``C:\Users\gml85`` is full of backslash-letter sequences and none of them
    name a macro, so it is not LaTeX and never becomes a scan candidate.
    """
    return any(_macro_name(match.group()) in KNOWN_MACROS for match in MACRO_RE.finditer(text))


def expand_latex(source: str) -> str:
    """Expand the supported LaTeX subset into MathFmt linear syntax.

    Two passes, in this order: the argument-taking macros first, because they
    consume braced groups whose *contents* may themselves be macros, then the
    single-token symbol substitutions over whatever is left.
    """
    return _expand_symbols(_expand_arguments(source))


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


def _read_group(source: str, index: int, opener: str, closer: str) -> tuple[str, int]:
    """Read a balanced ``opener``…``closer`` group starting at ``index``.

    Returns the contents and the index just past the closer. Balanced, not
    "up to the next closer", so a nested group inside the argument — the usual
    case for ``\\frac{\\frac{a}{b}}{c}`` — is read whole.
    """
    while index < len(source) and source[index].isspace():
        index += 1
    if index >= len(source) or source[index] != opener:
        raise FormulaError(
            f"Expected {opener} after a LaTeX macro",
            position=index,
            expected="a supported LaTeX macro",
            found=source[index : index + 1] or "end of formula",
            source=source,
        )
    depth = 0
    for position in range(index, len(source)):
        if source[position] == opener:
            depth += 1
        elif source[position] == closer:
            depth -= 1
            if depth == 0:
                content = source[index + 1 : position]
                # An empty argument has no expansion that is not a guess:
                # accent() and sqrt() both require an operand, so `\bar{}`
                # would expand to a formula that cannot parse anyway, and it
                # is more useful to name the empty argument than to report a
                # syntax error somewhere in the expanded text.
                if not content.strip():
                    raise FormulaError(
                        "A LaTeX macro argument is empty",
                        position=index,
                        expected="a supported LaTeX macro",
                        found=opener + closer,
                        source=source,
                    )
                return content, position + 1
    raise FormulaError(
        f"Unbalanced {opener} in LaTeX input",
        position=index,
        expected=closer,
        found="end of formula",
        source=source,
    )


def _expand_arguments(source: str) -> str:
    """Rewrite the argument-taking macros into MathFmt's call syntax.

    Every argument is expanded recursively and then parenthesized. The linear
    form is flat, so an unparenthesized argument would rebind against the
    surrounding operators — ``\\frac{a+b}{c-d}`` must not become ``a+b/c-d``.
    A macro this pass does not handle is re-emitted verbatim for the symbol
    pass, which is where an unknown macro is finally rejected.
    """
    out: list[str] = []
    index = 0
    while True:
        match = MACRO_RE.search(source, index)
        if match is None:
            out.append(source[index:])
            return "".join(out)
        out.append(source[index : match.start()])
        name = _macro_name(match.group())
        cursor = match.end()
        if name in FRACTION_MACROS:
            numerator, cursor = _read_group(source, cursor, "{", "}")
            denominator, cursor = _read_group(source, cursor, "{", "}")
            out.append(f"({_expand_arguments(numerator)})/({_expand_arguments(denominator)})")
        elif name == "sqrt":
            # The degree is LaTeX's optional [n] argument, and it changes which
            # construct this becomes: sqrt(x,3) would render "x, 3" inside one
            # radical rather than a cube root.
            degree = None
            probe = cursor
            while probe < len(source) and source[probe].isspace():
                probe += 1
            if probe < len(source) and source[probe] == "[":
                degree, cursor = _read_group(source, probe, "[", "]")
            radicand, cursor = _read_group(source, cursor, "{", "}")
            if degree is None:
                out.append(f"sqrt({_expand_arguments(radicand)})")
            else:
                out.append(f"root({_expand_arguments(radicand)},{_expand_arguments(degree)})")
        elif name in ACCENT_MACROS:
            base, cursor = _read_group(source, cursor, "{", "}")
            out.append(f"accent({_expand_arguments(base)},{ACCENT_MACROS[name]})")
        elif name in TEXT_MACROS:
            content, cursor = _read_group(source, cursor, "{", "}")
            # Not expanded: the point of \text is that its contents are not
            # math. A quote would close the text atom early and the remainder
            # would be lexed as math, so it is refused rather than escaped.
            if '"' in content:
                raise FormulaError(
                    "LaTeX text may not contain a double quote",
                    position=match.start(),
                    expected="a supported LaTeX macro",
                    found='"',
                    source=source,
                )
            out.append(f'"{content}"')
        elif name in SIZING_MACROS:
            pass  # the delimiter that follows is kept verbatim
        else:
            out.append(match.group())
        index = cursor


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
