from __future__ import annotations

import pytest
from lxml import etree

from mathfmt.accents import ACCENT_NAMES, ACCENTS, OMML_ACCENT_CHARS
from mathfmt.core import ACCENT_CHARS, M_NS, formula_to_mathml, qname
from mathfmt.nary import (
    FALLBACK_NARY_CHAR,
    NARY_CHARS,
    NARY_NAMES,
    NARY_OPERATORS,
    OMML_IMPLIED_NARY_CHAR,
)
from mathfmt.omml import (
    XML_NS,
    OmmlConversionError,
    combine_equation_array,
    mathml_to_omml_py,
    omml_to_text,
)


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
    # A square root's m:deg must be present (Word writes it even when hidden)
    # but empty — this is exactly what the "sqrt" branch of the nth-root
    # reversal test below relies on to distinguish it from a visible degree.
    deg = rad.find(qname(M_NS, "deg"))
    assert deg is not None
    assert len(deg) == 0


def test_nth_root_produces_m_rad_with_visible_degree() -> None:
    # root(x,3) must not fall through omml.py's unknown-MathML-tag flatten
    # fallback (mroot wasn't in MATHML_TAGS): that fallback silently drops the
    # radical and emits the base and degree as plain adjacent runs ("x3"),
    # which also regresses discoverability — before root() existed, the
    # unconverted call read literally as "root(x,3)" in Word, now it would
    # silently read as "x times 3".
    rad = omath_for("root(x,3)").find(".//m:rad", namespaces={"m": M_NS})
    assert rad is not None
    rad_pr = rad.find(qname(M_NS, "radPr"))
    assert rad_pr is not None
    deg_hide = rad_pr.find(qname(M_NS, "degHide"))
    assert deg_hide is not None
    assert deg_hide.get(qname(M_NS, "val")) == "0"
    deg = rad.find(qname(M_NS, "deg"))
    assert deg is not None
    assert "".join(deg.itertext()) == "3"
    e = rad.find(qname(M_NS, "e"))
    assert e is not None
    assert "".join(e.itertext()) == "x"
    # m:deg must precede m:e — OMML's CT_Rad fixes that child order.
    assert list(rad).index(deg) < list(rad).index(e)


@pytest.mark.parametrize("child_texts", [("x",), ()])
def test_root_rejects_malformed_child_count(child_texts: tuple[str, ...]) -> None:
    # mathml_to_omml_py is public API and can be handed foreign MathML — a
    # malformed mroot (missing its degree) must raise cleanly, not IndexError.
    mroot = etree.Element("mroot")
    for text in child_texts:
        etree.SubElement(mroot, "mi").text = text
    math = etree.Element("math")
    math.append(mroot)

    with pytest.raises(OmmlConversionError, match="requires a base and a degree"):
        mathml_to_omml_py(math)


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


def test_accent_produces_m_acc() -> None:
    root = omath_for("accent(x,bar)")
    acc = root.find(f".//{{{M_NS}}}acc")
    assert acc is not None
    chr_el = acc.find(f"{{{M_NS}}}accPr/{{{M_NS}}}chr")
    assert chr_el is not None
    # U+0305 COMBINING OVERLINE — Word's mark, not MathML's spacing U+203E.
    assert chr_el.get(qname(M_NS, "val")) == "̅"
    assert acc.find(f"{{{M_NS}}}e") is not None
    assert "".join(acc.find(f"{{{M_NS}}}e").itertext()) == "x"


@pytest.mark.parametrize(
    ("source", "char"),
    [
        ("accent(x,bar)", "̅"),
        ("accent(y,hat)", "̂"),
        ("accent(F,vec)", "⃗"),
        ("accent(q,dot)", "̇"),
        ("accent(q,ddot)", "̈"),
    ],
)
def test_accent_uses_word_combining_marks(source: str, char: str) -> None:
    acc = omath_for(source).find(f".//{{{M_NS}}}acc")
    assert acc.find(f"{{{M_NS}}}accPr/{{{M_NS}}}chr").get(qname(M_NS, "val")) == char


def test_annotated_arrow_still_uses_lim_upp() -> None:
    # mover without accent="true" must keep its existing m:limUpp output.
    assert "limUpp" in tags("CaCO3 =>[heat] CaO + CO2")


