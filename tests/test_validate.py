from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from mathfmt.aliases import load_alias_profile
from mathfmt.cli import main
from mathfmt.core import M_NS, find_xsl, formula_to_mathml, qname
from mathfmt.omml import mathml_to_omml_py
from mathfmt.validate import validate_docx
from tests.helpers import make_docx, make_docx_with_omml

# -- helpers ------------------------------------------------------------------


def omath_for(source: str) -> str:
    mathml = formula_to_mathml(source)
    omath = mathml_to_omml_py(mathml)
    return etree.tostring(omath, encoding="unicode")


def m(namespace: str, local: str) -> str:
    return qname(namespace, local)


# -- valid DOCX ---------------------------------------------------------------


def test_valid_docx_passes_validation(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    report = validate_docx(source)
    assert report["valid"] is True
    assert report["package"]["valid_zip"] is True
    assert isinstance(report["package"], dict)
    pkg = report["package"]
    assert pkg.get("paragraphs", 0) > 0


def test_piecewise_omml_passes_structure_validation(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "piecewise.docx",
        content=f"<w:p>{omath_for('cases(0 if x<0; 1 if x>=0)')}</w:p>",
    )

    report = validate_docx(source)

    assert report["valid"] is True
    assert report["omml"]["equation_count"] == 1
    assert report["omml"]["structural_errors"] == []


def test_chemistry_omml_passes_structure_validation(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "chemistry.docx",
        content=f"<w:p>{omath_for('CaCO3 =>[heat] CaO + CO2')}</w:p>",
    )

    report = validate_docx(source)

    assert report["valid"] is True
    assert report["omml"]["equation_count"] == 1
    assert report["omml"]["structural_errors"] == []


def test_physics_omml_passes_structure_validation(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "physics.docx",
        content=f"<w:p>{omath_for('∂f/∂x + T_i^j')}</w:p><w:p>{omath_for('<phi|psi>')}</w:p>",
    )

    report = validate_docx(source)

    assert report["valid"] is True
    assert report["omml"]["equation_count"] == 2
    assert report["omml"]["structural_errors"] == []


def test_validate_report_uses_v3_top_level_schema(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    report = validate_docx(source)

    assert report["schema_version"] == 3
    assert report["report_type"] == "validation"
    assert report["command"]["name"] == "validate"
    assert report["inputs"]["docx"] == str(source.resolve())
    assert report["inputs"]["review"] is None
    assert report["options"]["backend"] == "python"
    assert report["summary"]["valid"] is True
    assert report["summary"]["errors"] == 0


def test_valid_docx_with_omml_passes(tmp_path: Path) -> None:
    clean_omath = omath_for("x = 1")
    source = make_docx_with_omml(
        tmp_path / "omml.docx",
        content=f"<w:p>{clean_omath}</w:p>",
    )
    report = validate_docx(source)
    assert report["valid"] is True
    assert isinstance(report["omml"], dict)
    assert report["omml"]["equation_count"] == 1
    assert report["omml"]["structural_errors"] == []


# -- corrupt / invalid DOCX ---------------------------------------------------


def test_corrupt_zip_returns_valid_false(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"not a zip archive")
    report = validate_docx(corrupt)
    assert report["valid"] is False
    assert report["package"]["valid_zip"] is False


def test_non_docx_extension_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=".docx"):
        validate_docx(tmp_path / "notes.txt")


def test_missing_docx_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        validate_docx(tmp_path / "missing.docx")


# -- OMML structural checks ---------------------------------------------------


def test_empty_omath_is_flagged(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "empty.docx",
        content=f'<w:p><m:oMath xmlns:m="{M_NS}"/></w:p>',
    )
    report = validate_docx(source)
    assert any("Empty m:oMath" in e["error"] for e in report["omml"]["structural_errors"])


def test_fraction_missing_den_is_flagged(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "badfrac.docx",
        content=f'<w:p><m:oMath xmlns:m="{M_NS}"><m:f><m:num><m:r><m:t>x</m:t></m:r></m:num></m:f></m:oMath></w:p>',
    )
    report = validate_docx(source)
    assert any("missing num or den" in e["error"] for e in report["omml"]["structural_errors"])


def test_superscript_missing_e_is_flagged(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "badssup.docx",
        content=f'<w:p><m:oMath xmlns:m="{M_NS}"><m:sSup><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup></m:oMath></w:p>',
    )
    report = validate_docx(source)
    assert any("missing e" in e["error"] for e in report["omml"]["structural_errors"])


@pytest.mark.parametrize(
    ("label", "children", "missing"),
    [
        ("nosub", "<m:sup><m:r><m:t>n</m:t></m:r></m:sup><m:e><m:r><m:t>i</m:t></m:r></m:e>", "sub"),
        ("nosup", "<m:sub><m:r><m:t>i</m:t></m:r></m:sub><m:e><m:r><m:t>i</m:t></m:r></m:e>", "sup"),
        ("noe", "<m:sub><m:r><m:t>i</m:t></m:r></m:sub><m:sup><m:r><m:t>n</m:t></m:r></m:sup>", "e"),
    ],
)
def test_nary_missing_a_required_child_is_flagged(
    tmp_path: Path, label: str, children: str, missing: str
) -> None:
    # CT_Nary requires m:sub, m:sup and m:e (they are present but empty when
    # a bound is hidden), so an m:nary missing one is malformed the same way a
    # denominator-less m:f is — and until now it passed validation silently.
    source = make_docx_with_omml(
        tmp_path / f"badnary_{label}.docx",
        content=f'<w:p><m:oMath xmlns:m="{M_NS}"><m:nary>{children}</m:nary></m:oMath></w:p>',
    )
    report = validate_docx(source)
    assert any(f"m:nary missing {missing}" in e["error"] for e in report["omml"]["structural_errors"])


def test_generated_nary_passes_structure_validation(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "goodnary.docx",
        content=f"<w:p>{omath_for('sum(i=1,n) i')}</w:p>",
    )
    report = validate_docx(source)
    assert report["omml"]["structural_errors"] == []


def test_deep_nesting_is_flagged(tmp_path: Path) -> None:
    # Build 35 nested m:f (fraction) elements — each m:f is a math-structure layer.
    # m:num / m:den are containers, not counted toward depth.
    inner = "<m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>2</m:t></m:r></m:den>"
    wrapped = f"<m:f>{inner}</m:f>"
    for _ in range(34):
        wrapped = f"<m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den>{wrapped}</m:den></m:f>"
    source = make_docx_with_omml(
        tmp_path / "deep.docx",
        content=f'<w:p><m:oMath xmlns:m="{M_NS}">{wrapped}</m:oMath></w:p>',
    )
    report = validate_docx(source)
    assert any("depth" in w["warning"].lower() for w in report["omml"]["structural_warnings"])


def test_empty_text_run_is_counted(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "emptytext.docx",
        content=f'<w:p><m:oMath xmlns:m="{M_NS}"><m:r><m:t/></m:r></m:oMath></w:p>',
    )
    report = validate_docx(source)
    assert report["omml"]["empty_runs"] >= 1


# -- coverage layer (with review) ---------------------------------------------


def test_coverage_layer_with_review_passes_parseable_candidates(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "cov.docx",
        content=f"<w:p>{omath_for('x = 1')}</w:p>",
    )
    review = tmp_path / "candidates.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "c1",
                        "parse_status": "ok",
                        "source": "x = 1",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = validate_docx(source, review_path=review)
    assert report["coverage"]["parseable"] == 1
    assert report["coverage"]["omml_produced"] == 1
    assert report["coverage"]["failures"] == []


def test_coverage_layer_uses_linear_for_latex_delimited_candidates(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "latex.docx")
    review = tmp_path / "candidates.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "c1",
                        "parse_status": "ok",
                        "source": "$x^2 + 1$",
                        "linear": "x^2 + 1",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 16,
                        "end": 25,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = validate_docx(source, review_path=review)

    assert report["coverage"]["parseable"] == 1
    assert report["coverage"]["omml_produced"] == 1
    assert report["coverage"]["failures"] == []


def test_coverage_layer_accepts_multiline_reviewed_formula(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "multiline.docx")
    review = tmp_path / "candidates.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "c1",
                        "parse_status": "ok",
                        "source": "x = 1",
                        "linear": r"x = 1 \\ y = 2",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = validate_docx(source, review_path=review)

    assert report["coverage"]["parseable"] == 1
    assert report["coverage"]["omml_produced"] == 1
    assert report["coverage"]["failures"] == []


def test_coverage_layer_flags_unparseable_candidates(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "badcov.docx")
    review = tmp_path / "candidates.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "c1",
                        "parse_status": "ok",
                        "source": "x @ 2",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = validate_docx(source, review_path=review)
    assert report["coverage"]["failures"]
    assert report["coverage"]["failures"][0]["error_details"]["column"] >= 1


def test_validation_uses_and_reports_alias_profile(tmp_path: Path) -> None:
    alias_path = tmp_path / "engineering.json"
    alias_path.write_text(
        json.dumps({"name": "engineering", "aliases": {"ohm": "Ω"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    profile = load_alias_profile(alias_path)
    source = make_docx_with_omml(
        tmp_path / "aliases.docx",
        content=f"<w:p>{omath_for('x = 1')}</w:p>",
    )
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "profile": {"aliases": profile.metadata()},
                "candidates": [
                    {
                        "id": "a1",
                        "parse_status": "ok",
                        "source": "R = ohm",
                        "linear": "R = ohm",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 7,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = validate_docx(source, review_path=review, alias_profile=profile)

    assert report["valid"] is True
    assert report["coverage"]["parseable"] == 1
    assert report["coverage"]["omml_produced"] == 1
    assert report["inputs"]["aliases"] == str(alias_path.resolve())
    assert report["options"]["alias_profile"] == profile.metadata()

    with pytest.raises(ValueError, match="pass the same file"):
        validate_docx(source, review_path=review)


# -- CLI integration -----------------------------------------------------------


def test_validate_cli_clean_docx_exits_zero(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    code = main(["validate", str(source)])
    assert code == 0


def test_validate_cli_corrupt_docx_exits_two(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"garbage")
    code = main(["validate", str(corrupt)])
    assert code == 1  # validate_docx catches BadZipFile internally, reports valid=false


def test_validate_cli_bad_omml_exits_one(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "bad.docx",
        content=f'<w:p><m:oMath xmlns:m="{M_NS}"><m:f><m:num><m:r><m:t>x</m:t></m:r></m:num></m:f></m:oMath></w:p>',
    )
    code = main(["validate", str(source)])
    assert code == 1


def test_validate_cli_writes_report(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    report_path = tmp_path / "validation.json"
    code = main(["validate", str(source), "--report", str(report_path)])
    assert code == 0
    assert report_path.is_file()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["valid"] is True


def test_validate_cli_with_review(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "rev.docx")
    review = tmp_path / "candidates.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "v1",
                        "parse_status": "ok",
                        "source": "x^2 + 1 = 2",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 16,
                        "end": 26,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "v-report.json"
    code = main(
        [
            "validate",
            str(source),
            "--review",
            str(review),
            "--report",
            str(report_path),
        ]
    )
    assert code == 0
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["coverage"]["parseable"] == 1


def test_wps_compatibility_profile_accepts_portable_native_omml(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "wps-portable.docx",
        content=f"<w:p>{omath_for('x = 1')}</w:p>",
    )

    report = validate_docx(source, compatibility="wps")

    assert report["valid"] is True
    assert report["options"]["compatibility"] == "wps"
    compatibility = report["compatibility"]
    assert compatibility["compatible"] is True
    assert compatibility["equations"] == 1
    assert compatibility["errors"] == []


def test_wps_compatibility_profile_rejects_word_only_alignment_markers(tmp_path: Path) -> None:
    source = make_docx_with_omml(
        tmp_path / "wps-marker.docx",
        content=(
            "<w:p><m:oMath><m:eqArr><m:e><m:r><m:t>x &amp;= 1</m:t></m:r></m:e></m:eqArr></m:oMath></w:p>"
        ),
    )

    report = validate_docx(source, compatibility="wps")

    assert report["valid"] is False
    compatibility = report["compatibility"]
    assert compatibility["compatible"] is False
    assert compatibility["checks"][1] == {
        "name": "word_only_alignment_markers",
        "passed": False,
        "count": 1,
    }
    assert "literal '&' alignment marker" in compatibility["errors"][0]


def test_validate_cli_reports_wps_compatibility(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = make_docx_with_omml(
        tmp_path / "wps-cli.docx",
        content=f"<w:p>{omath_for('sqrt(x^2 + 1)')}</w:p>",
    )
    report_path = tmp_path / "wps-validation.json"

    code = main(
        [
            "validate",
            str(source),
            "--compatibility",
            "wps",
            "--report",
            str(report_path),
        ]
    )

    assert code == 0
    assert "WPS compatibility: PASS" in capsys.readouterr().out
    assert json.loads(report_path.read_text(encoding="utf-8"))["compatibility"]["compatible"] is True


# -- cross-backend (requires native XSL) --------------------------------------


@pytest.mark.native_xsl
def test_cross_backend_structure_comparison(tmp_path: Path) -> None:
    try:
        xsl_path = find_xsl()
    except FileNotFoundError:
        pytest.skip("Microsoft Office MML2OMML.XSL is not installed")

    source = make_docx(tmp_path / "cross.docx")
    review = tmp_path / "cross-review.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "x1",
                        "parse_status": "ok",
                        "source": "x = 1",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 5,
                    },
                    {
                        "id": "x2",
                        "parse_status": "ok",
                        "source": "a/(b+c)",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 7,
                    },
                    {
                        "id": "x3",
                        "parse_status": "ok",
                        "source": "sqrt(x^2+1)",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 12,
                    },
                    {
                        "id": "x4",
                        "parse_status": "ok",
                        "source": "cases(0 if x<0; 1 if x>=0)",
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 31,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    report = validate_docx(source, review_path=review, xsl_path=xsl_path)
    cb = report["cross_backend"]
    assert cb["available"] is True
    assert cb["divergences"] == 0
