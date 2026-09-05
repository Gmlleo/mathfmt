from __future__ import annotations

import pytest
from lxml import etree

from mathfmt.core import (
    ACCENT_CHARS,
    M_NS,
    MML_NS,
    NS,
    W_NS,
    FormulaError,
    Node,
    candidate_runs,
    candidate_spans,
    estimated_formula_width,
    formula_to_mathml,
    likely_code,
    mathml_to_omml,
    node_to_mathml,
    qname,
    run_with_text_like,
    set_math_font_size,
    split_multiline_formula,
    split_top_level_additive,
    tokenize,
)


def local_tags(source: str) -> list[str]:
    return [etree.QName(node).localname for node in formula_to_mathml(source).iter()]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("lim(p->0)", "munder"),
        ("sin(x) + cos(x)", "mfenced"),
        ("(a+b)/(c-d)", "mfrac"),
        ("2x + 3*x", "mrow"),
        ("x^(2)", "msup"),
        ("p1,2 = ep", "msub"),
        ("-x <= +2", "mo"),
        ("x, y", "mrow"),
    ],
)
def test_supported_formula_structures(source: str, expected: str) -> None:
    assert expected in local_tags(source)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("∓x", "mo"),
        ("±x", "mo"),
    ],
)
def test_new_symbol_characters_are_tokenized(source: str, expected: str) -> None:
    assert expected in local_tags(source)


@pytest.mark.parametrize("source", ["a ∓ b", "∓x", "∇f = 0", "∇"])
def test_new_symbol_characters_reach_the_output(source: str) -> None:
    text = "".join(formula_to_mathml(source).itertext())
    assert ("∓" in text) or ("∇" in text)


def test_bare_partial_still_raises() -> None:
    # ∂ is in MATH_CHARS, so a parse failure here is what keeps shapes like
    # ∂^2u/∂x^2 out of automatic conversion. See the comment above TOKEN_RE.
    with pytest.raises(FormulaError):
        formula_to_mathml("∂^2u/∂x^2 = 0")


def test_partial_derivative_preprocessing_still_wins_over_bare_partial() -> None:
    # ∂f/∂x must keep going through preprocess_formula into a stacked fraction
    # with ∂f over ∂x — a bare "mfrac appears somewhere" assertion would also
    # pass for the wrong parse (∂·f/∂)·x, so assert the operands.
    fraction = formula_to_mathml("∂f/∂x").find(".//{*}mfrac")
    assert fraction is not None
    assert "".join(fraction[0].itertext()) == "∂f"
    assert "".join(fraction[1].itertext()) == "∂x"


@pytest.mark.parametrize("source", ["x @ 2", "(x]", "x +", ")"])
def test_formula_errors_are_explicit(source: str) -> None:
    with pytest.raises(FormulaError):
        formula_to_mathml(source)


def test_formula_error_reports_column_context_and_expected_token() -> None:
    with pytest.raises(FormulaError) as exc_info:
        formula_to_mathml("x +")

    error = exc_info.value
    details = error.to_dict()

    assert error.position == 3
    assert details["column"] == 4
    assert "Expected formula atom" in details["message"]
    assert details["expected"] == "number, identifier, function, matrix, or grouped expression"
    assert details["context"] == "x +"
    assert "operand is missing" in details["hint"]


@pytest.mark.parametrize(
    ("source", "expected_snippet"),
    [
        ("(x]", "mismatched bracket"),
        ("(x+1", "mismatched bracket"),  # never closed at all, not just the wrong closer
        ("[x+1", "mismatched bracket"),
        ("cases(x^2; -x if x<0)", "missing 'if'"),
    ],
)
def test_formula_error_hint_covers_common_mistakes(source: str, expected_snippet: str) -> None:
    with pytest.raises(FormulaError) as exc_info:
        formula_to_mathml(source)

    hint = exc_info.value.to_dict().get("hint")
    assert hint is not None
    assert expected_snippet in hint