def test_every_accent_kind_survives_the_full_round_trip() -> None:
    # ACCENT_CHARS, OMML_ACCENT_CHARS, and ACCENT_NAMES all derive from the
    # single ACCENTS tuple now, so they cannot drift apart from each other —
    # test_accent_table_is_unambiguous already covers that. What can still
    # regress silently is the pipeline built on top of the table: scan_docx
    # calls formula_to_mathml only, so a formula is reported parse_status="ok"
    # and approved for apply on the strength of that call alone; if
    # mathml_to_omml_py or omml_to_text then failed to handle the character
    # formula_to_mathml just emitted, the candidate would fail at apply time
    # (recorded in `skipped` as status="failed") or refuse to reverse, after
    # scan already told the user it was fine. Iterating ACCENTS directly means
    # a kind added to the table is exercised here automatically.
    for kind in ACCENT_CHARS:
        source = f"accent(x,{kind})"
        assert omml_to_text(omath_for(source)) == source


def test_accent_converts_compound_base_expression() -> None:
    acc = omath_for("accent(a+b,bar)").find(f".//{{{M_NS}}}acc")
    e = acc.find(f"{{{M_NS}}}e")
    assert "".join(e.itertext()) == "a+b"


def test_accent_table_is_unambiguous() -> None:
    # Every kind needs its own MathML character and its own Word mark, or the
    # reverse mapping in ACCENT_NAMES silently collapses two kinds into one.
    names = [name for name, _, _ in ACCENTS]
    spacing = [spacing for _, spacing, _ in ACCENTS]
    combining = [combining for _, _, combining in ACCENTS]
    assert len(set(names)) == len(names)
    assert len(set(spacing)) == len(spacing)
    assert len(set(combining)) == len(combining)
    assert len(ACCENT_CHARS) == len(OMML_ACCENT_CHARS) == len(ACCENT_NAMES) == len(ACCENTS)


def test_accent_rejects_unsupported_mathml_character() -> None:
    # Reachable from the public API with foreign MathML, not only through the
    # fixed ACCENT_CHARS values that formula_to_mathml itself ever emits.
    mover = etree.Element("mover", accent="true")
    etree.SubElement(mover, "mi").text = "x"
    etree.SubElement(mover, "mo").text = "~"
    math = etree.Element("math")
    math.append(mover)

    with pytest.raises(OmmlConversionError, match="unsupported MathML accent character"):
        mathml_to_omml_py(math)


@pytest.mark.parametrize("child_texts", [("x",), ()])
def test_accent_rejects_malformed_child_count(child_texts: tuple[str, ...]) -> None:
    mover = etree.Element("mover", accent="true")
    for text in child_texts:
        etree.SubElement(mover, "mi").text = text
    math = etree.Element("math")
    math.append(mover)

    with pytest.raises(OmmlConversionError, match="requires a base and an accent character"):
        mathml_to_omml_py(math)


def test_delimited_group_produces_m_d() -> None:
    assert "d" in tags("sin(x)")


def test_limit_produces_m_limLow() -> None:
    assert "limLow" in tags("lim(p->0)")


def test_lim_output_unchanged_by_nary_bounds_support() -> None:
    # munderover gaining its own dispatch (for sum/prod bounds) must not
    # affect munder, which lim(...) uses via a completely separate branch.
    omath = omath_for("lim(x->0)")
    lim_low = omath.find(".//m:limLow", namespaces={"m": M_NS})
    assert lim_low is not None
    assert "".join(lim_low.find("./m:e", namespaces={"m": M_NS}).itertext()) == "lim"
    assert "".join(lim_low.find("./m:lim", namespaces={"m": M_NS}).itertext()) == "x→0"
    assert "nary" not in tags("lim(x->0)")


@pytest.mark.parametrize(
    ("source", "op_char", "sub_text", "sup_text"),
    [
        ("sum(i=1,n) i", "∑", "i=1", "n"),
        ("sum(i=1,10) i", "∑", "i=1", "10"),
        ("prod(k=1,m) k", "∏", "k=1", "m"),
    ],
)
def test_nary_bounds_produce_m_nary_with_both_bounds(
    source: str, op_char: str, sub_text: str, sup_text: str
) -> None:
    # Regression coverage for the pre-existing (shipped-in-v1.2) defect: before
    # "munderover" was added to MATHML_TAGS, both bounds of a bounded sum/prod
    # were silently flattened into plain adjacent text runs — e.g.
    # "sum(i=1,n) i" produced OMML text reading "∑i=1ni" with no m:nary and no
    # m:sub/m:sup at all. Asserting structure (not rendered text) is what would
    # have caught it: the old flattened output still concatenates to readable
    # text, which is exactly how this survived a release untested.
    omath = omath_for(source)
    assert "nary" in tags(source)
    nary = omath.find(".//m:nary", namespaces={"m": M_NS})
    assert nary is not None
    nary_pr = nary.find(qname(M_NS, "naryPr"))
    assert nary_pr is not None
    chr_el = nary_pr.find(qname(M_NS, "chr"))
    assert chr_el is not None
    assert chr_el.get(qname(M_NS, "val")) == op_char
    limLoc = nary_pr.find(qname(M_NS, "limLoc"))
    assert limLoc is not None
    assert limLoc.get(qname(M_NS, "val")) == "undOvr"
    for hide_tag in ("subHide", "supHide"):
        hide_el = nary_pr.find(qname(M_NS, hide_tag))
        assert hide_el is not None
        assert hide_el.get(qname(M_NS, "val")) == "0"
    sub = nary.find(qname(M_NS, "sub"))
    sup = nary.find(qname(M_NS, "sup"))
    assert sub is not None
    assert sup is not None
    assert "".join(sub.itertext()) == sub_text
    assert "".join(sup.itertext()) == sup_text
    # sub must precede sup, both before (or as) e, per CT_Nary's fixed order.
    order = list(nary)
    assert order.index(sub) < order.index(sup)


