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

#: All three become the same matrix literal; the bracket style is LaTeX's, and
#: MathFmt's own ``[[…]]`` chooses its fences from context.
MATRIX_ENVIRONMENTS = {"matrix", "pmatrix", "bmatrix"}

#: Multi-row alignment. These keep their ``\\`` separators for
#: ``core.split_multiline_formula``, which lays the rows out as one equation
#: array — this module only strips the environment around them.
ALIGN_ENVIRONMENTS = {"aligned", "align", "align*"}

#: The environment delimiters. They are in :data:`KNOWN_MACROS` so that a
#: document using ``\begin{cases}`` is detected as LaTeX; an unbalanced or
#: unsupported one is then named by the environment pass, which runs first.
ENVIRONMENT_MACROS = {"begin", "end"}

# A macro is a backslash followed by letters (with LaTeX's optional starred
# form), or one of the single-character control symbols. The row separator
# `\\` is deliberately *not* one: the environment pass consumes the separators
# it owns, expand_latex splits on what is left before the other passes run,
# and a `\\` that was never inside an environment is refused rather than
# reaching split_multiline_formula as a row break the author never wrote.
MACRO_RE = re.compile(r"\\(?:[A-Za-z]+\*?|[,;!])")

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
    | ENVIRONMENT_MACROS
)

ENVIRONMENT_RE = re.compile(
    r"\\begin\{(?P<name>[A-Za-z]+\*?)\}(?P<body>.*?)\\end\{(?P=name)\}",
    re.DOTALL,
)

#: The row separator, as a pattern. Two literal backslashes.
ROW_BREAK_RE = re.compile(r"\\\\")
ROW_BREAK = r" \\ "


def contains_latex_macro(text: str) -> bool:
    r"""True when the text contains at least one macro this module knows.

    Deliberately not "contains a backslash": a Windows path such as
    ``C:\Users\gml85`` is full of backslash-letter sequences and none of them
    name a macro, so it is not LaTeX and never becomes a scan candidate.
    """
    return any(_macro_name(match.group()) in KNOWN_MACROS for match in MACRO_RE.finditer(text))


def looks_like_latex(text: str) -> bool:
    r"""True when the text contains anything *shaped* like a macro.

    The wider of the two questions, and the two have different jobs.
    :func:`contains_latex_macro` asks "is this LaTeX I can handle?" and gates
    *discovery*, where a false positive would offer the reader a candidate that
    can never convert. This one asks "is this LaTeX at all?" and gates
    *expansion* of a formula the reader already chose, where the useful answer
    to ``$\substack{a}$`` is the macro's name and a pointer to the supported
    list — not a tokenizer complaint about an unrecognized backslash.

    The row separator ``\\`` is not macro-shaped, so MathFmt's own multi-line
    syntax is not mistaken for LaTeX.
    """
    return MACRO_RE.search(text) is not None


def expand_latex(source: str, *, allow_row_breaks: bool = False) -> str:
    """Expand the supported LaTeX subset into MathFmt linear syntax.

    Five passes, and the order is load-bearing:

    1. the environments, first, because ``&`` and ``\\\\`` only carry meaning
       inside one;
    2. the argument-taking macros, which consume braced groups whose contents
       may themselves be macros;
    3. ``_{…}``/``^{…}`` into MathFmt's parenthesized script form;
    4. binding a large operator's scripts into its ``name(lower,upper)`` call,
       which needs the scripts already parenthesized to find them;
    5. the single-token symbol substitutions, last, so that ``\\to`` inside
       ``\\lim_{x \\to 0}`` is still a macro while step 4 moves it.

    Steps 2-5 run per row. Splitting on the surviving row separators first
    keeps them intact for ``core.split_multiline_formula`` while letting every
    other pass work on separator-free text.

    ``allow_row_breaks`` says the caller already treats ``\\\\`` as a row
    separator of its own. Only ``core.split_multiline_formula`` does — there it
    is MathFmt's documented separator, so a reviewed multi-line formula whose
    rows happen to contain macros is not refused for carrying one.
    """
    if not allow_row_breaks and ROW_BREAK_RE.search(source) and not ENVIRONMENT_RE.search(source):
        raise FormulaError(
            "A row separator is only meaningful inside an aligned, matrix, or cases environment",
            expected="a supported LaTeX macro",
            found=ROW_BREAK.strip(),
            source=source,
        )
    rows = ROW_BREAK_RE.split(_expand_environments(source))
    return ROW_BREAK.join(
        _expand_symbols(_bind_limits(_expand_scripts(_expand_arguments(row)))) for row in rows
    )


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