def test_formula_error_hint_does_not_misfire_for_an_illegal_character() -> None:
    # "x @ y" fails at the tokenizer (unrecognized character), with an
    # `expected` string that happens to start the same way as the parser's
    # unrelated "missing operand" message — the hint rules must not conflate
    # the two.
    with pytest.raises(FormulaError) as exc_info:
        formula_to_mathml("x @ y")

    hint = exc_info.value.to_dict()["hint"]
    assert "isn't recognized" in hint
    assert "operand is missing" not in hint


def test_formula_error_hint_is_absent_for_unrecognized_expected() -> None:
    error = FormulaError("made up error", expected="some internal token kind")
    assert "hint" not in error.to_dict()


def test_tokenizer_accepts_trailing_space_and_rejects_unknown_text() -> None:
    assert tokenize("x = 1   ")[-1].kind == "EOF"
    with pytest.raises(FormulaError, match="Unrecognized"):
        tokenize("x @ 1")


def test_unknown_ast_node_is_rejected() -> None:
    with pytest.raises(FormulaError, match="Unsupported AST"):
        node_to_mathml(Node("not_a_real_node_kind"))


def transform(source: str) -> etree.XSLT:
    return etree.XSLT(etree.fromstring(source.encode("utf-8")))


def test_mathml_to_omml_accepts_supported_transform_roots() -> None:
    math = formula_to_mathml("x = 1")
    para_xsl = transform(
        f"""<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
        xmlns:m="{M_NS}"><xsl:template match="/"><m:oMathPara><m:oMath/></m:oMathPara></xsl:template>
        </xsl:stylesheet>"""
    )
    wrapper_xsl = transform(
        f"""<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
        xmlns:m="{M_NS}"><xsl:template match="/"><root><m:oMath/></root></xsl:template>
        </xsl:stylesheet>"""
    )
    assert mathml_to_omml(math, para_xsl).tag == qname(M_NS, "oMath")
    assert mathml_to_omml(math, wrapper_xsl).tag == qname(M_NS, "oMath")


@pytest.mark.parametrize(
    "body",
    [
        f"<m:oMathPara xmlns:m='{M_NS}'/>",
        f"<root xmlns:m='{M_NS}'/>",
    ],
)
def test_mathml_to_omml_rejects_transform_without_equation(body: str) -> None:
    xsl = transform(
        f"""<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
        <xsl:template match="/">{body}</xsl:template></xsl:stylesheet>"""
    )
    with pytest.raises(FormulaError):
        mathml_to_omml(formula_to_mathml("x = 1"), xsl)


@pytest.mark.parametrize(
    "text",
    [
        "% comment",
        "value = 1;",
        "step(system, t);",
        "import module",
    ],
)
def test_code_detection_positive_cases(text: str) -> None:
    assert likely_code(text)


def test_code_detection_leaves_prose_untouched() -> None:
    assert not likely_code("The result is x = 1")


def test_candidate_boundaries_and_low_score_text() -> None:
    candidates = candidate_runs("Result is x^2 + 1 = 2. More text")
    assert candidates
    assert candidates[0][2].endswith("= 2")
    assert candidate_runs("ordinary prose") == []


def test_chemistry_scanner_finds_formulas_and_whole_reactions() -> None:
    text = "Water is H2O; salt is NaCl. Reaction: 2H2 + O2 -> 2H2O."
    spans = candidate_spans(text)

    assert [span.source for span in spans] == ["H2O", "NaCl", "2H2 + O2 -> 2H2O"]
    assert all(span.chemistry for span in spans)


def test_chemistry_scanner_is_conservative_for_prose_and_single_elements() -> None:
    assert candidate_runs("NASA and Office are ordinary prose.") == []
    assert candidate_runs("Use A -> B to describe a mapping.") == []

    spans = candidate_spans("Oxygen is O2.")
    assert [span.source for span in spans] == ["O2"]
    assert spans[0].chemistry is True


def test_physics_scanner_finds_supported_notation_as_reviewable_spans() -> None:
    text = "Use partial f / partial x, ∂g/∂t, T_i^j, <phi|psi>, and bra(phi) ket(psi)."
    spans = candidate_spans(text)

    assert [span.source for span in spans] == [
        "partial f / partial x",
        "∂g/∂t",
        "T_i^j",
        "<phi|psi>",
        "bra(phi) ket(psi)",
    ]
    assert [span.physics for span in spans] == [
        "partial_derivative",
        "partial_derivative",
        "tensor",
        "braket",
        "braket",
    ]


