from __future__ import annotations

import pytest
from lxml import etree

from mathfmt.core import M_NS, formula_to_mathml, qname
from mathfmt.omml import XML_NS, OmmlConversionError, combine_equation_array, mathml_to_omml_py, omml_to_text


def omath_for(source: str) -> etree._Element:
    return mathml_to_omml_py(formula_to_mathml(source))


def tags(source: str) -> set[str]:
    root = omath_for(source)
    return {etree.QName(e).localname for e in root.iter()}


def count_tag(source: str, local: str) -> int:
    return len(omath_for(source).xpath(f".//m:{local}", namespaces={"m": M_NS}))


# -- structure tests ----------------------------------------------------------


def test_fraction_produces_m_f() -> None:
    assert "f" in tags("a/(b+c)")
    t = omath_for("a/b")
    f = t.find(qname(M_NS, "f"))
    assert f is not None
    assert f.find(qname(M_NS, "num")) is not None
    assert f.find(qname(M_NS, "den")) is not None


def test_radical_produces_m_rad() -> None:
    assert "rad" in tags("sqrt(x^2+1)")
    rad = omath_for("sqrt(x)").find(".//m:rad", namespaces={"m": M_NS})
    assert rad is not None
    rad_pr = rad.find(qname(M_NS, "radPr"))
    assert rad_pr is not None
    deg_hide = rad_pr.find(qname(M_NS, "degHide"))
    assert deg_hide is not None
    assert deg_hide.get(qname(M_NS, "val")) == "1"


def test_superscript_produces_m_sSup() -> None:
    assert "sSup" in tags("x^3")
    ssup = omath_for("x^2").find(".//m:sSup", namespaces={"m": M_NS})
    assert ssup is not None
    assert ssup.find(qname(M_NS, "e")) is not None
    assert ssup.find(qname(M_NS, "sup")) is not None


def test_subscript_produces_m_sSub() -> None:
    assert "sSub" in tags("p1 = p2")
    ssub = omath_for("p1").find(".//m:sSub", namespaces={"m": M_NS})
    assert ssub is not None
    assert ssub.find(qname(M_NS, "e")) is not None
    assert ssub.find(qname(M_NS, "sub")) is not None


def test_chemistry_uses_plain_element_runs_and_native_subscripts() -> None:
    omath = omath_for("H2O")

    assert omath.xpath("boolean(.//m:sSub)", namespaces={"m": M_NS})
    styles = omath.xpath(".//m:rPr/m:sty/@m:val", namespaces={"m": M_NS})
    assert styles == ["p", "p"]
    assert "".join(omath.itertext()) == "H2O"


def test_annotated_reaction_arrow_produces_upper_limit() -> None:
    omath = omath_for("CaCO3 =>[heat] CaO + CO2")
    upper = omath.find(".//m:limUpp", namespaces={"m": M_NS})

    assert upper is not None
    assert "".join(upper.find("./m:e", namespaces={"m": M_NS}).itertext()) == "⇒"
    assert "".join(upper.find("./m:lim", namespaces={"m": M_NS}).itertext()) == "heat"


def test_delimited_group_produces_m_d() -> None:
    assert "d" in tags("sin(x)")


def test_limit_produces_m_limLow() -> None:
    assert "limLow" in tags("lim(p->0)")


def test_derivative_produces_m_f() -> None:
    assert "f" in tags("ds(t)/dt")


def test_partial_derivative_produces_fraction_with_partial_runs() -> None:
    omath = omath_for("∂f/∂x")
    fraction = omath.find(".//m:f", namespaces={"m": M_NS})

    assert fraction is not None
    assert "".join(fraction.find("./m:num", namespaces={"m": M_NS}).itertext()) == "∂f"
    assert "".join(fraction.find("./m:den", namespaces={"m": M_NS}).itertext()) == "∂x"


def test_tensor_indices_produce_combined_omml_script() -> None:
    assert "sSubSup" in tags("T_i^j")