def test_munderover_rejects_malformed_child_count() -> None:
    # mathml_to_omml_py is public API and can be handed foreign MathML — a
    # malformed munderover (missing an over-bound) must raise cleanly, not
    # IndexError.
    munderover = etree.Element("munderover")
    etree.SubElement(munderover, "mo").text = "∑"
    etree.SubElement(munderover, "mrow")
    math = etree.Element("math")
    math.append(munderover)

    with pytest.raises(OmmlConversionError, match="requires a base, an under bound, and an over bound"):
        mathml_to_omml_py(math)


NS = {"m": M_NS}


def test_nary_operand_is_nested_inside_m_e() -> None:
    # Word (and Office's own MML2OMML.XSL) nests a big operator's operand in
    # m:e. Leaving m:e empty and emitting the operand as a following sibling of
    # m:nary is schema-valid and renders in the right order, but Word's equation
    # editor then shows an empty operand placeholder with the body sitting
    # outside the template.
    omath = omath_for("sum(i=1,n) i")
    children = list(omath)
    assert [etree.QName(child).localname for child in children] == ["nary"]
    e = children[0].find(qname(M_NS, "e"))
    assert e is not None
    assert "".join(e.itertext()) == "i"


def test_nary_declares_grow_so_the_operator_stretches() -> None:
    # Without m:grow, Word does not stretch the operator glyph to a tall
    # operand, so "sum(i=1,n) (a+b)/c" renders a small sigma beside a tall
    # fraction. MML2OMML.XSL writes m:grow m:val="1" for every operator in
    # its big-operator list, which covers all of the sum/prod/int characters
    # this writer emits.
    nary_pr = omath_for("sum(i=1,n) (a+b)/c").find(".//m:nary/m:naryPr", namespaces=NS)
    assert nary_pr is not None
    grow = nary_pr.find(qname(M_NS, "grow"))
    assert grow is not None
    assert grow.get(qname(M_NS, "val")) == "1"
    # CT_NaryPr fixes the child order: chr, limLoc, grow, subHide, supHide.
    assert [etree.QName(child).localname for child in nary_pr] == [
        "chr",
        "limLoc",
        "grow",
        "subHide",
        "supHide",
    ]


def test_nary_operand_scope_stops_at_the_enclosing_mrow() -> None:
    # "e^x = sum(n=0,oo) x^n/n!" nests the operator and its body in their own
    # mrow, so only the fraction belongs in m:e — the "e^x =" prefix lives in
    # the outer mrow and must stay outside m:nary. This is exactly what
    # MML2OMML.XSL produces for the same MathML.
    omath = omath_for("e^x = sum(n=0,oo) x^n / n!")
    assert [etree.QName(child).localname for child in omath] == ["sSup", "r", "nary"]
    e = omath.find(".//m:nary/m:e", namespaces=NS)
    assert e is not None
    assert [etree.QName(child).localname for child in e] == ["f"]


def test_nary_absorbs_the_operand_but_lim_does_not() -> None:
    # The n-ary absorption is gated on the munderover base being an n-ary
    # operator character. lim(...) is a munder over an mi base, keeps using
    # m:limLow, and must keep its body as a following sibling.
    omath = omath_for("lim(x->0) sin(x)/x")
    assert "nary" not in tags("lim(x->0) sin(x)/x")
    frac = omath.find(".//m:f", namespaces=NS)
    assert frac is not None
    num = frac.find(qname(M_NS, "num"))
    assert num is not None
    # The limLow and the sin(x) it applies to are siblings inside the numerator.
    assert [etree.QName(child).localname for child in num] == ["limLow", "r", "d"]