def test_physics_scanner_avoids_prose_like_angle_and_function_text() -> None:
    assert candidate_runs("Use <tag> in prose and call bracket(value) normally.") == []


@pytest.mark.parametrize("source", ["∂f/∂x = 0", "<phi|psi> = 1", "T_i^j = 0"])
def test_physics_scanner_keeps_complete_anchored_equations(source: str) -> None:
    spans = candidate_spans(source)

    assert len(spans) == 1
    assert spans[0].source == source


def test_latex_delimited_candidate_spans() -> None:
    spans = candidate_spans("Inline $x^2 + 1$ and display $$y = 2$$.")

    assert [(span.source, span.linear, span.display, span.explicit) for span in spans] == [
        ("$x^2 + 1$", "x^2 + 1", False, True),
        ("$$y = 2$$", "y = 2", True, True),
    ]


def test_latex_delimiter_scan_ignores_simple_currency() -> None:
    assert candidate_runs("The price is $12.00$ today.") == []


def test_latex_delimited_span_at_end_is_safe() -> None:
    spans = candidate_spans("Ends with $x + 1$")

    assert spans[-1].source == "$x + 1$"
    assert spans[-1].linear == "x + 1"


def test_multiline_formula_splits_latex_and_real_line_breaks() -> None:
    assert split_multiline_formula(r"a = b \\ c = d") == ["a = b", "c = d"]
    assert split_multiline_formula("a = b\nc = d") == ["a = b", "c = d"]
    assert split_multiline_formula("a / b") == ["a / b"]


def test_multiline_formula_rejects_empty_lines() -> None:
    with pytest.raises(FormulaError, match="empty line"):
        split_multiline_formula("a = b\n\nc = d")


def test_table_line_splitting_respects_groups_and_unary_signs() -> None:
    source = "a+(b+c+d)+e+f+g"
    lines = split_top_level_additive(source, target_length=8)
    assert "".join(lines) == source
    assert all("(b+c+d)" in line for line in lines if "(" in line)
    assert split_top_level_additive("a*(b+c)") == ["a*(b+c)"]
    assert split_top_level_additive("x^-2+y", target_length=3) == ["x^-2", "+y"]


def test_estimated_width_accounts_for_derivatives() -> None:
    assert estimated_formula_width("s'(t)") == len("s'(t)") + 18


def test_math_run_font_size_updates_existing_and_new_properties() -> None:
    root = etree.fromstring(
        f"""<m:oMath xmlns:m="{M_NS}" xmlns:w="{W_NS}">
        <m:r><m:rPr/><m:t>x</m:t></m:r>
        <m:r><w:rPr><w:sz w:val="20"/></w:rPr><m:t>y</m:t></m:r>
        </m:oMath>"""
    )
    set_math_font_size(root, 16)
    assert root.xpath("count(.//w:sz[@w:val='16'])", namespaces=NS) == 2
    assert root.xpath("count(.//w:szCs[@w:val='16'])", namespaces=NS) == 2


def test_text_run_clone_preserves_formatting_and_spaces() -> None:
    run = etree.fromstring(f"<w:r xmlns:w='{W_NS}'><w:rPr><w:b/></w:rPr><w:t>old</w:t></w:r>")
    cloned = run_with_text_like(run, " suffix ")
    assert cloned.xpath("boolean(./w:rPr/w:b)", namespaces=NS)
    text = cloned.find(qname(W_NS, "t"))
    assert text is not None and text.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"
    assert etree.QName(formula_to_mathml("x")).namespace == MML_NS


def test_accent_produces_mover_with_accent_attribute() -> None:
    math = formula_to_mathml("accent(x,bar)")
    mover = math.find(f".//{{{MML_NS}}}mover")
    assert mover is not None
    assert mover.get("accent") == "true"
    assert [etree.QName(child).localname for child in mover] == ["mi", "mo"]
    assert mover[1].text == "‾"


