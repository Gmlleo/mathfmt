"""Load and validate user-defined symbol alias profiles."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ALIAS_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")

# These names already control parser behavior or documented built-in notation.
# User aliases may add symbols, but must not change the meaning of core syntax.
RESERVED_ALIAS_TOKENS = frozenset(
    {
        "Delta",
        "accent",
        "bra",
        "braket",
        "cases",
        "cos",
        "exp",
        "if",
        "inf",
        "int",
        "ket",
        "lim",
        "partial",
        "pPAIR",
        "pi",
        "prod",
        "sin",
        "sqrt",
        "sum",
        "tan",
        "u",
    }
)


@dataclass(frozen=True)
class AliasProfile:
    """Validated alias configuration plus stable report metadata."""

    name: str
    path: Path
    aliases: dict[str, str]
    sha256: str

    def metadata(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "sha256": self.sha256,
            "count": len(self.aliases),
        }


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Alias profile contains duplicate key: {key!r}")
        result[key] = value
    return result


def _validate_symbol(token: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Alias {token!r} must map to a string")
    if len(value) != 1:
        raise ValueError(f"Alias {token!r} must map to exactly one Unicode symbol")
    if value.isspace() or unicodedata.category(value).startswith("C"):
        raise ValueError(f"Alias {token!r} maps to an unsupported whitespace/control character")
    if value.isascii() and value.isalnum():
        raise ValueError(f"Alias {token!r} must map to a mathematical symbol, not ASCII text")
    if value in "()[]{},;":
        raise ValueError(f"Alias {token!r} cannot map to a core grouping or separator character")
    return value


def load_alias_profile(path: Path) -> AliasProfile:
    """Load a strict JSON alias profile with a stable content digest."""
    if path.suffix.lower() != ".json":
        raise ValueError("Alias profile must be a .json file")
    if not path.is_file():
        raise FileNotFoundError(f"Alias profile was not found: {path}")

    try:
        raw = json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_object_without_duplicates,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid alias profile JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(raw, dict):
        raise ValueError("Alias profile root must be a JSON object")
    unknown = sorted(set(raw) - {"name", "aliases"})
    if unknown:
        raise ValueError(f"Alias profile contains unknown field(s): {', '.join(unknown)}")

    name = raw.get("name", path.stem)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Alias profile name must be a non-empty string")
    name = name.strip()

    configured = raw.get("aliases")
    if not isinstance(configured, dict) or not configured:
        raise ValueError("Alias profile must contain a non-empty 'aliases' object")

    aliases: dict[str, str] = {}
    for token, value in configured.items():
        if not ALIAS_TOKEN_RE.fullmatch(token):
            raise ValueError(
                f"Alias token {token!r} must start with an ASCII letter and contain only letters or digits"
            )
        if token in RESERVED_ALIAS_TOKENS or re.fullmatch(r"DERV\d+", token):
            raise ValueError(f"Alias token {token!r} is reserved by MathFmt core syntax")
        aliases[token] = _validate_symbol(token, value)

    canonical = json.dumps(
        {"name": name, "aliases": aliases},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return AliasProfile(name=name, path=path.resolve(), aliases=aliases, sha256=digest)


def alias_profile_metadata(profile: AliasProfile | None) -> dict[str, object] | None:
    return profile.metadata() if profile is not None else None


def validate_review_alias_profile(
    review: dict[str, object],
    profile: AliasProfile | None,
) -> None:
    """Ensure apply/validate use the exact alias semantics recorded by scan."""
    review_profile = review.get("profile")
    if not isinstance(review_profile, dict):
        return
    expected = review_profile.get("aliases")
    if expected is None:
        if profile is not None:
            raise ValueError("Review report was created without an alias profile; scan again with --aliases")
        return
    if not isinstance(expected, dict) or not isinstance(expected.get("sha256"), str):
        raise ValueError("Review report contains invalid alias profile metadata")
    if profile is None:
        name = expected.get("name", "unknown")
        raise ValueError(f"Review report uses alias profile {name!r}; pass the same file with --aliases")
    if expected["sha256"] != profile.sha256:
        raise ValueError(
            f"Alias profile {profile.name!r} does not match the profile recorded by the review report"
        )
