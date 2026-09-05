"""The accent kinds MathFmt supports, in every representation they need.

One row per kind so the MathML character, the Word combining mark, and the
name used by ``accent(x, bar)`` cannot drift apart.
"""

from __future__ import annotations

# (kind name, MathML spacing character, Word combining mark)
ACCENTS: tuple[tuple[str, str, str], ...] = (
    ("bar", "‾", "̅"),
    ("hat", "^", "̂"),
    ("vec", "→", "⃗"),
    ("dot", "˙", "̇"),
    ("ddot", "¨", "̈"),
)

ACCENT_CHARS = {name: spacing for name, spacing, _ in ACCENTS}
# U+0302 (hat) is also OMML's implicit default when m:chr is omitted, so
# omitting m:chr would silently turn every unmapped accent into a hat.
OMML_ACCENT_CHARS = {spacing: combining for _, spacing, combining in ACCENTS}
ACCENT_NAMES = {combining: name for name, _, combining in ACCENTS}

#: The mark ISO/IEC 29500's ``CT_AccPr`` implies when ``m:accPr`` — or its
#: ``m:chr`` child — is omitted from an ``m:acc`` entirely (``m:accPr`` is
#: itself ``minOccurs="0"`` in ``CT_Acc``). That is the format's own documented
#: default, not a converter guess, so the reader honors it instead of rejecting
#: the element. In practice it serves third-party or hand-authored OMML:
#: MathFmt's own writer and Office's MML2OMML.XSL both always write ``m:chr``
#: explicitly, even for a hat.
#:
#: Derived from the table rather than written out, so renaming the ``hat`` row
#: fails here at import time instead of silently changing what an absent
#: property means. Compare :data:`mathfmt.nary.OMML_IMPLIED_NARY_CHAR`.
DEFAULT_OMML_ACCENT = OMML_ACCENT_CHARS[ACCENT_CHARS["hat"]]
