from __future__ import annotations

import inspect

import mathfmt


def test_stable_public_api_exports() -> None:
    assert mathfmt.__all__ == [
        "AliasProfile",
        "DocxSecurityError",
        "FormulaCandidate",
        "FormulaError",
        "FormulaRecognizer",
        "OmmlConversionError",
        "RecognizerError",
        "UpdateInfo",
        "__version__",
        "apply_docx",
        "check_for_updates",
        "find_xsl",
        "formula_to_mathml",
        "load_alias_profile",
        "load_recognizer",
        "mathml_to_omml",
        "mathml_to_omml_py",
        "omml_to_text",
        "scan_docx",
        "validate_docx",
    ]


def test_stable_public_api_signatures() -> None:
    expected = {
        "formula_to_mathml": "(source: 'str', aliases: 'Mapping[str, str] | None' = None) -> 'etree._Element'",
        "mathml_to_omml": "(math: 'etree._Element', transform: 'etree.XSLT | None' = None) -> 'etree._Element'",
        "omml_to_text": "(omath_elem: 'etree._Element') -> 'str'",
        "scan_docx": "(input_path: 'Path', report_path: 'Path', alias_profile: 'AliasProfile | None' = None, *, recognizers: 'Sequence[FormulaRecognizer]' = ()) -> 'dict[str, object]'",
        "apply_docx": "(input_path: 'Path', review_path: 'Path', output_path: 'Path', result_path: 'Path', xsl_path: 'Path | None' = None, *, command_name: 'str' = 'apply', dry_run: 'bool' = False, strict: 'bool' = False, alias_profile: 'AliasProfile | None' = None) -> 'dict[str, object]'",
        "validate_docx": "(input_path: 'Path', *, review_path: 'Path | None' = None, xsl_path: 'Path | None' = None, alias_profile: 'AliasProfile | None' = None, compatibility: 'str | None' = None) -> 'dict[str, object]'",
        "find_xsl": "(explicit: 'Path | None' = None) -> 'Path'",
        "check_for_updates": "(include_prerelease: 'bool' = False, force: 'bool' = False) -> 'UpdateInfo'",
        "load_alias_profile": "(path: 'Path') -> 'AliasProfile'",
        "load_recognizer": "(spec: 'str') -> 'FormulaRecognizer'",
    }
    assert {name: str(inspect.signature(getattr(mathfmt, name))) for name in expected} == expected