def test_nary_operand_is_the_rest_of_the_enclosing_sequence() -> None:
    # The operand is the remainder of the sequence the operator sits in, not
    # just the next sibling. For MathFmt's own output the two rules coincide —
    # `_nary_mathml` always wraps the operator and its body in an mrow of
    # exactly two children — so this pins the choice against foreign MathML,
    # where MML2OMML.XSL reaches the same answer for this input by merging
    # adjacent token elements into a single run.
    mrow = etree.SubElement(etree.Element("math"), "mrow")
    munderover = etree.SubElement(mrow, "munderover")
    etree.SubElement(munderover, "mo").text = "∑"
    for text in ("i", "n"):
        etree.SubElement(munderover, "mi").text = text
    etree.SubElement(mrow, "mi").text = "a"
    etree.SubElement(mrow, "mo").text = "+"
    etree.SubElement(mrow, "mi").text = "b"

    omath = mathml_to_omml_py(mrow.getparent())
    assert [etree.QName(child).localname for child in omath] == ["nary"]
    assert "".join(omath[0].find(qname(M_NS, "e")).itertext()) == "a+b"


def _stacked(omath: etree._Element) -> tuple[str, str, str]:
    """Unpack the m:limUpp/m:limLow pair a non-n-ary munderover becomes."""
    lim_upp = omath[0]
    assert etree.QName(lim_upp).localname == "limUpp"
    lim_low = lim_upp.find(qname(M_NS, "e"))[0]
    assert etree.QName(lim_low).localname == "limLow"
    return (
        "".join(lim_low.find(qname(M_NS, "e")).itertext()),
        "".join(lim_low.find(qname(M_NS, "lim")).itertext()),
        "".join(lim_upp.find(qname(M_NS, "lim")).itertext()),
    )


@pytest.mark.parametrize(
    ("base_tag", "base_text", "under", "over"),
    [
        # An mo base that is not an n-ary operator: a doubly-annotated arrow.
        ("mo", "→", "cat", "heat"),
        # A non-operator base, whatever it spells — including an mi merely
        # spelling a summation sign, which MML2OMML.XSL's isNary also rejects
        # because it requires the base to be an mml:mo.
        ("mi", "x", "i", "n"),
        ("mi", "∑", "i", "n"),
        ("mi", "lim", "i", "n"),
    ],
)
def test_non_nary_munderover_becomes_stacked_limits_not_a_malformed_nary(
    base_tag: str, base_text: str, under: str, over: str
) -> None:
    # A munderover that is not a bounded big operator must not reach the n-ary
    # writer at all. Routing it there produced an m:nary whose m:chr held the
    # base's whole text — "lim", three characters in an attribute ST_Char
    # defines as one — with an empty m:e and the operand orphaned as a sibling:
    # the very shape the operand nesting was written to remove.
    #
    # MML2OMML.XSL converts every one of these to a nested
    # m:limUpp/m:limLow pair instead, which is lossless and valid, so that is
    # what is emitted here.
    mrow = etree.SubElement(etree.Element("math"), "mrow")
    munderover = etree.SubElement(mrow, "munderover")
    etree.SubElement(munderover, base_tag).text = base_text
    etree.SubElement(munderover, "mi").text = under
    etree.SubElement(munderover, "mi").text = over
    etree.SubElement(mrow, "mi").text = "a"

    omath = mathml_to_omml_py(mrow.getparent())
    assert [etree.QName(child).localname for child in omath] == ["limUpp", "r"]
    assert _stacked(omath) == (base_text, under, over)
    assert omath.find(".//m:chr", namespaces=NS) is None


def test_no_generated_m_chr_is_ever_longer_than_one_character() -> None:
    # m:chr's ST_Char is a single character. Any multi-character value is
    # malformed OMML that Word cannot round-trip, so hold every writer in this
    # module to the type.
    for source in ("sum(i=1,n) i", "prod(k=1,m) k", "accent(x,vec)", "int(0,1) f"):
        for chr_el in omath_for(source).xpath(".//m:chr", namespaces=NS):
            assert len(chr_el.get(qname(M_NS, "val")) or "") == 1


PRETTY_PRINTED_SUM = """<math xmlns="http://www.w3.org/1998/Math/MathML">
  <mrow>
    <munderover>
      <mo>
        ∑
      </mo>
      <mi>i</mi>
      <mi>n</mi>
    </munderover>
    <mi>a</mi>
  </mrow>
</math>"""