@pytest.mark.parametrize(
    ("source", "char"),
    [
        ("accent(F,vec)", "→"),
        ("accent(y,hat)", "^"),
        ("accent(q,dot)", "˙"),
        ("accent(q,ddot)", "¨"),
    ],
)
def test_accent_kinds(source: str, char: str) -> None:
    math = formula_to_mathml(source)
    assert math.find(f".//{{{MML_NS}}}mover")[1].text == char


@pytest.mark.parametrize("source", ["accent(x)", "accent(x,bar,y)", "accent(x,tilde)"])
def test_invalid_accent_is_rejected(source: str) -> None:
    with pytest.raises(FormulaError):
        formula_to_mathml(source)


def test_accent_error_carries_a_hint() -> None:
    with pytest.raises(FormulaError) as excinfo:
        formula_to_mathml("accent(x,tilde)")
    hint = excinfo.value.to_dict()["hint"]
    for kind in ACCENT_CHARS:
        assert kind in hint


def test_accent_kind_is_not_shadowed_by_a_user_alias() -> None:
    # latex.py generates accent(x,hat) from \hat{x}; a profile defining "hat"
    # must not break it.
    math = formula_to_mathml("accent(x,hat)", {"hat": "ĥ"})
    assert math.find(f".//{{{MML_NS}}}mover")[1].text == "^"


@pytest.mark.parametrize("source", ["accent(y,bar(x))", "accent(x,accent(y,bar))", "accent(y,(bar))"])
def test_accent_kind_must_be_a_bare_name(source: str) -> None:
    # These all have a node whose value is literally "bar"; accepting them would
    # silently drop the second argument's structure.
    with pytest.raises(FormulaError):
        formula_to_mathml(source)


def test_accent_preserves_a_compound_base() -> None:
    math = formula_to_mathml("accent(a+b,bar)")
    mover = math.find(f".//{{{MML_NS}}}mover")
    assert [etree.QName(child).localname for child in mover] == ["mrow", "mo"]
    assert "".join(mover[0].itertext()) == "a+b"


def test_accents_nest() -> None:
    math = formula_to_mathml("accent(accent(x,bar),vec)")
    outer = math.find(f".//{{{MML_NS}}}mover")
    assert outer[1].text == "→"
    inner = outer[0]
    assert etree.QName(inner).localname == "mover"
    assert inner[1].text == "‾"


def test_root_produces_mroot() -> None:
    math = formula_to_mathml("root(x,3)")
    mroot = math.find(f".//{{{MML_NS}}}mroot")
    assert mroot is not None
    assert [etree.QName(child).localname for child in mroot] == ["mi", "mn"]


def test_root_degree_may_be_an_expression() -> None:
    assert "mroot" in local_tags("root(x,n+1)")


def test_sqrt_still_produces_msqrt() -> None:
    assert "msqrt" in local_tags("sqrt(x)")


@pytest.mark.parametrize("source", ["root(x)", "root(x,2,3)", "root(x,y,z)"])
def test_invalid_root_is_rejected(source: str) -> None:
    with pytest.raises(FormulaError):
        formula_to_mathml(source)


def test_roots_nest() -> None:
    math = formula_to_mathml("root(root(x,3),2)")
    outer = math.find(f".//{{{MML_NS}}}mroot")
    assert [etree.QName(child).localname for child in outer] == ["mroot", "mn"]
    inner = outer[0]
    assert [etree.QName(child).localname for child in inner] == ["mi", "mn"]


def test_root_preserves_a_compound_base() -> None:
    math = formula_to_mathml("root(a+b,n)")
    mroot = math.find(f".//{{{MML_NS}}}mroot")
    assert [etree.QName(child).localname for child in mroot] == ["mrow", "mi"]
    assert "".join(mroot[0].itertext()) == "a+b"


def test_quoted_text_becomes_mtext() -> None:
    math = formula_to_mathml('"已知"')
    mtext = math.find(f".//{{{MML_NS}}}mtext")
    assert mtext is not None
    assert mtext.text == "已知"


