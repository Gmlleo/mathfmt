from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from mathfmt.aliases import load_alias_profile
from mathfmt.cli import main
from mathfmt.core import M_NS, NS, W_NS, apply_docx, find_xsl, paragraph_text, scan_docx
from tests.helpers import make_docx, make_fake_xsl


def document_with_body(body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:m="{M_NS}"><w:body>{body}</w:body></w:document>"""


def test_scan_reports_supported_parts_and_skips(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    report_path = tmp_path / "candidates.json"
    report = scan_docx(source, report_path)

    assert report["summary"]["existing_equations"] == 1
    assert report["summary"]["drawing_paragraphs"] == 1
    assert report["summary"]["code_paragraphs"] == 1
    parts = {candidate["part"] for candidate in report["candidates"]}
    assert {"word/document.xml", "word/header1.xml", "word/footer1.xml"} <= parts
    assert all(candidate["parse_status"] == "ok" for candidate in report["candidates"])


def test_apply_creates_omml_without_overwriting_source(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    original = source.read_bytes()
    review = tmp_path / "review.json"
    result_path = tmp_path / "result.json"
    output = tmp_path / "output.docx"
    xsl = make_fake_xsl(tmp_path / "fake.xsl")

    scanned = scan_docx(source, review)
    result = apply_docx(source, review, output, result_path, xsl)

    assert source.read_bytes() == original
    assert output.is_file()
    # With confidence scoring, only "high" candidates are selected by default
    assert result["converted_count"] >= 1
    assert scanned["summary"]["candidates"] >= 1
    assert any(item["lines"] > 1 for item in result["converted"])
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    assert len(root.xpath(".//m:oMath", namespaces=NS)) >= 3
    assert root.xpath(".//w:br", namespaces=NS)
    assert json.loads(result_path.read_text(encoding="utf-8"))["converted_count"] > 0


def test_apply_writes_v3_conversion_report_schema(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    review = tmp_path / "review.json"
    result_path = tmp_path / "result.json"
    output = tmp_path / "output.docx"

    scan_docx(source, review)
    result = apply_docx(source, review, output, result_path, xsl_path=None)
    saved = json.loads(result_path.read_text(encoding="utf-8"))

    assert result["schema_version"] == 3
    assert saved["schema_version"] == 3
    assert saved["report_type"] == "conversion"
    assert saved["command"]["name"] == "apply"
    assert saved["inputs"]["docx"] == str(source.resolve())
    assert saved["inputs"]["review"] == str(review.resolve())
    assert saved["outputs"]["docx"] == str(output.resolve())
    assert saved["outputs"]["report"] == str(result_path.resolve())
    assert saved["options"]["backend"] == "python"
    assert saved["summary"]["selected"] >= saved["summary"]["converted"]
    assert saved["summary"]["converted"] == saved["converted_count"]
    assert saved["summary"]["skipped"] == saved["skipped_count"]
    assert saved["formulas"]
    assert {item["status"] for item in saved["formulas"]} == {"converted"}


def test_apply_dry_run_writes_report_without_docx_output(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    original = source.read_bytes()
    review = tmp_path / "review.json"
    result_path = tmp_path / "result.json"
    output = tmp_path / "output.docx"

    scan_docx(source, review)
    result = apply_docx(source, review, output, result_path, xsl_path=None, dry_run=True)
    saved = json.loads(result_path.read_text(encoding="utf-8"))

    assert source.read_bytes() == original
    assert not output.exists()
    assert result["converted_count"] > 0
    assert saved["options"]["dry_run"] is True
    assert saved["summary"]["dry_run"] is True
    assert saved["summary"]["output_written"] is False
    assert saved["summary"]["converted"] == saved["converted_count"]


def test_apply_strict_skips_docx_output_when_selected_formula_fails(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    review = tmp_path / "review.json"
    output = tmp_path / "output.docx"
    result_path = tmp_path / "result.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "stale",
                        "selected": True,
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 5,
                        "source": "wrong",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = apply_docx(source, review, output, result_path, xsl_path=None, strict=True)
    saved = json.loads(result_path.read_text(encoding="utf-8"))

    assert not output.exists()
    assert result["skipped_count"] == 1
    assert saved["options"]["strict"] is True
    assert saved["summary"]["strict_failed"] is True
    assert saved["summary"]["output_written"] is False


def test_refuses_to_overwrite_input(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    review = tmp_path / "review.json"
    scan_docx(source, review)
    with pytest.raises(ValueError, match="overwrite"):
        apply_docx(source, review, source, tmp_path / "result.json", make_fake_xsl(tmp_path / "fake.xsl"))


def test_convert_command_uses_safe_defaults(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    xsl = make_fake_xsl(tmp_path / "fake.xsl")
    assert main(["convert", str(source), "--xsl", str(xsl)]) == 0
    assert (tmp_path / "source.mathfmt.docx").is_file()
    report_path = tmp_path / "source.mathfmt.report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 3
    assert report["command"]["name"] == "convert"


def test_explicit_missing_xsl_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found at"):
        find_xsl(tmp_path / "missing.xsl")


@pytest.mark.native_xsl
def test_native_xsl_when_available(tmp_path: Path) -> None:
    try:
        xsl = find_xsl()
    except FileNotFoundError:
        pytest.skip("Microsoft Office MML2OMML.XSL is not installed")
    source = make_docx(tmp_path / "source.docx")
    review = tmp_path / "review.json"
    output = tmp_path / "native.docx"
    scan_docx(source, review)
    result = apply_docx(source, review, output, tmp_path / "native.json", xsl)
    assert result["converted_count"] > 0
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    assert root.xpath(".//m:oMath", namespaces={"m": M_NS})


def test_scan_validates_input_and_corrupt_archives(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=".docx"):
        scan_docx(tmp_path / "notes.txt", tmp_path / "report.json")
    with pytest.raises(FileNotFoundError, match="not found"):
        scan_docx(tmp_path / "missing.docx", tmp_path / "report.json")
    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"not a zip archive")
    with pytest.raises(zipfile.BadZipFile):
        scan_docx(corrupt, tmp_path / "report.json")


def test_scan_records_empty_pict_and_unparseable_formula(tmp_path: Path) -> None:
    document = document_with_body(
        """
        <w:p><w:r><w:t>   </w:t></w:r></w:p>
        <w:p><w:r><w:pict/></w:r><w:r><w:t>x = 1</w:t></w:r></w:p>
        <w:p><w:r><w:t>x = +</w:t></w:r></w:p>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    report = scan_docx(source, tmp_path / "report.json")
    assert report["summary"]["drawing_paragraphs"] == 1
    assert report["candidates"][0]["parse_status"] == "review"
    assert report["candidates"][0]["selected"] is False
    assert report["candidates"][0]["parse_error"]
    assert report["candidates"][0]["parse_error_details"]["column"] >= 1
    assert report["candidates"][0]["parse_error_details"]["expected"]


def test_scan_reports_latex_delimited_formulas(tmp_path: Path) -> None:
    document = document_with_body(
        """
        <w:p><w:r><w:t>Inline formula $x^2 + 1$ in prose.</w:t></w:r></w:p>
        <w:p><w:r><w:t>$$y = 2$$</w:t></w:r></w:p>
        <w:p><w:r><w:t>The price is $12.00$ today.</w:t></w:r></w:p>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    report = scan_docx(source, tmp_path / "report.json")
    candidates = [candidate for candidate in report["candidates"] if candidate["part"] == "word/document.xml"]

    assert len(candidates) == 2
    assert candidates[0]["source"] == "$x^2 + 1$"
    assert candidates[0]["linear"] == "x^2 + 1"
    assert candidates[0]["selected"] is True
    assert candidates[0]["confidence_reason"] == "explicit LaTeX delimiter"
    assert candidates[0]["explicit"] is True
    assert candidates[0]["display"] is False
    assert candidates[1]["source"] == "$$y = 2$$"
    assert candidates[1]["linear"] == "y = 2"
    assert candidates[1]["display"] is True


def test_apply_latex_delimited_formulas_remove_delimiters(tmp_path: Path) -> None:
    document = document_with_body(
        """
        <w:p><w:r><w:t>Inline formula $x^2 + 1$ in prose.</w:t></w:r></w:p>
        <w:p><w:r><w:t>$$y = 2$$</w:t></w:r></w:p>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    review = tmp_path / "review.json"
    output = tmp_path / "output.docx"
    scan_docx(source, review)

    result = apply_docx(source, review, output, tmp_path / "result.json", xsl_path=None)

    assert result["converted_count"] == 2
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    paragraphs = root.xpath(".//w:p", namespaces=NS)
    assert "$" not in paragraph_text(paragraphs[0])
    assert paragraph_text(paragraphs[0]) == "Inline formula  in prose."
    assert paragraphs[0].xpath(".//m:oMath", namespaces=NS)
    assert paragraphs[1].xpath("./m:oMathPara/m:oMath", namespaces=NS)


def test_scan_and_apply_piecewise_formulas_in_inline_and_display_contexts(tmp_path: Path) -> None:
    document = document_with_body(
        """
        <w:p><w:r><w:t>Function: $f(x) = {0, x&lt;0; 1, x>=0}$ done.</w:t></w:r></w:p>
        <w:p><w:r><w:t>$$cases(0 if x&lt;0; 1 if x>=0)$$</w:t></w:r></w:p>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    review = tmp_path / "review.json"
    output = tmp_path / "output.docx"

    report = scan_docx(source, review)
    candidates = [candidate for candidate in report["candidates"] if candidate["part"] == "word/document.xml"]

    assert len(candidates) == 2
    assert all(candidate["parse_status"] == "ok" for candidate in candidates)
    assert all(candidate["selected"] for candidate in candidates)
    result = apply_docx(source, review, output, tmp_path / "result.json", xsl_path=None)
    assert result["converted_count"] == 2

    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    paragraphs = root.xpath(".//w:p", namespaces=NS)
    assert paragraph_text(paragraphs[0]) == "Function:  done."
    assert paragraphs[0].xpath("./m:oMath/m:d/m:e/m:m", namespaces=NS)
    assert paragraphs[1].xpath("./m:oMathPara/m:oMath/m:d/m:e/m:m", namespaces=NS)
    rows = root.xpath(".//m:d/m:e/m:m/m:mr", namespaces=NS)
    assert len(rows) == 4
    assert all(len(row.xpath("./m:e", namespaces=NS)) == 2 for row in rows)


def test_scan_and_apply_chemistry_with_conservative_single_element_selection(tmp_path: Path) -> None:
    document = document_with_body(
        """
        <w:p><w:r><w:t>Water is H2O and salt is NaCl.</w:t></w:r></w:p>
        <w:p><w:r><w:t>2H2 + O2 -> 2H2O</w:t></w:r></w:p>
        <w:p><w:r><w:t>Oxygen label O2.</w:t></w:r></w:p>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    review = tmp_path / "review.json"
    output = tmp_path / "output.docx"

    report = scan_docx(source, review)
    candidates = [candidate for candidate in report["candidates"] if candidate["part"] == "word/document.xml"]
    by_source = {candidate["source"]: candidate for candidate in candidates}

    assert {"H2O", "NaCl", "2H2 + O2 -> 2H2O", "O2"} == set(by_source)
    assert all(by_source[source]["selected"] for source in ("H2O", "NaCl", "2H2 + O2 -> 2H2O"))
    assert by_source["O2"]["confidence"] == "medium"
    assert by_source["O2"]["selected"] is False
    assert all(candidate["chemistry"] for candidate in candidates)

    result = apply_docx(source, review, output, tmp_path / "result.json", xsl_path=None)

    assert result["converted_count"] == 3
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    paragraphs = root.xpath(".//w:p", namespaces=NS)
    assert len(paragraphs[0].xpath("./m:oMath", namespaces=NS)) == 2
    prefix = paragraphs[0].find("./w:r/w:t", namespaces=NS)
    assert prefix is not None
    assert prefix.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"
    assert paragraphs[1].xpath("./m:oMathPara/m:oMath", namespaces=NS)
    assert not paragraphs[2].xpath(".//m:oMath", namespaces=NS)
    assert root.xpath(".//m:sSub", namespaces=NS)
    assert root.xpath(".//m:rPr/m:sty[@m:val='p']", namespaces=NS)


def test_scan_and_apply_physics_notation_with_reviewable_ambiguity(tmp_path: Path) -> None:
    document = document_with_body(
        """
        <w:p><w:r><w:t>Unicode derivative: ∂f/∂x.</w:t></w:r></w:p>
        <w:p><w:r><w:t>ASCII derivative: partial g / partial t.</w:t></w:r></w:p>
        <w:p><w:r><w:t>Tensor T_i^j and state &lt;phi|psi&gt;.</w:t></w:r></w:p>
        <w:p><w:r><w:t>Bra-ket functions bra(phi) ket(psi).</w:t></w:r></w:p>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    review = tmp_path / "review.json"
    output = tmp_path / "output.docx"

    report = scan_docx(source, review)
    candidates = [candidate for candidate in report["candidates"] if candidate["part"] == "word/document.xml"]
    by_source = {candidate["source"]: candidate for candidate in candidates}

    assert set(by_source) == {"∂f/∂x", "partial g / partial t", "T_i^j", "<phi|psi>", "bra(phi) ket(psi)"}
    assert by_source["∂f/∂x"]["confidence"] == "high"
    assert by_source["∂f/∂x"]["selected"] is True
    for formula in ("partial g / partial t", "T_i^j", "<phi|psi>", "bra(phi) ket(psi)"):
        assert by_source[formula]["confidence"] == "medium"
        assert by_source[formula]["selected"] is False
        by_source[formula]["selected"] = True
    assert all(candidate["physics"] for candidate in candidates)
    review.write_text(json.dumps(report), encoding="utf-8")

    result = apply_docx(source, review, output, tmp_path / "result.json", xsl_path=None)

    assert result["converted_count"] == 5
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    assert len(root.xpath(".//m:f", namespaces=NS)) == 2
    assert len(root.xpath(".//m:sSubSup", namespaces=NS)) == 1
    assert len(root.xpath(".//m:d", namespaces=NS)) == 2


def test_scan_and_apply_with_symbol_alias_profile(tmp_path: Path) -> None:
    alias_path = tmp_path / "engineering.json"
    alias_path.write_text(
        json.dumps({"name": "engineering", "aliases": {"ohm": "Ω"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    profile = load_alias_profile(alias_path)
    source = make_docx(
        tmp_path / "source.docx",
        document_xml=document_with_body("<w:p><w:r><w:t>Resistance: $R = ohm$.</w:t></w:r></w:p>"),
    )
    review = tmp_path / "review.json"
    output = tmp_path / "output.docx"
    result_path = tmp_path / "result.json"

    scanned = scan_docx(source, review, alias_profile=profile)
    candidate = next(item for item in scanned["candidates"] if item["source"] == "$R = ohm$")

    assert candidate["parse_status"] == "ok"
    assert candidate["selected"] is True
    assert scanned["profile"]["aliases"] == profile.metadata()

    result = apply_docx(
        source,
        review,
        output,
        result_path,
        xsl_path=None,
        alias_profile=profile,
    )

    assert result["converted_count"] == 1
    assert result["inputs"]["aliases"] == str(alias_path.resolve())
    assert result["options"]["alias_profile"] == profile.metadata()
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    assert "Ω" in "".join(root.xpath(".//m:t/text()", namespaces=NS))


def test_apply_rejects_missing_or_mismatched_review_alias_profile(tmp_path: Path) -> None:
    first_path = tmp_path / "first.json"
    first_path.write_text(
        json.dumps({"name": "first", "aliases": {"ohm": "Ω"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    second_path = tmp_path / "second.json"
    second_path.write_text(
        json.dumps({"name": "second", "aliases": {"ohm": "Ω"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    first = load_alias_profile(first_path)
    second = load_alias_profile(second_path)
    source = make_docx(
        tmp_path / "source.docx",
        document_xml=document_with_body("<w:p><w:r><w:t>$R = ohm$</w:t></w:r></w:p>"),
    )
    review = tmp_path / "review.json"
    scan_docx(source, review, alias_profile=first)

    with pytest.raises(ValueError, match="pass the same file"):
        apply_docx(source, review, tmp_path / "none.docx", tmp_path / "none.json")
    with pytest.raises(ValueError, match="does not match"):
        apply_docx(
            source,
            review,
            tmp_path / "wrong.docx",
            tmp_path / "wrong.json",
            alias_profile=second,
        )


def test_scan_accepts_multiline_latex_delimited_formula(tmp_path: Path) -> None:
    formula = r"$$a = b \\ c = d$$"
    document = document_with_body(f"<w:p><w:r><w:t>{formula}</w:t></w:r></w:p>")
    source = make_docx(tmp_path / "source.docx", document_xml=document)

    report = scan_docx(source, tmp_path / "report.json")
    candidate = next(c for c in report["candidates"] if c["part"] == "word/document.xml")

    assert candidate["parse_status"] == "ok"
    assert candidate["selected"] is True
    assert candidate["multiline"] is True
    assert candidate["line_count"] == 2


def test_apply_multiline_formulas_in_inline_display_and_table_contexts(tmp_path: Path) -> None:
    document = document_with_body(
        """
        <w:p><w:r><w:t>Before a = b after</w:t></w:r></w:p>
        <w:p><w:r><w:t>x = y</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>m = n</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "inline",
                        "selected": True,
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 7,
                        "end": 12,
                        "source": "a = b",
                        "linear": r"a = b \\ c = d",
                        "display": False,
                    },
                    {
                        "id": "display",
                        "selected": True,
                        "part": "word/document.xml",
                        "paragraph_index": 1,
                        "start": 0,
                        "end": 5,
                        "source": "x = y",
                        "linear": "x = y\nz = w",
                        "display": True,
                    },
                    {
                        "id": "table",
                        "selected": True,
                        "part": "word/document.xml",
                        "paragraph_index": 2,
                        "start": 0,
                        "end": 5,
                        "source": "m = n",
                        "linear": r"m = n \\ p = q",
                        "display": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output.docx"

    result = apply_docx(source, review, output, tmp_path / "result.json", xsl_path=None)

    assert result["converted_count"] == 3
    assert {item["layout"] for item in result["converted"]} == {"equation_array"}
    assert {item["lines"] for item in result["converted"]} == {2}
    assert all(item["multiline"] for item in result["formulas"])
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    arrays = root.xpath(".//m:m[m:mPr/m:mcs]", namespaces=NS)
    assert len(arrays) == 3
    assert all(len(array.xpath("./m:mr", namespaces=NS)) == 2 for array in arrays)
    paragraphs = root.xpath(".//w:p", namespaces=NS)
    assert paragraph_text(paragraphs[0]) == "Before  after"
    assert paragraphs[0].xpath("./m:oMath/m:m", namespaces=NS)
    assert paragraphs[1].xpath("./m:oMathPara/m:oMath/m:m", namespaces=NS)
    assert paragraphs[2].xpath("ancestor::w:tc", namespaces=NS)
    assert paragraphs[2].xpath("./m:oMath/m:m", namespaces=NS)
    assert paragraphs[2].xpath(".//w:sz[@w:val='16']", namespaces=NS)


def test_apply_preserves_mixed_text_across_runs(tmp_path: Path) -> None:
    document = document_with_body(
        """
        <w:p>
          <w:r><w:t xml:space="preserve">Before </w:t></w:r>
          <w:r><w:rPr><w:b/></w:rPr><w:t>x^2</w:t></w:r>
          <w:r><w:t xml:space="preserve"> = 4</w:t></w:r>
          <w:r><w:t xml:space="preserve"> after</w:t></w:r>
        </w:p>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "mixed",
                        "selected": True,
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 7,
                        "end": 14,
                        "source": "x^2 = 4",
                        "linear": "x^2 = 4",
                        "display": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output.docx"
    result = apply_docx(
        source,
        review,
        output,
        tmp_path / "result.json",
        make_fake_xsl(tmp_path / "fake.xsl"),
    )
    assert result["converted_count"] == 1
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    paragraph = root.xpath(".//w:p", namespaces=NS)[0]
    assert paragraph_text(paragraph) == "Before  after"
    assert paragraph.xpath(".//m:oMath", namespaces=NS)


def test_apply_preserves_single_run_suffix_formatting(tmp_path: Path) -> None:
    document = document_with_body("<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Before x = 1 after</w:t></w:r></w:p>")
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "styled",
                        "selected": True,
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 7,
                        "end": 12,
                        "source": "x = 1",
                        "display": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output.docx"
    apply_docx(
        source,
        review,
        output,
        tmp_path / "result.json",
        make_fake_xsl(tmp_path / "fake.xsl"),
    )
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    suffix = root.xpath(".//w:r[w:t=' after']", namespaces=NS)
    assert suffix and suffix[0].xpath("boolean(./w:rPr/w:b)", namespaces=NS)


def test_apply_reports_stale_and_invalid_review_locations(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    review = tmp_path / "review.json"
    candidates = [
        {
            "id": "missing-part",
            "selected": True,
            "part": "word/missing.xml",
            "paragraph_index": 0,
            "start": 0,
            "end": 1,
            "source": "x",
        },
        {
            "id": "missing-paragraph",
            "selected": True,
            "part": "word/header1.xml",
            "paragraph_index": 99,
            "start": 0,
            "end": 1,
            "source": "x",
        },
        {
            "id": "stale",
            "selected": True,
            "part": "word/footer1.xml",
            "paragraph_index": 0,
            "start": 0,
            "end": 5,
            "source": "wrong",
        },
    ]
    review.write_text(json.dumps({"candidates": candidates}), encoding="utf-8")
    result = apply_docx(
        source,
        review,
        tmp_path / "output.docx",
        tmp_path / "result.json",
        make_fake_xsl(tmp_path / "fake.xsl"),
    )
    assert result["converted_count"] == 0
    assert result["skipped_count"] == 3
    errors = {item["id"]: item["error"] for item in result["skipped"]}
    assert "part not found" in errors["missing-part"]
    assert "index out of range" in errors["missing-paragraph"]
    assert "no longer matches" in errors["stale"]
    formulas = {item["id"]: item for item in result["formulas"]}
    assert formulas["missing-part"]["status"] == "skipped"
    assert formulas["stale"]["status"] == "failed"
    assert formulas["stale"]["warnings"][0]["code"] == "conversion_failed"


def test_apply_report_includes_parse_error_details_for_failed_formula(tmp_path: Path) -> None:
    document = document_with_body("<w:p><w:r><w:t>x = 1</w:t></w:r></w:p>")
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    review = tmp_path / "review.json"
    result_path = tmp_path / "result.json"
    review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "bad-linear",
                        "selected": True,
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 5,
                        "source": "x = 1",
                        "linear": "x +",
                        "display": False,
                        "confidence": "high",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = apply_docx(source, review, tmp_path / "output.docx", result_path, xsl_path=None)
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    formula = saved["formulas"][0]

    assert result["skipped_count"] == 1
    assert saved["summary"]["failed"] == 1
    assert saved["summary"]["warnings"] == 1
    assert formula["status"] == "failed"
    assert formula["warnings"][0]["code"] == "conversion_failed"
    assert formula["error_details"]["column"] == 4
    assert formula["error_details"]["expected"]


def test_apply_rejects_invalid_extensions_and_nested_hyperlink(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    review = tmp_path / "review.json"
    review.write_text('{"candidates": []}', encoding="utf-8")
    xsl = make_fake_xsl(tmp_path / "fake.xsl")
    with pytest.raises(ValueError, match="must be .docx"):
        apply_docx(source, review, tmp_path / "output.txt", tmp_path / "result.json", xsl)

    nested_document = document_with_body("<w:p><w:hyperlink><w:r><w:t>x = 1</w:t></w:r></w:hyperlink></w:p>")
    nested = make_docx(tmp_path / "nested.docx", document_xml=nested_document)
    nested_review = tmp_path / "nested.json"
    nested_review.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "nested",
                        "selected": True,
                        "part": "word/document.xml",
                        "paragraph_index": 0,
                        "start": 0,
                        "end": 5,
                        "source": "x = 1",
                        "display": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = apply_docx(
        nested,
        nested_review,
        tmp_path / "nested-output.docx",
        tmp_path / "nested-result.json",
        xsl,
    )
    assert result["skipped_count"] == 1
    assert "hyperlink" in result["skipped"][0]["error"]


def test_unselected_candidates_leave_document_unchanged(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    review = tmp_path / "review.json"
    scanned = scan_docx(source, review)
    for candidate in scanned["candidates"]:
        candidate["selected"] = False
    review.write_text(json.dumps(scanned), encoding="utf-8")
    result = apply_docx(
        source,
        review,
        tmp_path / "output.docx",
        tmp_path / "result.json",
        make_fake_xsl(tmp_path / "fake.xsl"),
    )
    assert result["converted_count"] == result["skipped_count"] == 0


def test_apply_with_python_backend_produces_omml(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    review = tmp_path / "review.json"
    scan_docx(source, review)
    output = tmp_path / "output.docx"
    result = apply_docx(
        source,
        review,
        output,
        tmp_path / "result.json",
        xsl_path=None,
    )
    assert result["converted_count"] > 0
    assert result["skipped_count"] == 0
    assert result["xsl"] is None
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    assert root.xpath(".//m:oMath", namespaces=NS)


def test_convert_without_xsl_flag_does_not_crash(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "source.docx")
    code = main(["convert", str(source), "--output", str(tmp_path / "out.docx")])
    assert code in (0, 2)
    assert (tmp_path / "out.docx").is_file()


def test_scan_grades_latex_delimiters_high_and_bare_macros_medium(tmp_path: Path) -> None:
    document = document_with_body(
        r"""
        <w:p><w:r><w:t>由此可得 \(\frac{a}{b}\) 成立。</w:t></w:r></w:p>
        <w:p><w:r><w:t>样本均值记为 \bar{x}。</w:t></w:r></w:p>
        <w:p><w:r><w:t>文件位于 C:\Users\gml85 目录。</w:t></w:r></w:p>
        """
    )
    source = make_docx(tmp_path / "source.docx", document_xml=document)
    report = scan_docx(source, tmp_path / "report.json")
    candidates = [c for c in report["candidates"] if c["part"] == "word/document.xml"]
    by_source = {c["source"]: c for c in candidates}

    delimited = by_source[r"\(\frac{a}{b}\)"]
    assert delimited["confidence"] == "high"
    assert delimited["selected"] is True
    assert delimited["parse_status"] == "ok"

    # A bare macro is real notation but the author did not mark it as math, so
    # it lands in the review list instead of being converted unattended.
    bare = by_source[r"\bar{x}"]
    assert bare["confidence"] == "medium"
    assert bare["selected"] is False
    assert bare["parse_status"] == "ok"

    assert not any("Users" in candidate["source"] for candidate in candidates)
