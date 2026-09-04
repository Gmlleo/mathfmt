#!/usr/bin/env python3
"""Pure-Python MathML to OMML converter — no XSL required."""

from __future__ import annotations

import copy
from collections.abc import Sequence

from lxml import etree

from .accents import ACCENT_CHARS, ACCENT_NAMES, OMML_ACCENT_CHARS

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def qname(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


INVISIBLE_TIMES = "⁢"

MATHML_TAGS = {
    "mi",
    "mn",
    "mtext",
    "mo",
    "mfrac",
    "msqrt",
    "mroot",
    "msup",
    "msub",
    "msubsup",
    "mfenced",
    "munder",
    "mover",
    "munderover",
    "mrow",
    "mtable",
    "mtr",
    "mtd",
}


RELATION_SYMBOLS = ("=", "≤", "≥", "≠", "≈", "→", "⇒", "⇌", "<", ">")

# The n-ary big-operator characters this module recognizes, in both directions,
# kept in one table so they cannot drift apart.
#
# Forward (`_nary`): a MathML ``munderover`` only becomes an ``m:nary`` when its
# base is an ``mo`` holding one of these. Gating on the character — rather than
# merely on the tag — is what keeps ``lim(x->0)`` out of the n-ary path; ``lim``
# is a ``munder`` over an ``mi`` base and stays ``m:limLow``.
#
# Reverse (`_emit_nary`): the same characters map back to their linear names.
# ∫ never reaches the reverse path from MathFmt's own writer — ``int(...)``
# always builds ``m:sSubSup`` (see ``_nary_mathml`` in core.py) — but a
# Word-authored or hand-authored ``m:nary`` using ∫ is a real, common shape, so
# it is reconstructed the same way.
#
# All three are also in MML2OMML.XSL's own grow-by-default list, which is why
# `_nary` can write ``m:grow`` unconditionally.
_NARY_OPERATOR_NAMES = {"∑": "sum", "∏": "prod", "∫": "int"}


def mathml_to_omml_py(math_elem: etree._Element) -> etree._Element:
    omath = etree.Element(qname(M_NS, "oMath"))
    _convert_sequence(list(math_elem), omath)
    return omath


def combine_equation_array(equations: Sequence[etree._Element]) -> etree._Element:
    """Combine line-level equations into a native multiline layout.

    Rows that all contain a top-level relation use a two-column OMML matrix so
    the relation column aligns in Word and LibreOffice without exposing the
    literal ``&`` marker used by Word-only equation arrays. Other rows fall
    back to a one-column ``m:eqArr``.
    """
    if len(equations) < 2:
        raise ValueError("An equation array requires at least two lines")

    split_rows = [_split_at_relation(equation) for equation in equations]
    if all(row is not None for row in split_rows):
        return _relation_alignment_matrix([row for row in split_rows if row is not None])

    omath = etree.Element(qname(M_NS, "oMath"))
    equation_array = etree.SubElement(omath, qname(M_NS, "eqArr"))
    for equation in equations:
        line = etree.SubElement(equation_array, qname(M_NS, "e"))
        for child in equation:
            line.append(copy.deepcopy(child))
    return omath


def _split_at_relation(
    equation: etree._Element,
) -> tuple[list[etree._Element], list[etree._Element]] | None:
    """Split top-level OMML children immediately before the first relation."""
    children = list(equation)
    for index, child in enumerate(children):
        if child.tag != qname(M_NS, "r"):
            continue
        text_node = child.find(qname(M_NS, "t"))
        text = text_node.text if text_node is not None else None
        if not text:
            continue
        positions = [text.find(symbol) for symbol in RELATION_SYMBOLS if symbol in text]
        if not positions:
            continue
        position = min(positions)
        left = [copy.deepcopy(item) for item in children[:index]]
        right = [copy.deepcopy(item) for item in children[index + 1 :]]

        if position:
            left_run = copy.deepcopy(child)
            left_text = left_run.find(qname(M_NS, "t"))
            assert left_text is not None
            left_text.text = text[:position]
            left.append(left_run)

        right_run = copy.deepcopy(child)
        right_text = right_run.find(qname(M_NS, "t"))
        assert right_text is not None
        right_text.text = text[position:]
        right.insert(0, right_run)
        return left, right
    return None


def _relation_alignment_matrix(
    rows: Sequence[tuple[list[etree._Element], list[etree._Element]]],
) -> etree._Element:
    omath = etree.Element(qname(M_NS, "oMath"))
    matrix = etree.SubElement(omath, qname(M_NS, "m"))
    properties = etree.SubElement(matrix, qname(M_NS, "mPr"))
    etree.SubElement(properties, qname(M_NS, "plcHide"), {qname(M_NS, "val"): "1"})
    columns = etree.SubElement(properties, qname(M_NS, "mcs"))
    for justification in ("right", "left"):
        column = etree.SubElement(columns, qname(M_NS, "mc"))
        column_properties = etree.SubElement(column, qname(M_NS, "mcPr"))
        etree.SubElement(column_properties, qname(M_NS, "count"), {qname(M_NS, "val"): "1"})
        etree.SubElement(
            column_properties,
            qname(M_NS, "mcJc"),
            {qname(M_NS, "val"): justification},
        )

    for left, right in rows:
        matrix_row = etree.SubElement(matrix, qname(M_NS, "mr"))
        for cell_children in (left, right):
            cell = etree.SubElement(matrix_row, qname(M_NS, "e"))
            cell.extend(cell_children)
    return omath


def _is_nary_operator_group(elem: etree._Element) -> bool:
    """True for a ``munderover`` that is a bounded big operator (∑, ∏, ∫).

    Deliberately narrow. ``lim(x->0)`` is a ``munder`` whose base is an ``mi``
    reading "lim"; an annotated reaction arrow is a ``mover``. Neither is an
    n-ary object, and both must keep their ``m:limLow``/``m:limUpp`` shape with
    the body left as a following sibling, so this checks the tag, the base
    being an operator (``mo``), *and* the operator character.
    """
    if etree.QName(elem).localname != "munderover":
        return False
    base = elem[0] if len(elem) else None
    if base is None or etree.QName(base).localname != "mo":
        return False
    return (base.text or "").strip() in _NARY_OPERATOR_NAMES


def _convert_sequence(children: list[etree._Element], parent: etree._Element) -> None:
    """Convert a run of MathML siblings, nesting an n-ary operator's operand.

    In MathML the operand of a big operator is a *sibling* of the
    ``munderover``, not a child of it — ``_nary_mathml`` (core.py) emits
    ``<mrow><munderover>…</munderover><body/></mrow>``. In OMML the operand
    belongs inside the ``m:nary``'s own ``m:e`` slot, which is what Word and
    Office's MML2OMML.XSL both produce. Bridging the two needs a view of the
    sibling list, so every place that converts a sequence of MathML children
    goes through here rather than looping over ``_convert`` directly.

    The operand is **the rest of the enclosing sequence**. ``_nary_mathml``
    wraps the operator and its body in an ``mrow`` of exactly two children, so
    that ``mrow`` boundary is precisely the operand's scope: in
    ``e^x = sum(n=0,oo) x^n/n!`` only the fraction is absorbed, because the
    ``e^x =`` prefix lives in the *outer* ``mrow``. MML2OMML.XSL reaches the
    same answer by a different route — it takes the single
    ``following-sibling::*[1]`` and then merges adjacent token elements into
    one run — and the two rules coincide for every shape MathFmt emits.
    Taking the rest of the sequence, rather than only the next sibling, is the
    safer reading for foreign MathML: under-scoping would silently render part
    of the operand as though it sat outside the operator.
    """
    for index, child in enumerate(children):
        if _is_nary_operator_group(child):
            _nary(child, parent, children[index + 1 :])
            return
        _convert(child, parent)


def _convert(elem: etree._Element, parent: etree._Element) -> None:
    tag = etree.QName(elem).localname

    if tag not in MATHML_TAGS:
        for child in elem:
            _convert(child, parent)
        return

    if tag == "mi":
        _text_run(parent, elem.text or "", plain=elem.get("mathvariant") == "normal")
    elif tag == "mtext":
        _text_run(parent, elem.text or "", plain=True)
    elif tag == "mn":
        _text_run(parent, elem.text or "")
    elif tag == "mo":
        text = elem.text or ""
        if text != INVISIBLE_TIMES:
            _text_run(parent, text)
    elif tag == "mfrac":
        _fraction(elem, parent)
    elif tag == "msqrt":
        _radical(elem, parent)
    elif tag == "mroot":
        _radical_with_degree(elem, parent)
    elif tag == "msup":
        _script(elem, parent, "sSup", "sup")
    elif tag == "msub":
        _script(elem, parent, "sSub", "sub")
    elif tag == "msubsup":
        _subsup(elem, parent)
    elif tag == "mfenced":
        _delimiter(elem, parent)
    elif tag == "munder":
        _limit(elem, parent)
    elif tag == "mover":
        if elem.get("accent") == "true":
            _accent(elem, parent)
        else:
            _limit_upper(elem, parent)
    elif tag == "munderover":
        _nary(elem, parent)
    elif tag == "mtable":
        _matrix(elem, parent)
    elif tag == "mrow":
        _convert_sequence(list(elem), parent)


def _text_run(parent: etree._Element, text: str, *, plain: bool = False) -> None:
    r = etree.SubElement(parent, qname(M_NS, "r"))
    if plain:
        r_pr = etree.SubElement(r, qname(M_NS, "rPr"))
        style = etree.SubElement(r_pr, qname(M_NS, "sty"))
        style.set(qname(M_NS, "val"), "p")
    t = etree.SubElement(r, qname(M_NS, "t"))
    t.text = text
    if text[:1].isspace() or text[-1:].isspace():
        t.set(qname(XML_NS, "space"), "preserve")


def _fraction(elem: etree._Element, parent: etree._Element) -> None:
    f = etree.SubElement(parent, qname(M_NS, "f"))
    num = etree.SubElement(f, qname(M_NS, "num"))
    if len(elem) > 0:
        _convert(elem[0], num)
    den = etree.SubElement(f, qname(M_NS, "den"))
    if len(elem) > 1:
        _convert(elem[1], den)


def _radical(elem: etree._Element, parent: etree._Element) -> None:
    rad = etree.SubElement(parent, qname(M_NS, "rad"))
    rad_pr = etree.SubElement(rad, qname(M_NS, "radPr"))
    deg_hide = etree.SubElement(rad_pr, qname(M_NS, "degHide"))
    deg_hide.set(qname(M_NS, "val"), "1")
    etree.SubElement(rad, qname(M_NS, "deg"))
    e = etree.SubElement(rad, qname(M_NS, "e"))
    _convert_sequence(list(elem), e)


def _radical_with_degree(elem: etree._Element, parent: etree._Element) -> None:
    """Build an n-th root ``m:rad`` for MathML ``mroot`` (base, index children).

    Unlike :func:`_radical`, the degree is visible: ``degHide`` is ``0`` and
    ``m:deg`` is filled in. ``m:deg`` must be created before ``m:e`` — OMML's
    ``CT_Rad`` fixes that child order.
    """
    children = list(elem)
    if len(children) < 2:
        raise OmmlConversionError(f"mroot requires a base and a degree, got {len(children)} child(ren)")
    rad = etree.SubElement(parent, qname(M_NS, "rad"))
    rad_pr = etree.SubElement(rad, qname(M_NS, "radPr"))
    deg_hide = etree.SubElement(rad_pr, qname(M_NS, "degHide"))
    deg_hide.set(qname(M_NS, "val"), "0")
    deg = etree.SubElement(rad, qname(M_NS, "deg"))
    e = etree.SubElement(rad, qname(M_NS, "e"))
    _convert(children[0], e)
    _convert(children[1], deg)


def _script(
    elem: etree._Element,
    parent: etree._Element,
    container: str,
    script_role: str,
) -> None:
    container_elem = etree.SubElement(parent, qname(M_NS, container))
    e = etree.SubElement(container_elem, qname(M_NS, "e"))
    if len(elem) > 0:
        _convert(elem[0], e)
    script = etree.SubElement(container_elem, qname(M_NS, script_role))
    if len(elem) > 1:
        _convert(elem[1], script)


def _subsup(elem: etree._Element, parent: etree._Element) -> None:
    ss = etree.SubElement(parent, qname(M_NS, "sSubSup"))
    e = etree.SubElement(ss, qname(M_NS, "e"))
    if len(elem) > 0:
        _convert(elem[0], e)
    sub = etree.SubElement(ss, qname(M_NS, "sub"))
    if len(elem) > 1:
        _convert(elem[1], sub)
    sup = etree.SubElement(ss, qname(M_NS, "sup"))
    if len(elem) > 2:
        _convert(elem[2], sup)


def _delimiter(elem: etree._Element, parent: etree._Element) -> None:
    d = etree.SubElement(parent, qname(M_NS, "d"))
    d_pr = etree.SubElement(d, qname(M_NS, "dPr"))
    beg = etree.SubElement(d_pr, qname(M_NS, "begChr"))
    beg.set(qname(M_NS, "val"), elem.get("open", "("))
    end = etree.SubElement(d_pr, qname(M_NS, "endChr"))
    end.set(qname(M_NS, "val"), elem.get("close", ")"))
    e = etree.SubElement(d, qname(M_NS, "e"))
    _convert_sequence(list(elem), e)


def _limit(elem: etree._Element, parent: etree._Element) -> None:
    lim_low = etree.SubElement(parent, qname(M_NS, "limLow"))
    e = etree.SubElement(lim_low, qname(M_NS, "e"))
    if len(elem) > 0:
        _convert(elem[0], e)
    lim = etree.SubElement(lim_low, qname(M_NS, "lim"))
    if len(elem) > 1:
        _convert(elem[1], lim)


def _limit_upper(elem: etree._Element, parent: etree._Element) -> None:
    lim_upp = etree.SubElement(parent, qname(M_NS, "limUpp"))
    e = etree.SubElement(lim_upp, qname(M_NS, "e"))
    if len(elem) > 0:
        _convert(elem[0], e)
    lim = etree.SubElement(lim_upp, qname(M_NS, "lim"))
    if len(elem) > 1:
        _convert(elem[1], lim)


def _nary(
    elem: etree._Element,
    parent: etree._Element,
    operand: Sequence[etree._Element] = (),
) -> None:
    """Build a native ``m:nary`` (big operator with both bounds) from a MathML
    ``munderover``, nesting ``operand`` — the operator's MathML siblings, see
    :func:`_convert_sequence` — inside its ``m:e``.

    ``munderover`` over an n-ary operator is the only shape ``_nary_mathml``
    (core.py) produces for a bounded ``sum``/``prod``, always as ``(operator,
    under-bound, over-bound)``. (With a single bound it emits a bare ``mo``
    instead, so there is no ``munder``/``mover`` big-operator case to handle,
    and ``int(...)`` uses ``msubsup`` — reaching ``m:sSubSup`` — throughout.)

    This is what Word itself writes for ``∑_{i=1}^{n} i``: ``m:nary`` with
    ``m:naryPr``, ``m:sub``, ``m:sup``, and the operand inside ``m:e``. Leaving
    ``m:e`` empty and letting the operand fall out as a following sibling is
    schema-valid and renders in the right visual order, but Word's equation
    editor then shows an empty operand placeholder with the body sitting
    outside the template. ``m:limLow``/``m:limUpp`` nested together is not an
    alternative: that is Word's shape for a *stacked* under/over annotation,
    not a big-operator template, and has no room for the operator's own glyph
    alongside its bounds.
    """
    children = list(elem)
    if len(children) < 3:
        raise OmmlConversionError(
            f"munderover requires a base, an under bound, and an over bound, got {len(children)} child(ren)"
        )
    nary = etree.SubElement(parent, qname(M_NS, "nary"))
    nary_pr = etree.SubElement(nary, qname(M_NS, "naryPr"))
    chr_el = etree.SubElement(nary_pr, qname(M_NS, "chr"))
    chr_el.set(qname(M_NS, "val"), children[0].text or "")
    lim_loc = etree.SubElement(nary_pr, qname(M_NS, "limLoc"))
    lim_loc.set(qname(M_NS, "val"), "undOvr")
    # Without m:grow Word will not stretch the operator glyph to a tall
    # operand, so "sum(i=1,n) (a+b)/c" renders a small ∑ beside a full-height
    # fraction. MML2OMML.XSL writes grow="1" for every character in its
    # big-operator list, which contains all of _NARY_OPERATOR_NAMES, so this is
    # unconditional. "1"/"0" is both Office's spelling here and this file's own
    # ST_OnOff convention (compare _radical's degHide) — unlike subHide/supHide
    # just below, where Office writes "off"/"on" and this file deliberately
    # keeps the equivalent "0"/"1".
    grow = etree.SubElement(nary_pr, qname(M_NS, "grow"))
    grow.set(qname(M_NS, "val"), "1")
    sub_hide = etree.SubElement(nary_pr, qname(M_NS, "subHide"))
    sub_hide.set(qname(M_NS, "val"), "0")
    sup_hide = etree.SubElement(nary_pr, qname(M_NS, "supHide"))
    sup_hide.set(qname(M_NS, "val"), "0")
    sub = etree.SubElement(nary, qname(M_NS, "sub"))
    _convert(children[1], sub)
    sup = etree.SubElement(nary, qname(M_NS, "sup"))
    _convert(children[2], sup)
    # m:e stays present even with no operand — CT_Nary requires it, and Word
    # writes an empty one for a bare "∑_{i=1}^{n}".
    e = etree.SubElement(nary, qname(M_NS, "e"))
    _convert_sequence(list(operand), e)


def _accent(elem: etree._Element, parent: etree._Element) -> None:
    children = list(elem)
    if len(children) < 2:
        raise OmmlConversionError(
            f"accented mover requires a base and an accent character, got {len(children)} child(ren)"
        )
    mathml_char = (children[1].text or "").strip()
    char = OMML_ACCENT_CHARS.get(mathml_char)
    if char is None:
        raise OmmlConversionError(f"unsupported MathML accent character {mathml_char!r}")
    acc = etree.SubElement(parent, qname(M_NS, "acc"))
    acc_pr = etree.SubElement(acc, qname(M_NS, "accPr"))
    chr_el = etree.SubElement(acc_pr, qname(M_NS, "chr"))
    chr_el.set(qname(M_NS, "val"), char)
    e = etree.SubElement(acc, qname(M_NS, "e"))
    _convert(children[0], e)


def _matrix(elem: etree._Element, parent: etree._Element) -> None:
    m = etree.SubElement(parent, qname(M_NS, "m"))
    etree.SubElement(m, qname(M_NS, "mPr"))
    # Add base justification for all columns
    for child in elem:
        if etree.QName(child).localname == "mtr":
            mr = etree.SubElement(m, qname(M_NS, "mr"))
            for td in child:
                e = etree.SubElement(mr, qname(M_NS, "e"))
                _convert_sequence(list(td), e)


# -- Reverse direction: OMML -> MathFmt linear text -------------------------


class OmmlConversionError(ValueError):
    """Raised when a MathML/OMML construct cannot be converted in the requested direction —
    forward (unsupported accent character) or reverse (``omml_to_text`` cannot reverse it)."""


_REVERSE_OPERATORS = {
    "≠": "!=",
    "≤": "<=",
    "≥": ">=",
    "→": "->",
    "⇒": "=>",
    "±": "+/-",
}

_LIM_ARROW_BASES = {"->", "=>", "⇌"}  # `_reverse_operators` already ASCII-ifies → and ⇒

_PASSTHROUGH_CONTAINERS = {"oMath", "oMathPara"}


def omml_to_text(omath_elem: etree._Element) -> str:
    """Convert a native ``m:oMath``/``m:oMathPara`` element back to MathFmt's
    linear formula syntax — the reverse of :func:`mathml_to_omml_py`.

    Supports the constructs MathFmt's own OMML output uses: text runs, fractions
    (including derivative and partial-derivative fractions), radicals (both
    ``sqrt(...)`` and, via a visible ``m:deg``, the n-th root ``root(base,n)``),
    super/subscripts, delimited groups (parentheses, brackets, braces, bra-ket,
    vectors), limits / annotated reaction arrows, accents (``m:acc``,
    including a base of its own accent for a nested ``accent(accent(x,bar),vec)``),
    and bounded n-ary big operators (``m:nary``, e.g. ``sum(i=1,n) i`` /
    ``prod(k=1,m) k``) — an ``m:nary`` missing one of its two bounds, or
    naming an operator character this converter doesn't recognize, still
    raises :class:`OmmlConversionError` rather than guessing.
    Constructs this converter does not reverse — matrices, piecewise/cases tables, and **MathFmt's own
    multi-line/aligned equation output** (also built from a native OMML matrix
    or ``m:eqArr``, despite not being a mathematical matrix) — raise
    :class:`OmmlConversionError` naming the unsupported element instead of
    guessing at a wrong answer.

    The result re-parses (via :func:`formula_to_mathml <mathfmt.core.formula_to_mathml>`)
    to an equivalent formula, not necessarily byte-identical input text — for
    example, both ``2*x`` and ``2x`` round-trip to ``2x``. Chemistry formulas and
    reactions are specifically detected and reconstructed in their original bare
    form (``H2O``, ``(OH)2``, ...) rather than a generic subscript, so they
    re-parse through MathFmt's dedicated chemistry grammar and keep their
    upright element-symbol styling. That detection is a heuristic keyed on
    MathFmt's own upright-run styling plus an all-digit subscript, not a
    guarantee: this function accepts any ``m:oMath``, not just MathFmt's own
    output, so hand-authored OMML that happens to combine both for an
    unrelated reason would be misread as chemistry. See
    ``docs/formula-syntax.md`` section 9 for the exact rule.
    """
    tag = etree.QName(omath_elem).localname
    if tag not in _PASSTHROUGH_CONTAINERS:
        raise OmmlConversionError(f"Expected m:oMath or m:oMathPara, got m:{tag}")
    return _emit_children(omath_elem)


def _emit_children(elem: etree._Element) -> str:
    return _join_emitted(list(elem))


def _join_emitted(children: list[etree._Element]) -> str:
    """Concatenate each child's emitted text, inserting ``*`` at any boundary
    where the tokenizer would otherwise merge two atoms into one identifier or
    number (e.g. adjacent runs ``d`` and ``s`` reconstructing as ``ds`` instead
    of ``d`` times ``s``). An explicit ``*`` is semantically identical to the
    implicit multiplication it replaces, so this is always safe, even where
    unnecessary — except between two chemistry-styled atoms (adjacent element
    symbols like ``O`` then ``H`` in ``OH``), where bare adjacency is exactly
    the shape MathFmt's chemistry grammar looks for; inserting ``*`` there
    would make it reparse as ordinary algebra instead.
    """
    result = ""
    prev_child: etree._Element | None = None
    for child in children:
        fragment = _emit(child)
        if result and fragment and _merge_risk(result[-1], fragment[0]):
            if not (_is_plain_atom(prev_child) and _is_plain_atom(child)):
                result += "*"
        result += fragment
        prev_child = child
    return result


def _merge_risk(prev_char: str, next_char: str) -> bool:
    """True where the tokenizer could read two adjacent atoms as one token.

    A letter followed by a letter or digit can extend an identifier (``d`` +
    ``s`` -> ``ds``; ``d`` + ``2`` -> ``d2``, MathFmt's own auto-subscript
    shape). Two digits can extend a number. A digit followed by a letter is
    never risky — MathFmt's ``NUMBER`` token stops at the first non-digit, so
    ``2`` + ``H`` already tokenizes as two atoms (this is the ordinary
    coefficient shorthand ``2x``, and also lets a chemistry count like ``2H2O``
    round-trip without an inserted ``*`` breaking its bare-adjacency shape).
    """
    if prev_char.isalpha():
        return next_char.isalnum()
    if prev_char.isdigit():
        return next_char.isdigit()
    return False


def _is_plain_run(elem: etree._Element) -> bool:
    """True for a text run styled upright/plain (``m:rPr/m:sty[@m:val='p']``),
    which is how MathFmt marks chemistry element symbols — they're generated
    as MathML ``mtext`` (see ``_parse_chemical_formula`` in core.py), and the
    ``mtext`` branch of ``_convert`` above always sets ``plain=True``.
    """
    if etree.QName(elem).localname != "r":
        return False
    r_pr = _find(elem, "rPr")
    if r_pr is None:
        return False
    sty = _find(r_pr, "sty")
    return sty is not None and sty.get(qname(M_NS, "val")) == "p"


def _is_plain_atom(elem: etree._Element | None) -> bool:
    """Like :func:`_is_plain_run`, but also true for a chemistry element with
    its subscript count attached (``m:sSub`` whose base is a plain run), so
    adjacency detection sees ``H2`` next to ``O`` the same way it sees a bare
    ``O`` next to ``H``.
    """
    if elem is None:
        return False
    if _is_plain_run(elem):
        return True
    if etree.QName(elem).localname == "sSub":
        base = _find(elem, "e")
        return base is not None and len(base) == 1 and _is_plain_run(base[0])
    return False


def _emit(elem: etree._Element) -> str:
    tag = etree.QName(elem).localname
    if tag in _PASSTHROUGH_CONTAINERS:
        return _emit_children(elem)
    if tag == "r":
        return _reverse_operators(_run_text(elem))
    if tag == "f":
        return _emit_fraction(elem)
    if tag == "rad":
        return _emit_radical(elem)
    if tag == "sSup":
        return _emit_operand(_find(elem, "e")) + "^" + _emit_operand(_find(elem, "sup"))
    if tag == "sSub":
        return _emit_subscript(elem)
    if tag == "sSubSup":
        return (
            _emit_operand(_find(elem, "e"))
            + "_"
            + _emit_operand(_find(elem, "sub"))
            + "^"
            + _emit_operand(_find(elem, "sup"))
        )
    if tag == "d":
        beg, end = _delimiter_chars(elem)
        return beg + _emit_children(_require(elem, "e")) + end
    if tag in {"limLow", "limUpp"}:
        return _emit_limit(elem)
    if tag == "acc":
        return _emit_accent(elem)
    if tag == "nary":
        return _emit_nary(elem)
    raise OmmlConversionError(f"omml_to_text does not support m:{tag} elements")


def _run_text(elem: etree._Element) -> str:
    t = elem.find(qname(M_NS, "t"))
    return (t.text or "") if t is not None else ""


def _find(elem: etree._Element, name: str) -> etree._Element | None:
    return elem.find(qname(M_NS, name))


def _require(elem: etree._Element, name: str) -> etree._Element:
    found = _find(elem, name)
    if found is None:
        raise OmmlConversionError(f"m:{etree.QName(elem).localname} is missing its m:{name} child")
    return found


_PARTIAL_SYMBOL = "∂"


def _emit_fraction(elem: etree._Element) -> str:
    """Reconstruct ``m:f`` as ``num/den`` — except a partial derivative.

    A partial derivative's numerator/denominator each start with a literal
    ``∂`` run (see ``docs/formula-syntax.md``'s physics notation table). ``∂``
    is only ever accepted by the tokenizer through the dedicated
    ``partial(f, x)`` call syntax or an *unparenthesized* ``∂f/∂x`` — and every
    other fraction operand here needs parentheses for correct precedence — so
    that case must use the explicit call form instead of generic division.
    """
    num, den = _find(elem, "num"), _find(elem, "den")
    partial_num = _strip_partial_symbol(num)
    partial_den = _strip_partial_symbol(den)
    if partial_num is not None and partial_den is not None:
        if not partial_num or not partial_den:
            # A bare "∂" with nothing after it (e.g. a malformed or
            # hand-authored m:f) has no valid linear-text form: "∂" is only
            # ever accepted through partial(f, x) or unparenthesized ∂f/∂x,
            # never on its own. Raise rather than emit unparseable text.
            raise OmmlConversionError(
                "omml_to_text cannot reconstruct a partial derivative with an empty numerator or denominator"
            )
        return f"partial({partial_num},{partial_den})"
    num_text, den_text = _emit_operand(num), _emit_operand(den)
    if _PARTIAL_SYMBOL in num_text or _PARTIAL_SYMBOL in den_text:
        raise OmmlConversionError(
            "omml_to_text cannot reconstruct this fraction: it contains a bare '∂' outside the partial(f, x) shape"
        )
    return num_text + "/" + den_text


def _strip_partial_symbol(container: etree._Element | None) -> str | None:
    """Return the container's text with a leading ``∂`` run removed, or None."""
    if container is None or len(container) == 0:
        return None
    first = container[0]
    if etree.QName(first).localname != "r" or _run_text(first) != _PARTIAL_SYMBOL:
        return None
    return _join_emitted(list(container)[1:])


def _emit_radical(elem: etree._Element) -> str:
    """Reconstruct ``m:rad`` as ``sqrt(base)`` or, for a visible degree,
    ``root(base,degree)``.

    Word writes ``m:deg`` for a square root too (with ``degHide`` set), but
    empty — that is what distinguishes an ordinary square root from an n-th
    root here: an absent or empty ``m:deg`` means ``sqrt``, a non-empty one
    means ``root``.
    """
    base_text = _emit_children(_require(elem, "e"))
    deg = _find(elem, "deg")
    if deg is not None and len(deg) > 0:
        return f"root({base_text},{_emit_children(deg)})"
    return f"sqrt({base_text})"


def _emit_subscript(elem: etree._Element) -> str:
    """Reconstruct ``m:sSub`` as ``base_sub`` — except a chemistry element
    count (``H2``) or a parenthesized chemistry group count (``(OH)2``), which
    need the bare ``base`` + ``sub`` shape (no ``_``) to re-trigger MathFmt's
    chemistry grammar on reparse, matching how they were written in the first
    place. MathFmt's forward converter only ever puts a parenthesized group
    behind ``sSub`` for this chemistry case — an ordinary group directly
    followed by a digit parses as multiplication, not a subscript.

    The chemistry-vs-generic-subscript signal is the OMML plain/upright run
    styling MathFmt's own chemistry grammar marks element symbols with — a
    heuristic, not a guarantee, since ``omml_to_text`` also accepts
    hand-authored OMML that could style a subscript base upright for an
    unrelated reason. Requiring the subscript itself to be purely digits (an
    element count is always one) narrows that: a coincidental false positive
    now needs both an upright base *and* an all-digit subscript, e.g. a
    genuine ``x_2`` where ``x`` happens to be styled upright.
    """
    base, sub = _find(elem, "e"), _find(elem, "sub")
    sub_text = _emit_operand(sub)
    if sub_text.isdigit() and base is not None and len(base) == 1:
        inner = base[0]
        if _is_plain_run(inner) or _is_chemistry_group(inner):
            return _emit(inner) + sub_text
    return _emit_operand(base) + "_" + sub_text


def _is_chemistry_group(elem: etree._Element) -> bool:
    """True for a ``m:d`` (parenthesized group) whose contents are entirely
    chemistry-styled atoms — plain runs, or a nested element+count like the
    ``O`` + subscript ``4`` in ``(SO4)`` — e.g. the ``(OH)`` in ``(OH)2`` or
    the ``(SO4)`` in ``(SO4)2``.
    """
    if etree.QName(elem).localname != "d":
        return False
    inner = _find(elem, "e")
    if inner is None or len(inner) == 0:
        return False
    return all(_is_plain_atom(child) for child in inner)


def _emit_operand(elem: etree._Element | None) -> str:
    """Emit a fraction/script operand, parenthesizing it unless atomic.

    Always-safe rather than minimal: the reconstructed text is a flat string
    that must respect ASCII operator precedence on its own — there is no
    structural nesting left to fall back on the way there is in OMML/MathML —
    so anything beyond a single identifier or number run is grouped.
    """
    if elem is None or len(elem) == 0:
        return ""
    if len(elem) == 1 and etree.QName(elem[0]).localname == "r":
        return _emit(elem[0])
    return "(" + _emit_children(elem) + ")"


def _delimiter_chars(elem: etree._Element) -> tuple[str, str]:
    d_pr = _find(elem, "dPr")
    beg, end = "(", ")"
    if d_pr is not None:
        beg_chr = _find(d_pr, "begChr")
        end_chr = _find(d_pr, "endChr")
        if beg_chr is not None:
            beg = beg_chr.get(qname(M_NS, "val"), beg)
        if end_chr is not None:
            end = end_chr.get(qname(M_NS, "val"), end)
    return beg, end


def _emit_limit(elem: etree._Element) -> str:
    """``limLow``/``limUpp`` represent two unrelated MathFmt constructs that
    happen to share one OMML shape: the ``lim`` function, and an annotated
    reaction arrow (``=>[heat]``). Disambiguate on the base text rather than
    guessing which one was meant.
    """
    base = _emit_children(_require(elem, "e"))
    annotation = _emit_children(_require(elem, "lim"))
    if base.strip() == "lim":
        return f"lim({annotation})"
    if base in _LIM_ARROW_BASES:
        return f"{base}[{annotation}]"
    raise OmmlConversionError(
        f"omml_to_text only supports m:limLow/m:limUpp for 'lim(...)' or an annotated "
        f"reaction arrow, got base {base!r}"
    )


def _emit_nary(elem: etree._Element) -> str:
    """Reconstruct ``m:nary`` as ``name(sub,sup)`` followed by its operand.

    Requires both ``m:sub`` and ``m:sup`` to be present and non-empty — a
    single-bound or bound-less ``m:nary`` has no ``sum(a,b)``-shaped linear
    form, so it raises rather than guessing at a missing bound.

    The operand normally lives inside ``m:e`` — that is what Word writes, and
    what MathFmt's own :func:`_nary` writes too — and is emitted from there.
    An ``m:nary`` whose ``m:e`` is empty is still legal (Word writes one for a
    bare ``∑_{i=1}^{n}``); anything following it in the OMML is picked up by
    the normal sibling-concatenation loop in ``_join_emitted`` once this
    function returns, so the reconstructed text is the same either way.
    """
    nary_pr = _find(elem, "naryPr")
    chr_el = _find(nary_pr, "chr") if nary_pr is not None else None
    char = chr_el.get(qname(M_NS, "val")) if chr_el is not None else None
    name = _NARY_OPERATOR_NAMES.get(char or "")
    if name is None:
        raise OmmlConversionError(f"omml_to_text does not support the m:nary operator {char!r}")
    sub, sup = _find(elem, "sub"), _find(elem, "sup")
    if sub is None or len(sub) == 0 or sup is None or len(sup) == 0:
        raise OmmlConversionError(
            f"omml_to_text requires both m:sub and m:sup to reconstruct m:nary as {name}(...)"
        )
    e = _find(elem, "e")
    operand = _emit_children(e) if e is not None else ""
    return f"{name}({_emit_children(sub)},{_emit_children(sup)})" + operand


# ISO/IEC 29500's CT_AccPr defines U+0302 COMBINING CIRCUMFLEX ACCENT (hat) as
# the accent's value when m:accPr — or its m:chr child — is omitted entirely;
# m:accPr is itself minOccurs="0" in CT_Acc. That is the format's own
# documented default, not this converter guessing, so an absent property is
# honored rather than rejected. In practice this branch serves third-party or
# hand-authored OMML: MathFmt's own writer and Office's MML2OMML.XSL both
# always write m:chr explicitly, even for hat.
_DEFAULT_ACCENT_CHAR = OMML_ACCENT_CHARS[ACCENT_CHARS["hat"]]


def _emit_accent(elem: etree._Element) -> str:
    acc_pr = _find(elem, "accPr")
    chr_el = _find(acc_pr, "chr") if acc_pr is not None else None
    # A present m:chr with no m:val is a different, narrower case: ISO/IEC
    # 29500 treats that as the character being absent, not "use the default"
    # (the default applies only when m:chr/m:accPr is missing outright), so
    # it falls through to the same "unsupported character" raise below rather
    # than silently becoming hat.
    char = chr_el.get(qname(M_NS, "val")) if chr_el is not None else _DEFAULT_ACCENT_CHAR
    name = ACCENT_NAMES.get(char or "")
    if name is None:
        raise OmmlConversionError(f"omml_to_text does not support the accent character {char!r}")
    return f"accent({_emit_children(_require(elem, 'e'))},{name})"


def _reverse_operators(text: str) -> str:
    for symbol, ascii_form in _REVERSE_OPERATORS.items():
        if symbol in text:
            text = text.replace(symbol, ascii_form)
    return text