def _rows(body: str) -> list[list[str]]:
    """An environment body as rows of cells: ``\\\\`` between rows, ``&`` between cells."""
    return [[cell.strip() for cell in row.split("&")] for row in ROW_BREAK_RE.split(body) if row.strip()]


def _expand_environments(source: str) -> str:
    """Replace each supported environment with its MathFmt equivalent."""

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        rows = _rows(match.group("body"))
        if name in MATRIX_ENVIRONMENTS:
            return "[[" + "],[".join(",".join(row) for row in rows) + "]]"
        if name == "cases":
            branches = []
            for row in rows:
                # MathFmt's brace form pairs a value with a condition; a row
                # that is not a pair has no reading that is not a guess about
                # which half is missing.
                if len(row) != 2:
                    raise FormulaError(
                        "Each cases branch needs a value and a condition separated by &",
                        expected="a supported LaTeX macro",
                        found=" & ".join(row),
                        source=source,
                    )
                branches.append(f"{row[0]}, {row[1]}")
            return "{" + "; ".join(branches) + "}"
        if name in ALIGN_ENVIRONMENTS:
            # `&` is only an alignment hint here, and MathFmt aligns on the
            # relation itself, so the cells simply rejoin.
            return ROW_BREAK.join(" ".join(row) for row in rows)
        raise FormulaError(
            f"MathFmt does not support the LaTeX environment {name}",
            expected="a supported LaTeX macro",
            found=name,
            source=source,
        )

    expanded = ENVIRONMENT_RE.sub(replace, source)
    # ENVIRONMENT_RE pairs \begin{x} with \end{x} by name, so anything left is
    # unbalanced or mismatched — never silently dropped.
    if "\\begin" in expanded or "\\end" in expanded:
        raise FormulaError(
            "Unbalanced LaTeX environment",
            expected="a supported LaTeX macro",
            found="\\begin",
            source=source,
        )
    return expanded


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


def _expand_scripts(source: str) -> str:
    """Turn ``_{…}``/``^{…}`` into MathFmt's parenthesized script form.

    Braces are MathFmt's grouping characters too, so leaving them would often
    parse — and parse as something else. The rewrite is recursive so a script
    inside a script keeps its grouping.
    """
    out: list[str] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char in "_^" and index + 1 < len(source) and source[index + 1] == "{":
            content, index = _read_group(source, index + 1, "{", "}")
            out.append(f"{char}({_expand_scripts(content)})")
            continue
        out.append(char)
        index += 1
    return "".join(out)


NARY_RE = re.compile(r"\b(sum|int|prod)\s*_\(([^()]*)\)\s*\^\(([^()]*)\)")
LIMIT_RE = re.compile(r"\blim\s*_\(([^()]*)\)")
# What must never survive _bind_limits: a big operator or lim still carrying a
# script. `\b` matches after the backslash, so this sees the macro spelling as
# well as the bare one.
UNBOUND_RE = re.compile(r"\b(sum|int|prod|lim)\s*[_^]\(")


def _bind_limits(source: str) -> str:
    """Bind a large operator's scripts into its ``name(lower,upper)`` call.

    Refuses rather than leaves one unbound. ``sum``/``int``/``prod``/``lim``
    only mean the big operator when they are *called*; left as ``sum_(i=1)``
    the parser reads a bare identifier and Word renders the letters "sum"
    beside a subscript — a silently wrong equation rather than a reviewable
    error. Reached by a limit holding parentheses (which the patterns below
    cannot span) or by only one of the two limits being present.
    """
    source = NARY_RE.sub(lambda m: f"{m.group(1)}({m.group(2)},{m.group(3)})", source)
    source = LIMIT_RE.sub(lambda m: f"lim({m.group(1)})", source)
    unbound = UNBOUND_RE.search(source)
    if unbound is not None:
        raise FormulaError(
            f"MathFmt cannot read the limits of \\{unbound.group(1)} here — a big operator "
            "needs both bounds, and a bound may not contain parentheses",
            position=unbound.start(),
            expected="a supported LaTeX macro",
            found=unbound.group(),
            source=source,
        )
    return source


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
