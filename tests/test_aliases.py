from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathfmt.aliases import (
    alias_profile_metadata,
    load_alias_profile,
    validate_review_alias_profile,
)


def write_profile(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_alias_profile_returns_stable_metadata(tmp_path: Path) -> None:
    payload = {"name": "engineering", "aliases": {"ohm": "Ω", "mapsTo": "↦"}}
    first = load_alias_profile(write_profile(tmp_path / "first.json", payload))
    second = load_alias_profile(write_profile(tmp_path / "second.json", payload))

    assert first.name == "engineering"
    assert first.aliases == {"ohm": "Ω", "mapsTo": "↦"}
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
    assert alias_profile_metadata(first) == {
        "name": "engineering",
        "path": str(first.path),
        "sha256": first.sha256,
        "count": 2,
    }
    assert alias_profile_metadata(None) is None


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"aliases": {}}, "non-empty"),
        ({"name": "", "aliases": {"ohm": "Ω"}}, "name"),
        ({"aliases": {"bad-token": "Ω"}}, "ASCII letter"),
        ({"aliases": {"sqrt": "√"}}, "reserved"),
        ({"aliases": {"accent": "‾"}}, "reserved"),
        ({"aliases": {"if": "⇒"}}, "reserved"),
        ({"aliases": {"pPAIR": "ℙ"}}, "reserved"),
        ({"aliases": {"DERV0": "∂"}}, "reserved"),
        ({"aliases": {"ohm": 1}}, "string"),
        ({"aliases": {"ohm": "Ohm"}}, "exactly one"),
        ({"aliases": {"ohm": "R"}}, "mathematical symbol"),
        ({"aliases": {"left": "("}}, "grouping"),
        ({"aliases": {"blank": "\n"}}, "whitespace/control"),
        ({"aliases": {"ohm": "Ω"}, "extra": True}, "unknown field"),
    ],
)
def test_invalid_alias_profile_content_is_rejected(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    path = write_profile(tmp_path / "aliases.json", payload)

    with pytest.raises(ValueError, match=message):
        load_alias_profile(path)


def test_invalid_alias_profile_file_errors_are_clear(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=".json"):
        load_alias_profile(tmp_path / "aliases.toml")
    with pytest.raises(FileNotFoundError, match="not found"):
        load_alias_profile(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1, column 2"):
        load_alias_profile(malformed)

    root_list = write_profile(tmp_path / "list.json", [])
    with pytest.raises(ValueError, match="root"):
        load_alias_profile(root_list)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"aliases":{"ohm":"Ω","ohm":"Ω"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate key"):
        load_alias_profile(duplicate)


def test_review_alias_profile_must_match_exactly(tmp_path: Path) -> None:
    first = load_alias_profile(
        write_profile(tmp_path / "first.json", {"name": "one", "aliases": {"ohm": "Ω"}})
    )
    second = load_alias_profile(
        write_profile(tmp_path / "second.json", {"name": "two", "aliases": {"ohm": "Ω"}})
    )
    review = {"profile": {"aliases": first.metadata()}}

    validate_review_alias_profile(review, first)
    with pytest.raises(ValueError, match="pass the same file"):
        validate_review_alias_profile(review, None)
    with pytest.raises(ValueError, match="does not match"):
        validate_review_alias_profile(review, second)
    with pytest.raises(ValueError, match="invalid alias profile metadata"):
        validate_review_alias_profile({"profile": {"aliases": {"name": "bad"}}}, first)

    validate_review_alias_profile({}, None)
    with pytest.raises(ValueError, match="created without an alias profile"):
        validate_review_alias_profile({"profile": {"aliases": None}}, second)