@pytest.mark.parametrize(
    ("source", "delimiters"),
    [
        ("<phi|psi>", [("⟨", "⟩")]),
        ("bra(phi) ket(psi)", [("⟨", "⟩")]),
    ],
)
def test_braket_notation_produces_native_omml_delimiters(
    source: str, delimiters: list[tuple[str, str]]
) -> None:
    omath = omath_for(source)
    actual = [
        (
            item.find("./m:dPr/m:begChr", namespaces={"m": M_NS}).get(qname(M_NS, "val")),
            item.find("./m:dPr/m:endChr", namespaces={"m": M_NS}).get(qname(M_NS, "val")),
        )
        for item in omath.xpath(".//m:d", namespaces={"m": M_NS})
    ]

    assert actual == delimiters


# -- round-trip tests (all README examples) -----------------------------------


def test_all_readme_examples_produce_omath_root() -> None:
    examples = [
        "ds(t)/dt",
        "s'(t) = -s''(t)",
        "sqrt(x^2 + 1)",
        "x^3 + p1",
        "x != 0",
        "sin(x) + cos(x)",
        "lim(p->0)",
        "a/(b+c)",
        "e^(p1*t)",
        "1(t)",
        "Delta + pi",
        "x, y, z",
    ]
    for ex in examples:
        omath = omath_for(ex)
        assert etree.QName(omath).localname == "oMath", f"failed on: {ex}"
        assert len(omath) > 0, f"empty oMath for: {ex}"


# -- operator / edge case tests -----------------------------------------------


def test_invisible_times_is_skipped() -> None:
    num_runs = count_tag("a b", "r")
    assert num_runs == 2  # just a and b, no invisible-times run


def test_subscript_pPAIR_has_nested_runs() -> None:
    assert count_tag("p1,2", "r") >= 3


def test_greek_letters_are_text_runs() -> None:
    for source in ("Delta = 1", "pi > 0"):
        assert count_tag(source, "r") >= 1


def test_number_is_text_run() -> None:
    omath = omath_for("x = 42")
    runs = omath.xpath(".//m:r/m:t", namespaces={"m": M_NS})
    texts = {r.text for r in runs}
    assert "42" in texts


def test_binary_operator_is_text_run() -> None:
    omath = omath_for("a + b")
    runs = omath.xpath(".//m:r/m:t", namespaces={"m": M_NS})
    texts = [r.text for r in runs]
    assert "+" in texts
    assert texts == ["a", "+", "b"]


def test_unary_minus_is_preserved() -> None:
    omath = omath_for("-x")
    runs = omath.xpath(".//m:r/m:t", namespaces={"m": M_NS})
    assert runs[0].text == "-"
    assert runs[1].text == "x"


def test_comma_separated_sequence() -> None:
    omath = omath_for("x, y, z")
    runs = omath.xpath(".//m:r/m:t", namespaces={"m": M_NS})
    texts = [r.text for r in runs]
    assert texts == ["x", ",", "y", ",", "z"]


def test_equation_array_preserves_lines_and_aligns_relations() -> None:
    array = combine_equation_array([omath_for("a = b"), omath_for("long = d")])
    rows = array.xpath("./m:m/m:mr", namespaces={"m": M_NS})

    assert len(rows) == 2
    assert [["".join(cell.itertext()) for cell in row] for row in rows] == [
        ["a", "=b"],
        ["long", "=d"],
    ]
    justifications = array.xpath("./m:m/m:mPr/m:mcs/m:mc/m:mcPr/m:mcJc/@m:val", namespaces={"m": M_NS})
    assert justifications == ["right", "left"]


def test_equation_array_preserves_structured_math() -> None:
    array = combine_equation_array([omath_for("a / b = c"), omath_for("x^2 = y")])

    assert array.xpath("boolean(.//m:m/m:mr/m:e/m:f)", namespaces={"m": M_NS})
    assert array.xpath("boolean(.//m:m/m:mr/m:e/m:sSup)", namespaces={"m": M_NS})


def test_multiline_without_common_relations_falls_back_to_equation_array() -> None:
    array = combine_equation_array([omath_for("a + b"), omath_for("c - d")])
    rows = array.xpath("./m:eqArr/m:e", namespaces={"m": M_NS})

    assert len(rows) == 2
    assert ["".join(row.itertext()) for row in rows] == ["a+b", "c-d"]
    assert "&" not in "".join(array.itertext())