def test_nary_normalizes_a_whitespace_padded_operator() -> None:
    # Pretty-printed MathML is ordinary input, and MathML token content is
    # whitespace-insensitive, so an <mo> can carry newlines and indentation
    # around its character. Writing that text raw put the whitespace into
    # m:chr — whose ST_Char is a single character — and omml_to_text then
    # refused MathFmt's own forward output. MML2OMML.XSL passes
    # normalize-space() into CreateNaryProp for exactly this reason.
    omath = mathml_to_omml_py(etree.fromstring(PRETTY_PRINTED_SUM.encode()))

    chr_el = omath.find(".//m:naryPr/m:chr", namespaces=NS)
    assert chr_el is not None
    assert chr_el.get(qname(M_NS, "val")) == "∑"
    assert omml_to_text(omath) == "sum(i,n)a"


@pytest.mark.parametrize("source", ["sum(i=1,n) i", "prod(k=1,m) k", "sum(i=1,n) (a+b)/c"])
def test_nested_nary_operand_round_trips(source: str) -> None:
    # Nesting the operand must not change what omml_to_text reads back: compare
    # re-parsed trees rather than strings, since "2*x" and "2x" are the same
    # formula spelled two ways.
    reconstructed = omml_to_text(omath_for(source))
    assert etree.tostring(formula_to_mathml(reconstructed)) == etree.tostring(formula_to_mathml(source))


def test_int_with_bounds_produces_m_sSubSup_with_both_bounds() -> None:
    # int(0,1) f already worked before this task (msubsup, not munderover) —
    # pin its OMML structure so a future change can't regress it unnoticed the
    # same way munderover's bounds regressed silently.
    omath = omath_for("int(0,1) f")
    ssubsup = omath.find(".//m:sSubSup", namespaces={"m": M_NS})
    assert ssubsup is not None
    assert "".join(ssubsup.find("./m:e", namespaces={"m": M_NS}).itertext()) == "∫"
    assert "".join(ssubsup.find("./m:sub", namespaces={"m": M_NS}).itertext()) == "0"
    assert "".join(ssubsup.find("./m:sup", namespaces={"m": M_NS}).itertext()) == "1"
    # int(...) is deliberately *not* rerouted into m:nary by the n-ary operand
    # nesting: it stays m:sSubSup with the integrand as a following sibling.
    assert [etree.QName(child).localname for child in omath] == ["sSubSup", "r"]
    assert "nary" not in tags("int(0,1) f")


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
        "root(x,3)",
        "root(a+b,n+1)",
        "root(root(x,3),2)",
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
        "sum(i=1,n) i",
        "sum(i=1,10) i",
        "prod(k=1,m) k",
        "int(0,1) f",
        "H2O",
        "Ca(OH)2",
        "2H2 + O2 -> 2H2O",
        "CaCO3 =>[heat] CaO + CO2",
        "(SO4)2",  # chemistry group containing its own subscripted element
        "Fe2(SO4)3",
        "(NH4)2SO4",
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


def test_omml_to_text_rejects_relation_alignment_matrix_multiline() -> None:
    # combine_equation_array's two-column m:m (used for MathFmt's own
    # relation-aligned multi-line output) is a different feature from a
    # mathematical matrix, but shares its OMML shape and is equally
    # unsupported — must not be silently misread as one long formula.
    array = combine_equation_array([omath_for("a = b"), omath_for("long = d")])
    with pytest.raises(OmmlConversionError, match="m:m"):
        omml_to_text(array)


def test_omml_to_text_rejects_eqarr_multiline() -> None:
    array = combine_equation_array([omath_for("a + b"), omath_for("c - d")])
    with pytest.raises(OmmlConversionError, match="m:eqArr"):
        omml_to_text(array)


def test_omml_to_text_rejects_non_omath_root() -> None:
    with pytest.raises(OmmlConversionError, match="oMath"):
        omml_to_text(etree.Element(qname(M_NS, "r")))


def test_omml_to_text_rejects_bare_partial_symbol() -> None:
    # A malformed/hand-authored m:f with nothing but "∂" on each side has no
    # valid linear-text form ("∂" is only ever accepted through partial(f, x)
    # or an unparenthesized ∂f/∂x) — must raise rather than emit unparseable
    # text like "partial(,)".
    omath = etree.Element(qname(M_NS, "oMath"))
    f = etree.SubElement(omath, qname(M_NS, "f"))
    for part in ("num", "den"):
        container = etree.SubElement(f, qname(M_NS, part))
        run = etree.SubElement(container, qname(M_NS, "r"))
        etree.SubElement(run, qname(M_NS, "t")).text = "∂"

    with pytest.raises(OmmlConversionError, match="partial derivative"):
        omml_to_text(omath)