def test_quoted_text_participates_in_a_formula() -> None:
    assert "mtext" in local_tags('x = 3 "kg"')


def test_quoted_text_is_one_token_not_split_by_its_contents() -> None:
    # The whole point of a text atom is that its contents are not math: a
    # quoted run holding operators, digits, spaces and commas stays one mtext
    # rather than being lexed as the expression it resembles.
    math = formula_to_mathml('"a + 1, b"')
    assert [etree.QName(el).localname for el in math.iter()][1:] == ["mtext"]
    assert math.find(f".//{{{MML_NS}}}mtext").text == "a + 1, b"


def test_empty_quoted_text_is_an_empty_mtext() -> None:
    math = formula_to_mathml('x "" y')
    texts = [el.text for el in math.iter(f"{{{MML_NS}}}mtext")]
    assert texts == [""]


def test_unterminated_quote_is_rejected() -> None:
    # An opening quote with no closing one must not silently lex as anything
    # else; a lone " is still untokenizable.
    with pytest.raises(FormulaError):
        formula_to_mathml('x "kg')


def test_matrix_literal_produces_two_by_two_structure() -> None:
    # Regression for Task 5b: a comma between two digit runs used to lex as a
    # single decimal NUMBER, so [[1,2],[3,4]] silently became a 2x1 matrix of
    # the "numbers" 1,2 and 3,4 instead of a 2x2 integer matrix.
    math = formula_to_mathml("[[1,2],[3,4]]")
    rows = math.findall(f".//{{{MML_NS}}}mtr")
    assert len(rows) == 2
    for row, expected in zip(rows, [["1", "2"], ["3", "4"]], strict=True):
        cells = row.findall(f"{{{MML_NS}}}mtd")
        assert [etree.QName(cell[0]).localname for cell in cells] == ["mn", "mn"]
        assert [cell[0].text for cell in cells] == expected


def test_vector_literal_has_three_elements() -> None:
    # Regression for Task 5b: [1,2,3] used to lex as the 2-element vector
    # ["1,2", "3"] because "1,2" merged into one decimal NUMBER.
    math = formula_to_mathml("[1,2,3]")
    fenced = math.find(f".//{{{MML_NS}}}mfenced")
    assert fenced is not None
    numbers = fenced.findall(f".//{{{MML_NS}}}mn")
    assert [n.text for n in numbers] == ["1", "2", "3"]


def test_decimal_point_still_parses_as_one_number() -> None:
    math = formula_to_mathml("x = 3.14")
    numbers = math.findall(f".//{{{MML_NS}}}mn")
    assert [n.text for n in numbers] == ["3.14"]


def test_decimal_comma_is_now_a_sequence_not_one_number() -> None:
    # Deliberate behaviour change (Task 5b): a comma is always a separator,
    # never a decimal point, so "3,14" no longer lexes as one NUMBER token --
    # it is the two-element sequence 3, 14.
    tokens = [token.kind for token in tokenize("3,14") if token.kind != "EOF"]
    assert tokens == ["NUMBER", "COMMA", "NUMBER"]
    math = formula_to_mathml("3,14")
    numbers = math.findall(f".//{{{MML_NS}}}mn")
    assert [n.text for n in numbers] == ["3", "14"]


def test_bracket_interval_after_identifier_keeps_both_endpoints() -> None:
    # Regression for Task 5c: "x in [0,1]" used to call parse_group() for the
    # "[0,1]" bracket, get back a bare "vector" node (not a wrapped "group"
    # node), and then silently drop everything after the first element when
    # building the "function" node -- "in(0,1)" renders with the 1 missing.
    # Task 5b made this reachable for numbers (it used to fuse "0,1" into one
    # decimal and at least show both digits as "in(0,1)").
    math = formula_to_mathml("x in [0,1]")
    fenced = math.find(f".//{{{MML_NS}}}mfenced")
    assert fenced is not None
    assert fenced.get("open") == "["
    assert fenced.get("close") == "]"
    numbers = fenced.findall(f".//{{{MML_NS}}}mn")
    assert [n.text for n in numbers] == ["0", "1"]