@pytest.mark.parametrize(
    "source",
    [
        "f(x) = {0, x<0; 1, x>=0}",
        "cases(0 if x<0; 1 if x>=0)",
    ],
)
def test_piecewise_produces_open_delimiter_and_two_column_matrix(source: str) -> None:
    omath = omath_for(source)
    delimiters = omath.xpath(".//m:d[m:dPr/m:begChr[@m:val='{']]", namespaces={"m": M_NS})
    delimiter = delimiters[0] if delimiters else None

    assert delimiter is not None
    assert delimiter.find("./m:dPr/m:begChr", namespaces={"m": M_NS}).get(qname(M_NS, "val")) == "{"
    assert delimiter.find("./m:dPr/m:endChr", namespaces={"m": M_NS}).get(qname(M_NS, "val")) == ""
    rows = delimiter.xpath(".//m:m/m:mr", namespaces={"m": M_NS})
    assert len(rows) == 2
    assert all(len(row.xpath("./m:e", namespaces={"m": M_NS})) == 2 for row in rows)
    assert "if\u00a0" in "".join(delimiter.itertext())


def test_piecewise_preserves_condition_spacing_for_office_suites() -> None:
    omath = omath_for("cases(0 if x<0; 1 if x>=0)")
    condition_labels = [
        node for node in omath.xpath(".//m:t", namespaces={"m": M_NS}) if (node.text or "").startswith("if")
    ]

    assert [node.text for node in condition_labels] == ["if\u00a0", "if\u00a0"]
    assert all(node.get(qname(XML_NS, "space")) == "preserve" for node in condition_labels)


def test_variable_with_numeric_suffix_is_subscript() -> None:
    assert "sSub" in tags("e0")
    assert "sSub" in tags("ep")


def test_function_application_has_delimiters() -> None:
    assert "d" in tags("exp(x)")


def test_nested_fraction() -> None:
    omath = omath_for("a/(b/c)")
    assert len(omath.xpath(".//m:f", namespaces={"m": M_NS})) == 2


# -- omml_to_text: reverse direction -------------------------------------------


def reparsed_omath(source: str) -> etree._Element:
    """Round-trip source through omml_to_text and back to an OMML tree."""
    text = omml_to_text(omath_for(source))
    return omath_for(text)


@pytest.mark.parametrize(
    "source",
    [
        "x^2 + 1 = 2",
        "a/(b+c)",
        "(a+b)/(c-d)",
        "sqrt(x^2+1)",
        "x^2",
        "p1",
        "T_i^j",
        "x^(a+b)",
        "ds(t)/dt",
        "d^2s(t)/dt^2",
        "partial(f,x)",
        "bra(phi) ket(psi)",
        "(a+b)*c",
        "[1,2,3]",
        "x != y",
        "x <= 2",
        "x >= 2",
        "x -> y",
        "x => y",
        "2 +/- 3",
        "lim(x->0) sin(x)/x",
        "H2O",
        "Ca(OH)2",
        "2H2 + O2 -> 2H2O",
        "CaCO3 =>[heat] CaO + CO2",
    ],
)
def test_omml_to_text_round_trips_to_an_equivalent_tree(source: str) -> None:
    original = omath_for(source)
    reconstructed = reparsed_omath(source)
    assert etree.tostring(reconstructed) == etree.tostring(original)


def test_omml_to_text_multiplication_boundary_is_disambiguated() -> None:
    # Two adjacent bare-identifier runs ("d" then "s(...)") must not merge into
    # one longer identifier ("ds") on reparse.
    text = omml_to_text(omath_for("ds(t)/dt"))
    assert "d*s" in text
    assert "d*t" in text


def test_omml_to_text_digit_then_letter_boundary_needs_no_star() -> None:
    # Unlike letter-then-letter, a digit followed by a letter is never
    # ambiguous to the tokenizer (NUMBER stops at the first non-digit), so the
    # ordinary coefficient shorthand round-trips without an inserted "*".
    assert omml_to_text(omath_for("2x")) == "2x"