def test_omml_to_text_rejects_unknown_element() -> None:
    omath = etree.Element(qname(M_NS, "oMath"))
    etree.SubElement(omath, qname(M_NS, "bogus"))
    with pytest.raises(OmmlConversionError, match="m:bogus"):
        omml_to_text(omath)


def test_omml_to_text_reconstructs_nth_root() -> None:
    # Was "does not support nth-root radicals" — root(x,3) is now a native
    # construct (Task 5), so this must reconstruct rather than raise.
    omath = etree.Element(qname(M_NS, "oMath"))
    rad = etree.SubElement(omath, qname(M_NS, "rad"))
    deg = etree.SubElement(rad, qname(M_NS, "deg"))
    deg_run = etree.SubElement(deg, qname(M_NS, "r"))
    etree.SubElement(deg_run, qname(M_NS, "t")).text = "3"
    e = etree.SubElement(rad, qname(M_NS, "e"))
    e_run = etree.SubElement(e, qname(M_NS, "r"))
    etree.SubElement(e_run, qname(M_NS, "t")).text = "x"

    assert omml_to_text(omath) == "root(x,3)"


def test_omml_to_text_nary_requires_both_bounds() -> None:
    # A m:nary with only one bound present is not a shape sum(...)/prod(...)
    # can represent — must raise rather than guess a missing bound.
    omath = omath_for("sum(i=1,n) i")
    nary = omath.find(qname(M_NS, "nary"))
    assert nary is not None
    sup = nary.find(qname(M_NS, "sup"))
    assert sup is not None
    nary.remove(sup)

    with pytest.raises(OmmlConversionError, match="both m:sub and m:sup"):
        omml_to_text(omath)


def _word_nary(
    omath: etree._Element,
    *,
    chr_val: str | None = "∑",
    with_nary_pr: bool = True,
    operand: str = "x",
) -> etree._Element:
    """Build the m:nary shape Word writes: naryPr, both bounds, operand in m:e."""
    nary = etree.SubElement(omath, qname(M_NS, "nary"))
    if with_nary_pr:
        nary_pr = etree.SubElement(nary, qname(M_NS, "naryPr"))
        if chr_val is not None:
            chr_el = etree.SubElement(nary_pr, qname(M_NS, "chr"))
            chr_el.set(qname(M_NS, "val"), chr_val)
        for tag, val in (("limLoc", "undOvr"), ("grow", "1")):
            prop = etree.SubElement(nary_pr, qname(M_NS, tag))
            prop.set(qname(M_NS, "val"), val)
    for tag, text in (("sub", "i=1"), ("sup", "n")):
        container = etree.SubElement(nary, qname(M_NS, tag))
        run = etree.SubElement(container, qname(M_NS, "r"))
        etree.SubElement(run, qname(M_NS, "t")).text = text
    e = etree.SubElement(nary, qname(M_NS, "e"))
    run = etree.SubElement(e, qname(M_NS, "r"))
    etree.SubElement(run, qname(M_NS, "t")).text = operand
    return nary


def test_omml_to_text_reads_a_nary_operand_nested_in_m_e() -> None:
    # The operand of a Word-authored (and, since the operand is now nested,
    # MathFmt-authored) m:nary lives inside m:e. Dropping it would silently
    # lose the body of every summation read out of a real document while still
    # producing a plausible-looking "sum(i=1,n)" — so assert the operand text
    # itself, not just that the call succeeds.
    omath = etree.Element(qname(M_NS, "oMath"))
    _word_nary(omath, operand="k")

    assert omml_to_text(omath) == "sum(i=1,n)k"


def test_omml_to_text_reads_a_multi_run_nary_operand() -> None:
    omath = etree.Element(qname(M_NS, "oMath"))
    nary = _word_nary(omath)
    e = nary.find(qname(M_NS, "e"))
    assert e is not None
    for text in ("+", "1"):
        run = etree.SubElement(e, qname(M_NS, "r"))
        etree.SubElement(run, qname(M_NS, "t")).text = text

    assert omml_to_text(omath) == "sum(i=1,n)x+1"


@pytest.mark.parametrize("with_nary_pr", [True, False])
def test_omml_to_text_defaults_an_absent_nary_chr_to_sum(with_nary_pr: bool) -> None:
    # ECMA-376 gives CT_NaryPr's m:chr a default of U+2211 (n-ary summation),
    # and m:naryPr is itself optional in CT_Nary, so an m:nary that omits
    # either is a legitimate Word shape meaning "sum" — not an error. This
    # matches how an absent m:accPr/m:chr is handled for accents: an absent
    # property means the format's documented default; a present but
    # unrecognised value still raises.
    omath = etree.Element(qname(M_NS, "oMath"))
    _word_nary(omath, chr_val=None, with_nary_pr=with_nary_pr)

    assert omml_to_text(omath) == "sum(i=1,n)x"


