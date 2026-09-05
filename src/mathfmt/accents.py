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
