"""The n-ary big operators MathFmt supports, in every representation they need.

One row per operator so the linear name (``sum``), the MathML/OMML operator
character (``∑``), and the lookups the parser and both converters test against
cannot drift apart. Adding a row here is all it takes to teach every direction
about a new big operator at once.

Modelled on :mod:`mathfmt.accents`, for the same reason: the previous
name-to-character correspondence lived in three independent tables (the
parser's two identifier sets, ``_nary_mathml``'s ``op_map``, and the OMML
converter's reverse map), and a row added to one of them but not the others
produced an ``m:chr`` the reverse converter then refused to read.
"""

from __future__ import annotations

# (linear name, operator character)
NARY_OPERATORS: tuple[tuple[str, str], ...] = (
    ("int", "∫"),
    ("sum", "∑"),
    ("prod", "∏"),
)

#: Linear name -> operator character (``{"sum": "∑", ...}``).
NARY_CHARS = {name: char for name, char in NARY_OPERATORS}

#: Operator character -> linear name (``{"∑": "sum", ...}``).
NARY_NAMES = {char: name for name, char in NARY_OPERATORS}

#: What the MathML writer emits for an n-ary node naming no known operator.
#: Historic behavior, kept so an unrecognized name degrades to an integral
#: rather than raising in the middle of a document conversion.
FALLBACK_NARY_CHAR = NARY_CHARS["int"]

#: The operator ISO/IEC 29500's ``CT_NaryPr`` implies when ``m:naryPr`` — or
#: its ``m:chr`` child — is omitted from an ``m:nary`` entirely (``m:naryPr``
#: is itself ``minOccurs="0"`` in ``CT_Nary``). That is the format's own
#: documented default, not a converter guess, so the reader honors it instead
#: of rejecting the element.
#:
#: Deliberately *not* the same character as :data:`FALLBACK_NARY_CHAR`: one is
#: what this project writes when it knows nothing, the other is what the
#: format says an absent property means. They sat in two modules under one
#: name before, which read as a contradiction rather than two rules.
OMML_IMPLIED_NARY_CHAR = NARY_CHARS["sum"]