def test_omml_to_text_rejects_a_valueless_nary_chr() -> None:
    # A *present* m:chr carrying no m:val is the narrower case the default does
    # not cover — it names no operator, so it raises rather than becoming a sum.
    omath = etree.Element(qname(M_NS, "oMath"))
    nary = _word_nary(omath, chr_val=None)
    nary_pr = nary.find(qname(M_NS, "naryPr"))
    assert nary_pr is not None
    nary_pr.insert(0, etree.Element(qname(M_NS, "chr")))

    with pytest.raises(OmmlConversionError, match="does not support the m:nary operator"):
        omml_to_text(omath)


def test_omml_to_text_nary_rejects_unrecognized_operator() -> None:
    omath = etree.Element(qname(M_NS, "oMath"))
    nary = etree.SubElement(omath, qname(M_NS, "nary"))
    nary_pr = etree.SubElement(nary, qname(M_NS, "naryPr"))
    chr_el = etree.SubElement(nary_pr, qname(M_NS, "chr"))
    chr_el.set(qname(M_NS, "val"), "⋃")
    for tag in ("sub", "sup"):
        container = etree.SubElement(nary, qname(M_NS, tag))
        run = etree.SubElement(container, qname(M_NS, "r"))
        etree.SubElement(run, qname(M_NS, "t")).text = "1"

    with pytest.raises(OmmlConversionError, match="does not support the m:nary operator"):
        omml_to_text(omath)


def test_nary_table_is_unambiguous() -> None:
    # NARY_CHARS and NARY_NAMES are inverse views of one NARY_OPERATORS tuple,
    # so a duplicate name or a duplicate character would silently collapse two
    # operators into one in whichever direction lost the row. Both documented
    # defaults must also name operators the table actually knows, or the branch
    # that reaches for one raises on a value this module itself supplied.
    names = [name for name, _ in NARY_OPERATORS]
    chars = [char for _, char in NARY_OPERATORS]
    assert len(set(names)) == len(names)
    assert len(set(chars)) == len(chars)
    assert len(NARY_CHARS) == len(NARY_NAMES) == len(NARY_OPERATORS)
    assert FALLBACK_NARY_CHAR in NARY_NAMES
    assert OMML_IMPLIED_NARY_CHAR in NARY_NAMES


@pytest.mark.parametrize(("char", "name"), sorted(NARY_NAMES.items()))
def test_every_nary_operator_crosses_both_directions(char: str, name: str) -> None:
    # The one drift this shared table exists to prevent: an operator taught to
    # the parser but not to this module produced an m:chr the reverse direction
    # then refused to read. Iterating the table means a row added to it is
    # exercised in both directions here automatically, rather than needing a
    # second edit someone can forget.
    #
    # Forward: a munderover over the character is a bounded big operator and
    # takes the m:nary path, not the stacked-limits path.
    mrow = etree.SubElement(etree.Element("math"), "mrow")
    munderover = etree.SubElement(mrow, "munderover")
    etree.SubElement(munderover, "mo").text = char
    for bound in ("i", "n"):
        etree.SubElement(munderover, "mi").text = bound
    forward = mathml_to_omml_py(mrow.getparent())
    assert [etree.QName(child).localname for child in forward] == ["nary"]
    assert forward.find(".//m:naryPr/m:chr", namespaces=NS).get(qname(M_NS, "val")) == char

    # Reverse: the same character comes back as its linear name.
    omath = etree.Element(qname(M_NS, "oMath"))
    _word_nary(omath, chr_val=char)
    assert omml_to_text(omath) == f"{name}(i=1,n)x"


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