def test_bracket_call_after_identifier_keeps_both_operands() -> None:
    # Regression for Task 5c: same root cause as the interval case above, via
    # a plain function-shaped identifier instead of a relation.
    math = formula_to_mathml("f [a,b]")
    fenced = math.find(f".//{{{MML_NS}}}mfenced")
    assert fenced is not None
    assert fenced.get("open") == "["
    assert fenced.get("close") == "]"
    identifiers = fenced.findall(f".//{{{MML_NS}}}mi")
    assert [i.text for i in identifiers] == ["a", "b"]


def test_sqrt_with_single_element_bracket_still_works() -> None:
    # A single-element [x] is not a comma sequence, so parse_group() returns
    # a "group" node here (not "vector") and is unaffected by the Task 5c
    # fix -- confirm it still works.
    assert "msqrt" in local_tags("sqrt[x]")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\frac{a}{b}", "mfrac"),
        (r"\sqrt[3]{x}", "mroot"),
        (r"\bar{x}", "mover"),
        (r"\alpha + \beta", "mi"),
        (r"\sum_{i=1}^{n} i", "mrow"),
        (r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", "mtable"),
        (r"\text{已知} x", "mtext"),
        (r"\begin{cases} 0 & x<0 \\ 1 & x \geq 0 \end{cases}", "mtable"),
    ],
)
def test_latex_input_reaches_mathml(source: str, expected: str) -> None:
    assert expected in local_tags(source)


def test_unsupported_latex_macro_raises_formula_error() -> None:
    with pytest.raises(FormulaError):
        formula_to_mathml(r"\substack{a}")


def test_a_formula_with_no_macro_never_reaches_the_expander() -> None:
    # The expander runs only when a known macro is present, so ordinary linear
    # formulas — and the backslash-bearing text that is not LaTeX at all — are
    # unaffected by the wiring.
    assert "mfrac" in local_tags("(a)/(b)")
    with pytest.raises(FormulaError):
        formula_to_mathml(r"C:\Users\gml85")


def test_an_aligned_environment_keeps_its_rows_for_the_multiline_splitter() -> None:
    # formula_to_mathml renders one formula, so the row separators an aligned
    # environment produces are the multiline splitter's business, not its own.
    # This pins that the expansion reaches that splitter intact.
    assert split_multiline_formula(r"\begin{aligned} a=b \\ c=d \end{aligned}") == ["a=b", "c=d"]


def test_latex_inline_delimiters_are_high_confidence() -> None:
    spans = candidate_spans(r"由此可得 \(x^2 + 1\) 成立")
    assert len(spans) == 1
    assert spans[0].explicit is True
    assert spans[0].linear == "x^2 + 1"


def test_latex_display_delimiters_are_detected() -> None:
    spans = candidate_spans(r"\[ y = 2x \]")
    assert len(spans) == 1
    assert spans[0].explicit is True
    assert spans[0].display is True
    assert spans[0].linear == "y = 2x"


def test_bare_macro_span_is_detected() -> None:
    spans = candidate_spans(r"其中 \frac{a}{b} 是比值")
    assert len(spans) == 1
    assert spans[0].explicit is False
    assert r"\frac{a}{b}" in spans[0].source


def test_windows_path_is_not_a_candidate() -> None:
    # \Users names no macro, so the path is not LaTeX and the generic walk
    # cannot reach it either — MATH_CHARS excludes the backslash.
    assert candidate_spans(r"文件位于 C:\Users\gml85 目录") == []


def test_unparseable_macro_span_is_not_a_candidate() -> None:
    # The bare-macro detector is guarded by a real parse, so an unsupported
    # macro is not offered for review as though it could convert.
    assert candidate_spans(r"见 \substack{a} 一节") == []


def test_a_bare_macro_span_does_not_overlap_a_delimited_one() -> None:
    # The delimited detector runs first and claims its range; the macro
    # detector must not offer the same text a second time.
    spans = candidate_spans(r"由此 \(\frac{a}{b}\) 成立")
    assert len(spans) == 1
    assert spans[0].explicit is True