def test_omml_to_text_rejects_matrix_and_piecewise() -> None:
    with pytest.raises(OmmlConversionError, match="m:m"):
        omml_to_text(omath_for("cases(x^2 if x>=0; -x if x<0)"))


def test_omml_to_text_rejects_non_omath_root() -> None:
    with pytest.raises(OmmlConversionError, match="oMath"):
        omml_to_text(etree.Element(qname(M_NS, "r")))


def test_omml_to_text_rejects_unknown_element() -> None:
    omath = etree.Element(qname(M_NS, "oMath"))
    etree.SubElement(omath, qname(M_NS, "nary"))
    with pytest.raises(OmmlConversionError, match="m:nary"):
        omml_to_text(omath)


def test_omml_to_text_rejects_nth_root() -> None:
    omath = etree.Element(qname(M_NS, "oMath"))
    rad = etree.SubElement(omath, qname(M_NS, "rad"))
    deg = etree.SubElement(rad, qname(M_NS, "deg"))
    deg_run = etree.SubElement(deg, qname(M_NS, "r"))
    etree.SubElement(deg_run, qname(M_NS, "t")).text = "3"
    e = etree.SubElement(rad, qname(M_NS, "e"))
    e_run = etree.SubElement(e, qname(M_NS, "r"))
    etree.SubElement(e_run, qname(M_NS, "t")).text = "x"

    with pytest.raises(OmmlConversionError, match="nth-root"):
        omml_to_text(omath)


def test_omml_to_text_rejects_unrecognized_lim_base() -> None:
    omath = etree.Element(qname(M_NS, "oMath"))
    lim_low = etree.SubElement(omath, qname(M_NS, "limLow"))
    e = etree.SubElement(lim_low, qname(M_NS, "e"))
    e_run = etree.SubElement(e, qname(M_NS, "r"))
    etree.SubElement(e_run, qname(M_NS, "t")).text = "max"  # not "lim" or an arrow
    lim = etree.SubElement(lim_low, qname(M_NS, "lim"))
    lim_run = etree.SubElement(lim, qname(M_NS, "r"))
    etree.SubElement(lim_run, qname(M_NS, "t")).text = "x->0"

    with pytest.raises(OmmlConversionError, match="limLow"):
        omml_to_text(omath)


@pytest.mark.parametrize(
    ("source", "expected_text"),
    [
        ("H2O", "H2O"),
        ("Ca(OH)2", "Ca(OH)2"),
        ("2H2 + O2 -> 2H2O", "2H2+O2->2H2O"),
    ],
)
def test_omml_to_text_chemistry_reconstructs_in_bare_form(source: str, expected_text: str) -> None:
    # A chemistry element/count reconstructs without an underscore (H2, not
    # H_2) so it re-triggers the chemistry grammar on reparse and keeps its
    # upright styling, rather than falling back to an italic generic subscript.
    assert omml_to_text(omath_for(source)) == expected_text


def test_omml_to_text_non_chemistry_group_subscript_still_uses_underscore() -> None:
    # `_is_chemistry_group` must not fire for an ordinary (non-upright) group,
    # only for the plain/upright-styled runs MathFmt's chemistry grammar
    # produces — otherwise a genuine grouped-expression subscript would lose
    # its `_` and silently reparse as multiplication instead.
    omath = etree.Element(qname(M_NS, "oMath"))
    ssub = etree.SubElement(omath, qname(M_NS, "sSub"))
    base = etree.SubElement(ssub, qname(M_NS, "e"))
    group = etree.SubElement(base, qname(M_NS, "d"))
    group_e = etree.SubElement(group, qname(M_NS, "e"))
    run = etree.SubElement(group_e, qname(M_NS, "r"))  # no rPr/sty -> not chemistry-plain
    etree.SubElement(run, qname(M_NS, "t")).text = "a"
    sub = etree.SubElement(ssub, qname(M_NS, "sub"))
    sub_run = etree.SubElement(sub, qname(M_NS, "r"))
    etree.SubElement(sub_run, qname(M_NS, "t")).text = "2"

    # `_emit_operand` also over-parenthesizes any non-atomic operand (see its
    # docstring), so the non-chemistry fallback doubles the group's own parens.
    assert omml_to_text(omath) == "((a))_2"