def test_omml_to_text_plain_styled_non_digit_subscript_still_uses_underscore() -> None:
    # A synthetic (non-MathFmt) m:sSub with a plain/upright-styled base but a
    # non-digit subscript ("max", not an element count) must not be mistaken
    # for chemistry: dropping the "_" here would corrupt "x_max" into the bare
    # identifier "xmax" on reparse. The all-digit-subscript requirement is
    # exactly what rules this out.
    omath = etree.Element(qname(M_NS, "oMath"))
    ssub = etree.SubElement(omath, qname(M_NS, "sSub"))
    base = etree.SubElement(ssub, qname(M_NS, "e"))
    run = etree.SubElement(base, qname(M_NS, "r"))
    r_pr = etree.SubElement(run, qname(M_NS, "rPr"))
    sty = etree.SubElement(r_pr, qname(M_NS, "sty"))
    sty.set(qname(M_NS, "val"), "p")
    etree.SubElement(run, qname(M_NS, "t")).text = "x"
    sub = etree.SubElement(ssub, qname(M_NS, "sub"))
    sub_run = etree.SubElement(sub, qname(M_NS, "r"))
    etree.SubElement(sub_run, qname(M_NS, "t")).text = "max"

    assert omml_to_text(omath) == "x_max"


@pytest.mark.parametrize(
    "source", ["accent(x,bar)", "accent(F,vec)", "accent(y,hat)", "accent(q,dot)", "accent(q,ddot)"]
)
def test_accent_round_trips_through_omml_to_text(source: str) -> None:
    assert omml_to_text(omath_for(source)) == source


def test_accent_round_trips_with_a_compound_base() -> None:
    assert omml_to_text(omath_for("accent(a+b,bar)")) == "accent(a+b,bar)"


def test_accent_round_trips_when_nested() -> None:
    assert omml_to_text(omath_for("accent(accent(x,bar),vec)")) == "accent(accent(x,bar),vec)"


def test_accent_missing_chr_element_defaults_to_hat() -> None:
    # ISO/IEC 29500's CT_AccPr: omitting m:chr means the implicit default,
    # U+0302 COMBINING CIRCUMFLEX ACCENT (hat) — a spec-defined default, not
    # something this converter chooses to guess. Matters for third-party or
    # hand-authored OMML: MathFmt's own writer and Office's MML2OMML.XSL both
    # always write m:chr explicitly, even for hat.
    omath = omath_for("accent(y,hat)")
    acc_pr = omath.find(f".//{{{M_NS}}}acc/{{{M_NS}}}accPr")
    acc_pr.remove(acc_pr.find(f"{{{M_NS}}}chr"))
    assert omml_to_text(omath) == "accent(y,hat)"


def test_accent_missing_accPr_element_defaults_to_hat() -> None:
    # m:accPr is minOccurs="0" in CT_Acc, so a bare <m:acc><m:e>x</m:e></m:acc>
    # is schema-valid, and the same ISO/IEC 29500 default (U+0302, hat) applies
    # whether m:accPr itself or only its m:chr child is omitted — the rule is
    # "an absent property means the documented default", applied consistently.
    omath = etree.Element(qname(M_NS, "oMath"))
    acc = etree.SubElement(omath, qname(M_NS, "acc"))
    e = etree.SubElement(acc, qname(M_NS, "e"))
    run = etree.SubElement(e, qname(M_NS, "r"))
    etree.SubElement(run, qname(M_NS, "t")).text = "x"

    assert omml_to_text(omath) == "accent(x,hat)"


def test_omml_to_text_rejects_accent_with_unrecognized_chr_value() -> None:
    omath = etree.Element(qname(M_NS, "oMath"))
    acc = etree.SubElement(omath, qname(M_NS, "acc"))
    acc_pr = etree.SubElement(acc, qname(M_NS, "accPr"))
    chr_el = etree.SubElement(acc_pr, qname(M_NS, "chr"))
    chr_el.set(qname(M_NS, "val"), "~")
    e = etree.SubElement(acc, qname(M_NS, "e"))
    run = etree.SubElement(e, qname(M_NS, "r"))
    etree.SubElement(run, qname(M_NS, "t")).text = "x"

    with pytest.raises(OmmlConversionError, match="accent character '~'"):
        omml_to_text(omath)


def test_omml_to_text_rejects_accent_chr_with_no_val() -> None:
    # ISO/IEC 29500: m:chr present but without m:val means the character
    # itself is absent, a narrower case than m:chr/m:accPr being missing
    # outright — the spec-defined hat default applies only to the latter, so
    # this must not be silently treated as hat either.
    omath = etree.Element(qname(M_NS, "oMath"))
    acc = etree.SubElement(omath, qname(M_NS, "acc"))
    acc_pr = etree.SubElement(acc, qname(M_NS, "accPr"))
    etree.SubElement(acc_pr, qname(M_NS, "chr"))  # no m:val
    e = etree.SubElement(acc, qname(M_NS, "e"))
    run = etree.SubElement(e, qname(M_NS, "r"))
    etree.SubElement(run, qname(M_NS, "t")).text = "x"

    with pytest.raises(OmmlConversionError, match="accent character None"):
        omml_to_text(omath)
