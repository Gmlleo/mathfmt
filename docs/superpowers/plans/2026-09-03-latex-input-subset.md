# LaTeX Input Subset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let MathFmt accept a closed, documented subset of LaTeX macros as formula input, so documents whose formulas were pasted from papers, textbooks, or AI output convert instead of failing to parse.

**Architecture:** A new isolated module `src/mathfmt/latex.py` expands LaTeX macros into MathFmt's existing linear syntax as a pure text-to-text transform, then hands the result to the unchanged `preprocess_formula` → `tokenize` → `Parser` pipeline. Three constructs have no linear equivalent and become new native AST nodes (`accent`, `root`, quoted text). The tokenizer only ever gains characters that today can only produce a tokenize error, so no input that works now can change behaviour.

**Tech Stack:** Python 3.10+, lxml, pytest. No new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-09-03-latex-input-and-gui-preview-design.md`

---

## Deviation from the spec

Spec §3.2 proposes `text(已知)` as the upright-text construct. That cannot work: `TOKEN_RE`'s IDENT class matches only ASCII letters, Greek letters, and a fixed symbol set, so `已` raises a tokenize error before the parser sees anything.

This plan uses a **quoted string atom** instead: `\text{已知}` expands to `"已知"`. A new `STRING` token matches `"[^"]*"`. This is the same class of additive change as `∂` `∇` `∓` — `"` today can only produce a tokenize error — and it keeps `expand_latex(source: str) -> str` (spec §2.2) unchanged, which a side-table placeholder scheme would not.

## File Structure

| File | Responsibility |
|---|---|
| `src/mathfmt/latex.py` (create) | LaTeX macro expansion, text → text. Knows nothing about lxml, MathML, or OMML. Raises `FormulaError` for anything outside the subset. |
| `tests/test_latex.py` (create) | Table-driven expansion tests, one case per documented macro, plus every rejection path. |
| `src/mathfmt/core.py` (modify) | Tokenizer character classes and operator sets; three new AST nodes and their MathML; `_suggest_fix` entries; `formula_to_mathml` wiring; two scanner detectors. |
| `src/mathfmt/omml.py` (modify) | `m:acc` for accents, `m:rad` with a visible degree for n-th roots, and the matching `omml_to_text` reversals. |
| `tests/test_core.py` (modify) | Tokenizer additions, new node parsing/MathML, scanner behaviour. |
| `tests/test_omml.py` (modify) | OMML forward output and `omml_to_text` round trips. |
| `docs/formula-syntax.md` (modify) | New section 10 plus updates to the tokenizer and MathML-mapping tables. |

`latex.py` imports only `re` and `FormulaError` from `core`. Nothing in `core` imports `latex` except the single wiring branch in `formula_to_mathml` (Task 12), which imports lazily inside the function to avoid a circular import.

---

## Task 1: Tokenizer additions — `∇` `∓` (`∂` withdrawn during implementation)

> **Revised after code review.** This task originally added `∂` as well. It must not:
> `∂` is already in `MATH_CHARS` (`core.py:70`), so `∂` spans are discovered by the
> scanner and were protected only by `formula_to_mathml` raising, which marks the
> candidate `selected: false`. Making `∂` tokenizable turned `∂^2u/∂x^2 = 0` from a
> reviewable parse error into a silently wrong auto-conversion — the preprocessing
> only rewrites the plain `∂ IDENT / ∂ IDENT` shape, and left-associative division
> then yields `(∂²·u / ∂) · x²`. Keep `∇` and `∓`; drop `∂`. See the revision note in
> spec §2.3. The lesson generalises: "this character can only produce a tokenize
> error today" proves lexer-level safety, not pipeline-level safety.

**Files:**
- Modify: `src/mathfmt/core.py:373-383` (TOKEN_RE), `src/mathfmt/core.py:606-620` (`parse_add`), `src/mathfmt/core.py:664-667` (`parse_unary`)
- Test: `tests/test_core.py`

These three characters are currently unmatched by `TOKEN_RE`, so every input containing them raises `FormulaError` today. Adding them to the existing character classes cannot change any input that currently succeeds.

`parse_unary` gains `±` as well as `∓`. Without it `\pm x` — a macro this version claims to support — would fail while `\mp x` succeeded.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("∇", "mi"),
        ("∂", "mi"),
        ("a ∓ b", "mo"),
        ("∓x", "mo"),
        ("±x", "mo"),
        ("∇f = 0", "mi"),
    ],
)
def test_new_symbol_characters_are_tokenized(source: str, expected: str) -> None:
    assert expected in local_tags(source)


def test_partial_derivative_preprocessing_still_wins_over_bare_partial() -> None:
    # ∂f/∂x must keep going through preprocess_formula into a stacked fraction,
    # not become three separate identifiers now that ∂ tokenizes on its own.
    assert "mfrac" in local_tags("∂f/∂x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_core.py -k "new_symbol_characters or preprocessing_still_wins" -v --no-cov`
Expected: the six parametrized cases FAIL with `FormulaError: Unrecognized formula text near: '∇'` (and similar); `test_partial_derivative_preprocessing_still_wins_over_bare_partial` PASSES already.

- [ ] **Step 3: Add the characters**

In `src/mathfmt/core.py`, `TOKEN_RE`, extend the IDENT alternative's final character class and the OP class:

```python
    r"(?P<IDENT>sqrt|lim|exp|sin|cos|tan|Delta|pi|inf|e[pv]|pPAIR|DERV\d+|[A-Za-z][A-Za-z0-9]*|[Α-Ωα-ω∞∫∑∏ℝℂℕℤℚℙℍℓ∂∇])|"
    r"(?P<OP><->|<=|>=|!=|<<|>>|~=|->|=>|\+/-|[+\-*/^=<>!±∓≠≤≥≈≅→⇒⇌·×÷_∈∉⊂⊆⊃⊇∪∩∧∨⊕⊗∝≡])|"
```

In `parse_add`, add `"∓"` to the operator set:

```python
        while self.current.kind == "OP" and self.current.value in {
            "+",
            "-",
            "±",
            "∓",
            "∪",
            "∩",
            "∧",
            "∨",
            "⊕",
        }:
```

In `parse_unary`, accept both signs as prefixes:

```python
    def parse_unary(self) -> Node:
        if self.current.kind == "OP" and self.current.value in {"+", "-", "±", "∓"}:
            return Node("unary", self.advance().value, (self.parse_unary(),))
        return self.parse_atom()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_core.py tests/test_omml.py -v --no-cov`
Expected: PASS, including every pre-existing test in both files.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/core.py tests/test_core.py
git commit -m "feat(core): tokenize the partial, nabla, and minus-plus characters"
```

---

## Task 2: `accent(x, bar)` — parsing and MathML

**Files:**
- Modify: `src/mathfmt/core.py` (module constants, `parse_atom` at `core.py:771`, new parser method, `node_to_mathml` at `core.py:907`)
- Test: `tests/test_core.py`

Follows the parser's existing functional-extension convention (`partial(f,x)`, `bra(a)`, `braket(a,b)` — see `_parse_physics_function` at `core.py:691`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
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
    assert excinfo.value.to_dict()["hint"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_core.py -k accent -v --no-cov`
Expected: FAIL. `accent(x,bar)` currently parses as a generic `function` node, so no `mover` element exists and `test_accent_produces_mover_with_accent_attribute` fails on `assert mover is not None`; the rejection tests fail because nothing raises.

- [ ] **Step 3: Implement the node**

Add the character table next to the other module-level constants in `src/mathfmt/core.py` (near `MATH_CHARS`):

```python
ACCENT_CHARS = {"bar": "‾", "vec": "→", "hat": "^", "dot": "˙", "ddot": "¨"}
```

In `parse_atom`, immediately after the existing physics-function branch:

```python
            if name in {"partial", "bra", "ket", "braket"} and self.current.kind == "LPAREN":
                return self._parse_physics_function(name, token)
            if name == "accent" and self.current.kind == "LPAREN":
                return self._parse_accent(token)
```

Add the parser method next to `_parse_physics_function`:

```python
    def _parse_accent(self, token: Token) -> Node:
        group = self.parse_group()
        inner = group.children[0]
        arguments = inner.children if inner.kind == "sequence" else (inner,)
        if len(arguments) != 2:
            raise FormulaError(
                "accent requires 2 arguments",
                position=token.start,
                expected="2 comma-separated arguments",
                found=str(len(arguments)),
                source=self.source,
            )
        kind_node = arguments[1]
        kind = kind_node.value if kind_node.kind == "identifier" else None
        if kind not in ACCENT_CHARS:
            raise FormulaError(
                f"Unknown accent kind: {kind_node.value or kind_node.kind}",
                position=token.start,
                expected="accent kind",
                found=str(kind_node.value or kind_node.kind),
                source=self.source,
            )
        return Node("accent", kind, (arguments[0],))
```

In `node_to_mathml`, add a branch before the `function` branch:

```python
    if node.kind == "accent":
        over = mml("mover", accent="true")
        over.append(node_to_mathml(node.children[0]))
        over.append(mml("mo", ACCENT_CHARS[node.value or "bar"]))
        return over
```

In `_suggest_fix`, add the hint rule alongside the existing ones:

```python
    if expected == "accent kind":
        return "An accent must be one of: bar, vec, hat, dot, ddot — e.g. accent(x,bar)."
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_core.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/core.py tests/test_core.py
git commit -m "feat(core): add the accent() construct and its MathML output"
```

---

## Task 3: Accents in OMML — `m:acc`

**Files:**
- Modify: `src/mathfmt/omml.py:166-169` (the `munder`/`mover` dispatch), new `_accent` function
- Test: `tests/test_omml.py`

`mover` is currently sent unconditionally to `_limit_upper` → `m:limUpp`, which is correct for MathFmt's annotated reaction arrows and wrong for an accent. Dispatch on the `accent` attribute so the existing path is untouched.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_omml.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_omml.py -k "m_acc or lim_upp" -v --no-cov`
Expected: `test_accent_produces_m_acc` FAILS on `assert acc is not None` (the accent currently emits `m:limUpp`); `test_annotated_arrow_still_uses_lim_upp` PASSES already and must keep passing.

- [ ] **Step 3: Implement the dispatch**

In `src/mathfmt/omml.py`, change the `mover` branch of `_convert`:

```python
    elif tag == "mover":
        if elem.get("accent") == "true":
            _accent(elem, parent)
        else:
            _limit_upper(elem, parent)
```

**Do not pass the MathML character through to OMML.** Task 2's code review established that the two notations want different codepoints, and that copying `children[1].text` verbatim would bake the wrong one into every Word document:

- MathML uses **spacing** forms, and Task 2's choices are correct there — U+203E `‾`, U+005E `^`, U+2192 `→`, U+02D9 `˙`, U+00A8 `¨` — matching what MathJax emits and the MathML operator dictionary's `&OverBar;`.
- Word's native accents are **combining** marks: U+0305 (bar), U+0302 (hat — also OMML's implicit default when `m:chr` is omitted), U+20D7 (vec), U+0307 (dot), U+0308 (ddot). U+2192 is especially wrong: it is a full-size arrow glyph, not the compact combining vector arrow.

So add an explicit mapping next to the other module constants:

```python
_OMML_ACCENT_CHARS = {"‾": "̅", "^": "̂", "→": "⃗", "˙": "̇", "¨": "̈"}
```

and the writer next to `_limit_upper`:

```python
def _accent(elem: etree._Element, parent: etree._Element) -> None:
    children = list(elem)
    mathml_char = (children[1].text or "").strip()
    char = _OMML_ACCENT_CHARS.get(mathml_char)
    if char is None:
        raise OmmlConversionError(f"unsupported MathML accent character {mathml_char!r}")
    acc = etree.SubElement(parent, qname(M_NS, "acc"))
    acc_pr = etree.SubElement(acc, qname(M_NS, "accPr"))
    chr_el = etree.SubElement(acc_pr, qname(M_NS, "chr"))
    chr_el.set(qname(M_NS, "val"), char)
    e = etree.SubElement(acc, qname(M_NS, "e"))
    _convert(children[0], e)
```

Raising rather than defaulting keeps the project's no-guessing rule: an accent character nobody mapped must fail loudly, not silently render as a bar.

Assert the exact codepoints in the tests (`chr_el.get(qname(M_NS, "val")) == "̅"`), not just that `m:chr` exists. Task 4's reverse mapping must invert this table, not `ACCENT_CHARS`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_omml.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/omml.py tests/test_omml.py
git commit -m "feat(omml): write accents as m:acc instead of m:limUpp"
```

---

## Task 4: Accents in `omml_to_text`

**Files:**
- Modify: `src/mathfmt/omml.py:411-441` (`_emit`)
- Test: `tests/test_omml.py`

Without this, `omml_to_text` raises `OmmlConversionError: omml_to_text does not support m:acc elements` for equations MathFmt itself now produces — a new gap in the v1.2 reverse capability.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_omml.py`:

```python
@pytest.mark.parametrize(
    "source", ["accent(x,bar)", "accent(F,vec)", "accent(y,hat)", "accent(q,dot)", "accent(q,ddot)"]
)
def test_accent_round_trips_through_omml_to_text(source: str) -> None:
    assert omml_to_text(omath_for(source)) == source
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_omml.py -k round_trips_through -v --no-cov`
Expected: FAIL with `OmmlConversionError: omml_to_text does not support m:acc elements`.

- [ ] **Step 3: Implement the reversal**

Add the reverse table next to the other module constants in `src/mathfmt/omml.py`:

**Do not write a new table.** Task 3's follow-up collapsed all three accent representations into one source of truth, `src/mathfmt/accents.py`, whose `ACCENTS` rows are `(kind name, MathML spacing character, Word combining mark)`. The reverse mapping already exists there:

```python
ACCENT_NAMES = {combining: name for name, _, combining in ACCENTS}
```

Import it — `from .accents import ACCENT_NAMES` — and key the lookup off the **combining** mark written into `m:accPr/m:chr`, which is what an `m:acc` element actually carries. A hand-written table here would reintroduce the drift that refactor removed, and `test_accent_table_is_unambiguous` would not catch it.

In `_emit`, add a branch before the final `raise`:

```python
    if tag == "acc":
        chr_el = elem.find(qname(M_NS, "accPr") + "/" + qname(M_NS, "chr"))
        char = chr_el.get(qname(M_NS, "val")) if chr_el is not None else "‾"
        name = ACCENT_NAMES.get(char or "")
        if name is None:
            raise OmmlConversionError(f"omml_to_text does not support the accent character {char!r}")
        return f"accent({_emit_children(_require(elem, 'e'))},{name})"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_omml.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/omml.py tests/test_omml.py
git commit -m "feat(omml): reverse m:acc back to accent() in omml_to_text"
```

---

## Task 5: `root(x, 3)` — parsing and MathML

**Files:**
- Modify: `src/mathfmt/core.py` (`parse_atom`, new parser method, `node_to_mathml`)
- Test: `tests/test_core.py`

`sqrt` accepts exactly one group and maps to `m:msqrt`; there is no `m:mroot`. `sqrt(x,3)` would silently render "x, 3" inside the radical, which is why the n-th root needs a real node.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
def test_root_produces_mroot() -> None:
    math = formula_to_mathml("root(x,3)")
    mroot = math.find(f".//{{{MML_NS}}}mroot")
    assert mroot is not None
    assert [etree.QName(child).localname for child in mroot] == ["mi", "mn"]


def test_root_degree_may_be_an_expression() -> None:
    assert "mroot" in local_tags("root(x,n+1)")


def test_sqrt_still_produces_msqrt() -> None:
    assert "msqrt" in local_tags("sqrt(x)")


@pytest.mark.parametrize("source", ["root(x)", "root(x,2,3)"])
def test_invalid_root_is_rejected(source: str) -> None:
    with pytest.raises(FormulaError):
        formula_to_mathml(source)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_core.py -k root -v --no-cov`
Expected: FAIL — `root(x,3)` parses as a generic `function` node, so no `mroot` element exists and nothing raises for the wrong argument counts. `test_sqrt_still_produces_msqrt` PASSES already.

- [ ] **Step 3: Implement the node**

In `parse_atom`, after the `accent` branch added in Task 2:

```python
            if name == "root" and self.current.kind == "LPAREN":
                return self._parse_root(token)
```

Add the parser method next to `_parse_accent`:

```python
    def _parse_root(self, token: Token) -> Node:
        group = self.parse_group()
        inner = group.children[0]
        arguments = inner.children if inner.kind == "sequence" else (inner,)
        if len(arguments) != 2:
            raise FormulaError(
                "root requires 2 arguments",
                position=token.start,
                expected="2 comma-separated arguments",
                found=str(len(arguments)),
                source=self.source,
            )
        return Node("root", children=tuple(arguments))
```

In `node_to_mathml`, next to the `sqrt` branch:

```python
    if node.kind == "root":
        root = mml("mroot")
        root.append(node_to_mathml(node.children[0]))
        root.append(node_to_mathml(node.children[1]))
        return root
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_core.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/core.py tests/test_core.py
git commit -m "feat(core): add the root() construct and its MathML output"
```

---

## Task 6: n-th roots in OMML, both directions

**Files:**
- Modify: `src/mathfmt/omml.py:28-40` (`MATHML_TAGS`), `omml.py:136-174` (`_convert`), new `_radical_with_degree`, `omml.py:419-424` (the `rad` branch of `_emit`)
- Test: `tests/test_omml.py`

`_convert` returns early for any tag not in `MATHML_TAGS`, so `mroot` must be added there or the element is silently dropped. `_radical` already emits `m:radPr/m:degHide` and an empty `m:deg`; the n-th root sets `degHide` to `0` and fills that `m:deg`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_omml.py`:

```python
def test_nth_root_produces_visible_degree() -> None:
    root = omath_for("root(x,3)")
    rad = root.find(f".//{{{M_NS}}}rad")
    assert rad is not None
    deg_hide = rad.find(f"{{{M_NS}}}radPr/{{{M_NS}}}degHide")
    assert deg_hide is not None
    assert deg_hide.get(qname(M_NS, "val")) == "0"
    deg = rad.find(f"{{{M_NS}}}deg")
    assert deg is not None and len(deg) > 0


def test_square_root_keeps_hidden_empty_degree() -> None:
    rad = omath_for("sqrt(x)").find(f".//{{{M_NS}}}rad")
    assert rad.find(f"{{{M_NS}}}radPr/{{{M_NS}}}degHide").get(qname(M_NS, "val")) == "1"
    assert len(rad.find(f"{{{M_NS}}}deg")) == 0


def test_nth_root_round_trips_through_omml_to_text() -> None:
    assert omml_to_text(omath_for("root(x,3)")) == "root(x,3)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_omml.py -k "root" -v --no-cov`
Expected: `test_nth_root_produces_visible_degree` FAILS on `assert rad is not None` (`mroot` is not in `MATHML_TAGS`, so nothing is emitted); `test_nth_root_round_trips_through_omml_to_text` FAILS the same way. `test_square_root_keeps_hidden_empty_degree` PASSES already.

- [ ] **Step 3: Implement both directions**

Add `"mroot"` to `MATHML_TAGS` in `src/mathfmt/omml.py`, next to `"msqrt"`.

Add the branch to `_convert`, next to the `msqrt` branch:

```python
    elif tag == "mroot":
        _radical_with_degree(elem, parent)
```

Add the writer next to `_radical`:

```python
def _radical_with_degree(elem: etree._Element, parent: etree._Element) -> None:
    children = list(elem)
    rad = etree.SubElement(parent, qname(M_NS, "rad"))
    rad_pr = etree.SubElement(rad, qname(M_NS, "radPr"))
    deg_hide = etree.SubElement(rad_pr, qname(M_NS, "degHide"))
    deg_hide.set(qname(M_NS, "val"), "0")
    deg = etree.SubElement(rad, qname(M_NS, "deg"))
    e = etree.SubElement(rad, qname(M_NS, "e"))
    _convert(children[0], e)
    _convert(children[1], deg)
```

The `m:deg` element is created before `m:e` because OMML requires that order, and the base is converted first only to keep the reading order obvious — element order is fixed by the `SubElement` calls above, not by the conversion order.

In `_emit`, replace the `rad` branch's rejection of degrees:

```python
    if tag == "rad":
        deg = _find(elem, "deg")
        if deg is not None and len(deg) > 0:
            return "root(" + _emit_children(_require(elem, "e")) + "," + _emit_children(deg) + ")"
        return "sqrt(" + _emit_children(_require(elem, "e")) + ")"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_omml.py -v --no-cov`
Expected: PASS. Any pre-existing test asserting that an n-th root raises `OmmlConversionError` must be updated to the new behaviour — search with `grep -n "nth-root" tests/test_omml.py`.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/omml.py tests/test_omml.py
git commit -m "feat(omml): support n-th root radicals in both directions"
```

---

## Task 7: Quoted upright text atom

**Files:**
- Modify: `src/mathfmt/core.py` (TOKEN_RE, `starts_atom` at `core.py:622`, `parse_atom`, `node_to_mathml`)
- Test: `tests/test_core.py`, `tests/test_omml.py`

`"` is currently unmatched by `TOKEN_RE`, so this is the same additive change as Task 1. `starts_atom` must learn the new token kind or implicit multiplication (`2"kg"`) breaks. OMML needs no work: `_convert` already maps `mtext` to a plain (upright) run.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
def test_quoted_text_becomes_mtext() -> None:
    math = formula_to_mathml('"已知"')
    mtext = math.find(f".//{{{MML_NS}}}mtext")
    assert mtext is not None
    assert mtext.text == "已知"


def test_quoted_text_participates_in_a_formula() -> None:
    assert "mtext" in local_tags('x = 3 "kg"')
```

Add to `tests/test_omml.py`:

```python
def test_quoted_text_produces_a_plain_run() -> None:
    root = omath_for('"已知"')
    texts = [t.text for t in root.iter(f"{{{M_NS}}}t")]
    assert "已知" in texts
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_core.py tests/test_omml.py -k quoted -v --no-cov`
Expected: FAIL with `FormulaError: Unrecognized formula text near: '"已知"'`.

- [ ] **Step 3: Implement the atom**

In `TOKEN_RE`, add the STRING alternative immediately before `NUMBER` so a quoted run is never split:

```python
    r"(?P<MATRIX_OPEN>\[\[)|"
    r"(?P<MATRIX_CLOSE>\]\])|"
    r"(?P<STRING>\"[^\"]*\")|"
    r"(?P<NUMBER>\d+(?:[\.,]\d+)?)|"
```

In `starts_atom`, add the kind so adjacency still multiplies:

```python
    def starts_atom(self) -> bool:
        return self.current.kind in {"NUMBER", "IDENT", "LPAREN", "MATRIX_OPEN", "STRING"}
```

In `parse_atom`, add the branch next to the `NUMBER` branch:

```python
        if token := self.accept("STRING"):
            return Node("text", token.value[1:-1])
```

In `node_to_mathml`, add the branch next to the `number` branch:

```python
    if node.kind == "text":
        return mml("mtext", node.value or "")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_core.py tests/test_omml.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/core.py tests/test_core.py tests/test_omml.py
git commit -m "feat(core): add a quoted upright text atom"
```

---

## Task 8: `latex.py` — symbol macros, detection, and rejection

**Files:**
- Create: `src/mathfmt/latex.py`
- Create: `tests/test_latex.py`
- Modify: `src/mathfmt/core.py` (`_suggest_fix`)

This task establishes the module and the no-guessing rejection path. Later tasks add the argument-taking macros on top.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_latex.py`:

```python
from __future__ import annotations

import pytest

from mathfmt.core import FormulaError
from mathfmt.latex import contains_latex_macro, expand_latex


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\alpha + \beta", "α + β"),
        (r"\Gamma \Omega", "Γ Ω"),
        (r"a \leq b", "a ≤ b"),
        (r"a \neq b", "a ≠ b"),
        (r"a \pm b", "a ± b"),
        (r"a \mp b", "a ∓ b"),
        (r"a \times b \cdot c \div d", "a × b · c ÷ d"),
        (r"x \to y", "x → y"),
        (r"x \Rightarrow y", "x ⇒ y"),
        (r"x \in A \cup B", "x ∈ A ∪ B"),
        (r"\infty", "∞"),
        (r"\nabla f", "∇ f"),
        (r"\sin x + \cos y", "sin x + cos y"),
        (r"a \, b \quad c", "a  b  c"),
    ],
)
def test_symbol_macros_expand(source: str, expected: str) -> None:
    assert expand_latex(source).split() == expected.split()


@pytest.mark.parametrize("text", [r"\frac{a}{b}", r"\alpha", r"x \, y", r"\begin{cases}"])
def test_contains_latex_macro_detects_macros(text: str) -> None:
    assert contains_latex_macro(text) is True


@pytest.mark.parametrize("text", ["x^2 + 1", "H2O", r"C:\Users\gml85", "a = b"])
def test_contains_latex_macro_ignores_non_macros(text: str) -> None:
    assert contains_latex_macro(text) is False


@pytest.mark.parametrize("source", [r"\substack{a}", r"\mathcal{L}", r"\overbrace{x}", r"\newcommand"])
def test_unsupported_macro_is_rejected_with_a_hint(source: str) -> None:
    with pytest.raises(FormulaError) as excinfo:
        expand_latex(source)
    details = excinfo.value.to_dict()
    assert details["hint"]
    assert source.split("{")[0] in str(excinfo.value)
```

`C:\Users\gml85` must not be detected: `\Users` is not a known macro. That is what keeps Windows paths out of the scanner in Task 13.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_latex.py -v --no-cov`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'mathfmt.latex'`.

- [ ] **Step 3: Create the module**

Create `src/mathfmt/latex.py`:

```python
"""Expand a documented subset of LaTeX into MathFmt's linear formula syntax.

This module is a pure text-to-text transform: it knows nothing about lxml,
MathML, or OMML.  Anything outside the documented subset raises FormulaError
rather than being guessed at, so a wrong rendering can never be produced from
an unsupported macro.
"""

from __future__ import annotations

import re

from .core import FormulaError

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

OPERATORS = {
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "pm": "±", "mp": "∓", "times": "×",
    "cdot": "·", "div": "÷", "to": "→", "rightarrow": "→", "Rightarrow": "⇒",
    "leftrightarrow": "<->", "in": "∈", "notin": "∉", "subset": "⊂",
    "subseteq": "⊆", "cup": "∪", "cap": "∩", "infty": "∞", "partial": "∂",
    "nabla": "∇",
}

FUNCTIONS = {"sin", "cos", "tan", "log", "ln", "exp", "lim", "sum", "int", "prod", "sqrt"}

SPACING = {",", ";", "!", "quad", "qquad"}

MACRO_RE = re.compile(r"\\(?:[A-Za-z]+\*?|[,;!\\])")


def contains_latex_macro(text: str) -> bool:
    """True when the text contains at least one macro this module knows."""
    return any(_macro_name(match.group()) in _KNOWN for match in MACRO_RE.finditer(text))


def expand_latex(source: str) -> str:
    """Expand the supported LaTeX subset into MathFmt linear syntax."""
    return _expand_symbols(source)


def _macro_name(macro: str) -> str:
    return macro[1:]


def _reject(name: str, source: str, position: int) -> FormulaError:
    return FormulaError(
        f"MathFmt does not support the LaTeX macro \\{name}",
        position=position,
        expected="a supported LaTeX macro",
        found=f"\\{name}",
        source=source,
    )


def _expand_symbols(source: str) -> str:
    out: list[str] = []
    index = 0
    for match in MACRO_RE.finditer(source):
        out.append(source[index : match.start()])
        name = _macro_name(match.group())
        if name in SPACING:
            out.append(" ")
        elif name in GREEK:
            out.append(GREEK[name])
        elif name in OPERATORS:
            out.append(OPERATORS[name])
        elif name in FUNCTIONS:
            out.append(name)
        else:
            raise _reject(name, source, match.start())
        index = match.end()
    out.append(source[index:])
    return "".join(out)


_KNOWN = set(GREEK) | set(OPERATORS) | set(FUNCTIONS) | SPACING
```

In `core.py`'s `_suggest_fix`, add the hint rule:

```python
    if expected == "a supported LaTeX macro":
        return (
            "This LaTeX macro is outside MathFmt's supported subset — "
            "see docs/formula-syntax.md section 10 for the full list."
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_latex.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/latex.py tests/test_latex.py src/mathfmt/core.py
git commit -m "feat(latex): expand symbol macros and reject everything else"
```

---

## Task 9: `latex.py` — argument-taking macros

**Files:**
- Modify: `src/mathfmt/latex.py`
- Test: `tests/test_latex.py`

Covers `\frac`, `\dfrac`, `\tfrac`, `\sqrt`, `\sqrt[n]`, the six accents, `\text`, `\mathrm`, and `\left`/`\right`. Braces nest, so this needs a real scanner, not a regex.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_latex.py`:

```python
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\frac{a}{b}", "(a)/(b)"),
        (r"\dfrac{a}{b}", "(a)/(b)"),
        (r"\tfrac{a}{b}", "(a)/(b)"),
        (r"\frac{\frac{a}{b}}{c}", "((a)/(b))/(c)"),
        (r"\frac{a+b}{c-d}", "(a+b)/(c-d)"),
        (r"\sqrt{x}", "sqrt(x)"),
        (r"\sqrt[3]{x}", "root(x,3)"),
        (r"\sqrt[n+1]{x}", "root(x,n+1)"),
        (r"\bar{x}", "accent(x,bar)"),
        (r"\overline{x}", "accent(x,bar)"),
        (r"\hat{y}", "accent(y,hat)"),
        (r"\vec{F}", "accent(F,vec)"),
        (r"\dot{q}", "accent(q,dot)"),
        (r"\ddot{q}", "accent(q,ddot)"),
        (r"\text{已知}", '"已知"'),
        (r"\mathrm{d}", '"d"'),
        (r"\left( a \right)", "( a )"),
        (r"\frac{\bar{x}}{\sqrt{n}}", "(accent(x,bar))/(sqrt(n))"),
    ],
)
def test_argument_macros_expand(source: str, expected: str) -> None:
    assert expand_latex(source).replace(" ", "") == expected.replace(" ", "")


def test_sqrt_with_degree_never_becomes_a_two_argument_sqrt() -> None:
    # sqrt(x,3) would silently render "x, 3" inside the radical.
    assert "sqrt(x,3)" not in expand_latex(r"\sqrt[3]{x}")


@pytest.mark.parametrize("source", [r"\frac{a}", r"\frac{a}{b", r"\bar{}"])
def test_malformed_arguments_are_rejected(source: str) -> None:
    with pytest.raises(FormulaError):
        expand_latex(source)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_latex.py -k "argument_macros or never_becomes or malformed" -v --no-cov`
Expected: FAIL — `\frac` is not in any table, so `_expand_symbols` raises "does not support the LaTeX macro \frac".

- [ ] **Step 3: Implement the argument scanner**

Add to `src/mathfmt/latex.py`:

```python
ACCENT_MACROS = {
    "bar": "bar", "overline": "bar", "hat": "hat",
    "vec": "vec", "dot": "dot", "ddot": "ddot",
}

FRACTION_MACROS = {"frac", "dfrac", "tfrac"}

TEXT_MACROS = {"text", "mathrm"}


def _read_group(source: str, index: int, opener: str, closer: str) -> tuple[str, int]:
    """Read a balanced ``opener``…``closer`` group starting at ``index``."""
    while index < len(source) and source[index].isspace():
        index += 1
    if index >= len(source) or source[index] != opener:
        raise FormulaError(
            f"Expected {opener} after a LaTeX macro",
            position=index,
            expected="a supported LaTeX macro",
            found=source[index : index + 1] or "end of formula",
            source=source,
        )
    depth = 0
    for position in range(index, len(source)):
        if source[position] == opener:
            depth += 1
        elif source[position] == closer:
            depth -= 1
            if depth == 0:
                content = source[index + 1 : position]
                if not content.strip():
                    raise FormulaError(
                        "A LaTeX macro argument is empty",
                        position=index,
                        expected="a supported LaTeX macro",
                        found=opener + closer,
                        source=source,
                    )
                return content, position + 1
    raise FormulaError(
        f"Unbalanced {opener} in LaTeX input",
        position=index,
        expected=closer,
        found="end of formula",
        source=source,
    )


def _expand_arguments(source: str) -> str:
    out: list[str] = []
    index = 0
    while True:
        match = MACRO_RE.search(source, index)
        if match is None:
            out.append(source[index:])
            return "".join(out)
        out.append(source[index : match.start()])
        name = _macro_name(match.group())
        cursor = match.end()
        if name in FRACTION_MACROS:
            numerator, cursor = _read_group(source, cursor, "{", "}")
            denominator, cursor = _read_group(source, cursor, "{", "}")
            out.append(f"({_expand_arguments(numerator)})/({_expand_arguments(denominator)})")
        elif name == "sqrt":
            degree = None
            probe = cursor
            while probe < len(source) and source[probe].isspace():
                probe += 1
            if probe < len(source) and source[probe] == "[":
                degree, cursor = _read_group(source, probe, "[", "]")
            radicand, cursor = _read_group(source, cursor, "{", "}")
            if degree is None:
                out.append(f"sqrt({_expand_arguments(radicand)})")
            else:
                out.append(f"root({_expand_arguments(radicand)},{_expand_arguments(degree)})")
        elif name in ACCENT_MACROS:
            base, cursor = _read_group(source, cursor, "{", "}")
            out.append(f"accent({_expand_arguments(base)},{ACCENT_MACROS[name]})")
        elif name in TEXT_MACROS:
            content, cursor = _read_group(source, cursor, "{", "}")
            if '"' in content:
                raise FormulaError(
                    "LaTeX text may not contain a double quote",
                    position=match.start(),
                    expected="a supported LaTeX macro",
                    found='"',
                    source=source,
                )
            out.append(f'"{content}"')
        elif name in {"left", "right"}:
            pass  # the delimiter that follows is kept verbatim
        else:
            out.append(match.group())
        index = cursor
```

Change `expand_latex` to run this pass before symbol substitution:

```python
def expand_latex(source: str) -> str:
    """Expand the supported LaTeX subset into MathFmt linear syntax."""
    return _expand_symbols(_expand_arguments(source))
```

Add the new names to the known set so `contains_latex_macro` sees them:

```python
_KNOWN = (
    set(GREEK)
    | set(OPERATORS)
    | set(FUNCTIONS)
    | SPACING
    | set(ACCENT_MACROS)
    | FRACTION_MACROS
    | TEXT_MACROS
    | {"left", "right"}
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_latex.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/latex.py tests/test_latex.py
git commit -m "feat(latex): expand fractions, radicals, accents, and text macros"
```

---

## Task 10: `latex.py` — limits on large operators

**Files:**
- Modify: `src/mathfmt/latex.py`
- Test: `tests/test_latex.py`

`\sum_{i=1}^{n}` becomes `sum(i=1,n)`, matching `parse_atom`'s n-ary form (`core.py:792`). `\lim_{x \to 0}` becomes `lim(x->0)`, which `preprocess_formula` already documents.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_latex.py`:

```python
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\sum_{i=1}^{n} i", "sum(i=1,n) i"),
        (r"\int_{a}^{b} f", "int(a,b) f"),
        (r"\prod_{k=1}^{m} k", "prod(k=1,m) k"),
        (r"\lim_{x \to 0} f", "lim(x→0) f"),
        (r"x_{i}^{2}", "x_(i)^(2)"),
        (r"x^{n+1}", "x^(n+1)"),
    ],
)
def test_limits_and_scripts_expand(source: str, expected: str) -> None:
    assert expand_latex(source).replace(" ", "") == expected.replace(" ", "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_latex.py -k limits_and_scripts -v --no-cov`
Expected: FAIL — the braces survive untouched, so the result is `sum_{i=1}^{n} i`, not `sum(i=1,n) i`.

- [ ] **Step 3: Implement the pass**

Add to `src/mathfmt/latex.py`:

```python
NARY = {"sum", "int", "prod"}


def _expand_scripts(source: str) -> str:
    """Turn ``_{...}``/``^{...}`` into MathFmt's parenthesised script form, and
    bind a large operator's two limits into its ``name(lower,upper)`` call."""
    out: list[str] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char in "_^" and index + 1 < len(source) and source[index + 1] == "{":
            content, index = _read_group(source, index + 1, "{", "}")
            out.append(f"{char}({_expand_scripts(content)})")
            continue
        out.append(char)
        index += 1
    return "".join(out)


NARY_RE = re.compile(r"\b(sum|int|prod)\s*_\(([^()]*)\)\s*\^\(([^()]*)\)")
LIMIT_RE = re.compile(r"\blim\s*_\(([^()]*)\)")


def _bind_limits(source: str) -> str:
    source = NARY_RE.sub(lambda m: f"{m.group(1)}({m.group(2)},{m.group(3)})", source)
    return LIMIT_RE.sub(lambda m: f"lim({m.group(1)})", source)
```

Chain both passes in `expand_latex`, after argument expansion and before symbol substitution — `_bind_limits` must run on the already-parenthesised script form:

```python
def expand_latex(source: str) -> str:
    """Expand the supported LaTeX subset into MathFmt linear syntax."""
    expanded = _expand_arguments(source)
    expanded = _expand_scripts(expanded)
    return _expand_symbols(_bind_limits(expanded))
```

`_expand_symbols` runs last so `\to` inside `\lim_{x \to 0}` is still a macro when `_bind_limits` copies it into the call.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_latex.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/latex.py tests/test_latex.py
git commit -m "feat(latex): bind sub/superscripts and large-operator limits"
```

---

## Task 11: `latex.py` — environments

**Files:**
- Modify: `src/mathfmt/latex.py`
- Test: `tests/test_latex.py`

Matrices become `[[a,b],[c,d]]`, `cases` becomes the compact brace form, and `aligned` keeps `\\` for `split_multiline_formula` (`core.py:1368`). Environments are expanded first, before any other pass, because `&` and `\\` only carry meaning inside them.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_latex.py`:

```python
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\begin{matrix} a & b \\ c & d \end{matrix}", "[[a,b],[c,d]]"),
        (r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", "[[a,b],[c,d]]"),
        (r"\begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix}", "[[1,0],[0,1]]"),
        (r"\begin{cases} 0 & x<0 \\ 1 & x \geq 0 \end{cases}", "{0, x<0; 1, x≥0}"),
        (r"\begin{aligned} a=b \\ c=d \end{aligned}", r"a=b \\ c=d"),
        (r"\begin{align} a=b \\ c=d \end{align}", r"a=b \\ c=d"),
    ],
)
def test_environments_expand(source: str, expected: str) -> None:
    assert expand_latex(source).replace(" ", "") == expected.replace(" ", "")


@pytest.mark.parametrize(
    "source",
    [
        r"\begin{smallmatrix} a \end{smallmatrix}",
        r"\begin{matrix} a & b \end{pmatrix}",
        r"a \\ b",
    ],
)
def test_unsupported_environments_and_stray_row_breaks_are_rejected(source: str) -> None:
    with pytest.raises(FormulaError):
        expand_latex(source)
```

The last case matters: `\\` outside an environment has no meaning in LaTeX input and must not silently reach `split_multiline_formula`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_latex.py -k "environments or stray_row" -v --no-cov`
Expected: FAIL — `\begin` is not a known macro, so every case raises the generic unsupported-macro error, including the ones that should succeed.

- [ ] **Step 3: Implement the pass**

Add to `src/mathfmt/latex.py`:

```python
MATRIX_ENVIRONMENTS = {"matrix", "pmatrix", "bmatrix"}
ALIGN_ENVIRONMENTS = {"aligned", "align", "align*"}

ENVIRONMENT_RE = re.compile(
    r"\\begin\{(?P<name>[A-Za-z]+\*?)\}(?P<body>.*?)\\end\{(?P=name)\}",
    re.DOTALL,
)


def _rows(body: str) -> list[list[str]]:
    return [[cell.strip() for cell in row.split("&")] for row in re.split(r"\\\\", body) if row.strip()]


def _expand_environments(source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        rows = _rows(match.group("body"))
        if name in MATRIX_ENVIRONMENTS:
            return "[[" + "],[".join(",".join(row) for row in rows) + "]]"
        if name == "cases":
            branches = []
            for row in rows:
                if len(row) != 2:
                    raise FormulaError(
                        "Each cases branch needs a value and a condition separated by &",
                        expected="a supported LaTeX macro",
                        found=" & ".join(row),
                        source=source,
                    )
                branches.append(f"{row[0]}, {row[1]}")
            return "{" + "; ".join(branches) + "}"
        if name in ALIGN_ENVIRONMENTS:
            return r" \\ ".join(" ".join(row) for row in rows)
        raise FormulaError(
            f"MathFmt does not support the LaTeX environment {name}",
            expected="a supported LaTeX macro",
            found=name,
            source=source,
        )

    expanded = ENVIRONMENT_RE.sub(replace, source)
    if r"\begin" in expanded or r"\end" in expanded:
        raise FormulaError(
            "Unbalanced LaTeX environment",
            expected="a supported LaTeX macro",
            found=r"\begin",
            source=source,
        )
    return expanded
```

Run it first in `expand_latex`, and reject any `\\` that survives it:

```python
def expand_latex(source: str) -> str:
    """Expand the supported LaTeX subset into MathFmt linear syntax."""
    expanded = _expand_environments(source)
    rows = re.split(r"\\\\", expanded)
    converted = []
    for row in rows:
        row = _expand_arguments(row)
        row = _expand_scripts(row)
        converted.append(_expand_symbols(_bind_limits(row)))
    return r" \\ ".join(converted)
```

Splitting on `\\` before the remaining passes keeps the row separator intact for `split_multiline_formula` while letting every other pass work on separator-free text. A `\\` that was never inside an environment therefore reaches `split_multiline_formula` as a two-row formula — so `MACRO_RE` must stop matching it. Change the pattern so a doubled backslash is not a macro:

```python
MACRO_RE = re.compile(r"\\(?:[A-Za-z]+\*?|[,;!])")
```

and reject stray separators explicitly at the top of `expand_latex`:

```python
    if r"\\" in source and not ENVIRONMENT_RE.search(source):
        raise FormulaError(
            r"\\ is only a row separator inside an aligned, matrix, or cases environment",
            expected="a supported LaTeX macro",
            found=r"\\",
            source=source,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_latex.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/latex.py tests/test_latex.py
git commit -m "feat(latex): expand matrix, cases, and aligned environments"
```

---

## Task 12: Wire the expander into `formula_to_mathml`

**Files:**
- Modify: `src/mathfmt/core.py:1353-1366`
- Test: `tests/test_core.py`

One branch, guarded by `contains_latex_macro`, so no non-LaTeX input changes its execution path. The import is local to the function because `latex` imports `FormulaError` from `core`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\frac{a}{b}", "mfrac"),
        (r"\sqrt[3]{x}", "mroot"),
        (r"\bar{x}", "mover"),
        (r"\alpha + \beta", "mi"),
        (r"\sum_{i=1}^{n} i", "mrow"),
        (r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", "mtable"),
    ],
)
def test_latex_input_reaches_mathml(source: str, expected: str) -> None:
    assert expected in local_tags(source)


def test_unsupported_latex_macro_raises_formula_error() -> None:
    with pytest.raises(FormulaError):
        formula_to_mathml(r"\substack{a}")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_core.py -k latex -v --no-cov`
Expected: FAIL with `FormulaError: Unrecognized formula text near: '\\frac{a}{b}'` — the backslash never reaches the expander.

- [ ] **Step 3: Wire it up**

In `formula_to_mathml`:

```python
def formula_to_mathml(
    source: str,
    aliases: Mapping[str, str] | None = None,
) -> etree._Element:
    from .latex import contains_latex_macro, expand_latex

    if contains_latex_macro(source):
        source = expand_latex(source)
    if not (aliases and source.strip() in aliases):
        chemistry = _try_chemistry_mathml(source)
        if chemistry is not None:
            return chemistry[0]
    normalized, derivatives = preprocess_formula(source)
    ast = Parser(tokenize(normalized), derivatives, normalized, aliases).parse()
    root = mml("math", display="inline", nsmap={None: MML_NS})
    root.append(node_to_mathml(ast))
    return root
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -m "not native_xsl"`
Expected: PASS, coverage at or above the 85% threshold. A `WinError 5` during setup means a stale temp directory, not a defect — rerun with `pytest -m "not native_xsl" --basetemp=.pytest_tmp_latex_1`.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/core.py tests/test_core.py
git commit -m "feat(core): parse LaTeX input through the macro expander"
```

---

## Task 13: Scanner — LaTeX delimiters and bare macros

**Files:**
- Modify: `src/mathfmt/core.py:1460-1500` (`_latex_delimited_spans`), `core.py:1579-1610` (`candidate_spans`), new `_latex_macro_spans`
- Test: `tests/test_core.py`

`\(...\)` and `\[...\]` join the existing `$`/`$$` detector at high confidence. Bare macro spans get their own detector at medium confidence, guarded by a real parse, so they land in the review list without being auto-converted. `MATH_CHARS` is deliberately untouched.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
def test_latex_inline_delimiters_are_high_confidence() -> None:
    spans = candidate_spans(r"由此可得 \(x^2 + 1\) 成立")
    assert len(spans) == 1
    assert spans[0].explicit is True


def test_latex_display_delimiters_are_detected() -> None:
    spans = candidate_spans(r"\[ y = 2x \]")
    assert len(spans) == 1
    assert spans[0].explicit is True


def test_bare_macro_span_is_detected() -> None:
    spans = candidate_spans(r"其中 \frac{a}{b} 是比值")
    assert len(spans) == 1
    assert spans[0].explicit is False
    assert r"\frac{a}{b}" in spans[0].source


def test_windows_path_is_not_a_candidate() -> None:
    assert candidate_spans(r"文件位于 C:\Users\gml85 目录") == []


def test_unparseable_macro_span_is_not_a_candidate() -> None:
    assert candidate_spans(r"见 \substack{a} 一节") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_core.py -k "latex_inline or latex_display or bare_macro or windows_path or unparseable_macro" -v --no-cov`
Expected: the first three FAIL (no detector produces these spans); the last two PASS already and must keep passing.

- [ ] **Step 3: Implement both detectors**

`CandidateSpan` is `FormulaCandidate` (`plugins.py:20`), whose positional fields are `(start, end, source, linear, display, explicit)`. The delimiter stripping therefore happens right here — the fourth argument is the parser-ready text — and there is no separate stripping step elsewhere.

In `_latex_delimited_spans` (`core.py:1463`), add both branches at the top of the `while` loop, before the existing `$$` branch:

```python
        if text.startswith("\\[", index):
            end = text.find("\\]", index + 2)
            if end == -1:
                index += 2
                continue
            span_end = end + 2
            inner = text[index + 2 : end].strip()
            if inner:
                spans.append(CandidateSpan(index, span_end, text[index:span_end], inner, True, True))
                claimed.append((index, span_end))
            index = span_end
            continue

        if text.startswith("\\(", index):
            end = text.find("\\)", index + 2)
            if end == -1:
                index += 2
                continue
            span_end = end + 2
            inner = text[index + 2 : end].strip()
            if inner:
                spans.append(CandidateSpan(index, span_end, text[index:span_end], inner, False, True))
                claimed.append((index, span_end))
            index = span_end
            continue
```

`\[` is display (fifth argument `True`), `\(` is inline (`False`); both are explicit (sixth argument `True`), which is what makes them high confidence.

Add the bare-macro detector next to `_physics_spans` (`core.py:1546`):

```python
LATEX_MACRO_SPAN_RE = re.compile(r"\\[A-Za-z]+\*?(?:\s*[\[{][^\]}]*[\]}])*(?:\s*\S+)?")


def _latex_macro_spans(text: str, claimed: Sequence[tuple[int, int]]) -> list[CandidateSpan]:
    """Find undelimited LaTeX spans, at medium confidence, never auto-selected."""
    from .latex import contains_latex_macro

    spans: list[CandidateSpan] = []
    occupied = list(claimed)
    for match in LATEX_MACRO_SPAN_RE.finditer(text):
        start, end = match.span()
        if _range_overlaps(start, end, occupied):
            continue
        source = match.group().strip(TRIM_PUNCT)
        if not contains_latex_macro(source):
            continue
        try:
            formula_to_mathml(source)
        except FormulaError:
            continue
        spans.append(CandidateSpan(start, start + len(source), source))
        occupied.append((start, end))
    return spans
```

Call it in `candidate_spans`, after the chemistry spans and before the generic walk:

```python
    macro_spans = _latex_macro_spans(text, claimed_ranges)
    candidates.extend(macro_spans)
    claimed_ranges.extend((span.start, span.end) for span in macro_spans)
```

Now assign the confidence. `span.confidence` is only honoured for plugin recognizers (`core.py:1756`), so a built-in detector needs its own branch in the confidence chain. Add it immediately after the `elif span.explicit:` branch (`core.py:1760`):

```python
                elif "\\" in source:
                    confidence = "medium"
                    reason = "LaTeX macro without delimiters; review required"
```

Testing for a backslash is sufficient and needs no import: `MATH_CHARS` excludes `\`, so no other built-in detector can produce a span containing one, and delimited spans were already handled by the `span.explicit` branch above.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_core.py tests/test_docx.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mathfmt/core.py tests/test_core.py
git commit -m "feat(core): detect LaTeX delimiters and bare macro spans"
```

---

## Task 14: End-to-end acceptance document

**Files:**
- Modify: `tests/acceptance/gen_docs.py`
- Test: `tests/test_acceptance.py`

Proves the whole path — a real DOCX containing LaTeX, scanned, applied, and validated.

- [ ] **Step 1: Write the failing test**

`tests/test_acceptance.py` builds every document once per session in the `acceptance_docs` fixture (`test_acceptance.py:20`) by patching `gen_docs.OUT` and calling each zero-argument factory, then runs `_scan_convert_validate` over them. Extend that fixture's list:

```python
    for name, builder in [
        ("doc01", gen_docs.doc01_basic),
        ("doc02", gen_docs.doc02_advanced),
        ("doc03", gen_docs.doc03_mixed),
        ("doc04", gen_docs.doc04_edge_cases),
        ("doc05", gen_docs.doc05_textbook),
        ("doc06", gen_docs.doc06_v040),
        ("doc07", gen_docs.doc07_latex),
    ]:
```

Add `"doc07"` to the parametrize list of `test_acceptance_scan_convert_validate` (`test_acceptance.py:70`), and add this test after it:

```python
def test_acceptance_latex_formulas_parse(acceptance_docs: dict[str, Path], tmp_path: Path) -> None:
    """Every LaTeX span in doc07 must be detected and parse, and the Windows path must not."""
    scan_report = tmp_path / "doc07_latex_scan.json"
    result = scan_docx(acceptance_docs["doc07"], scan_report)
    by_source = {str(c.get("source", "")): c for c in result.get("candidates", [])}

    for target in [
        r"\(\frac{a}{b}\)",
        r"\[ V = \sqrt[3]{x} \]",
        r"\bar{x}",
        r"\sum_{i=1}^{n} i",
    ]:
        assert target in by_source, f"{target!r} was not detected"
        assert by_source[target]["parse_status"] == "ok"

    assert by_source[r"\(\frac{a}{b}\)"]["confidence"] == "high"
    assert by_source[r"\bar{x}"]["confidence"] == "medium"
    assert not any("Users" in source for source in by_source), "a Windows path became a candidate"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_acceptance.py -k "doc07 or latex_formulas" -v --no-cov`
Expected: FAIL with `AttributeError: module 'tests.acceptance.gen_docs' has no attribute 'doc07_latex'`.

- [ ] **Step 3: Add the document factory**

`gen_docs.py` factories take no arguments and write into the module-level `OUT` via the shared `_write(name, paragraphs)` helper (`gen_docs.py:43`). Add this after `doc06_v040`:

```python
def doc07_latex() -> Path:
    """v1.3 notation: LaTeX delimiters, bare macros, accents, and environments."""
    return _write(
        "doc07_latex.docx",
        [
            "MathFmt v1.3 LaTeX Acceptance",
            "",
            r"由此可得 \(\frac{a}{b}\) 成立。",
            r"体积公式为 \[ V = \sqrt[3]{x} \]",
            r"样本均值记为 \bar{x}。",
            r"求和式 \sum_{i=1}^{n} i 收敛。",
            r"$\begin{cases} 0 & x<0 \\ 1 & x \geq 0 \end{cases}$",
            r"文件位于 C:\Users\gml85 目录，不应被识别。",
        ],
    )
```

The `cases` paragraph is wrapped in `$…$` because its `\\` row separator would otherwise be rejected outside an environment only after the environment pass — wrapping keeps it a single explicit span and exercises the delimiter path as well.

Register it in `all_docs()`:

```python
        doc06_v040(),
        doc07_latex(),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_acceptance.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/gen_docs.py tests/test_acceptance.py
git commit -m "test: add a LaTeX acceptance document"
```

---

## Task 15: Documentation and release notes

**Files:**
- Modify: `docs/formula-syntax.md`, `docs/workflow.md`, `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `src/mathfmt/_version.py`

- [ ] **Step 1: Update the syntax reference**

In `docs/formula-syntax.md`:

- Section 2 (Tokenizer): add `∇` to the IDENT character list, `∓` to OP, and the new `STRING : "…"` token. Do not list `∂` — see the Task 1 revision note.
- Section 3 (Grammar): add `accent`, `root`, and the quoted text atom to the `atom` production.
- Section 4 (MathML Output Mapping): add three rows — `accent` → `m:mover accent="true"`, `root` → `m:mroot`, `text` → `m:mtext`.
- New section 10, "LaTeX input subset": the complete supported table from spec §2.3, and an explicit unsupported list — `\substack`, `\overbrace`, `\underbrace`, `\mathcal`, `\mathbb`, `\operatorname`, `\binom`, `\newcommand`, and any environment other than `matrix`/`pmatrix`/`bmatrix`/`cases`/`aligned`/`align`.

Document these three limitations in the same section:

1. A parse error's column number refers to the expanded text, not the original LaTeX; the macro name in the error's `hint` is the reliable locator.
2. Bare Unicode symbols (`∇f = 0` with no macro and no delimiter) are parsed but not discovered by the scanner — wrap them in `$…$`, the same rule the alias section already states.
2b. A standalone `\partial` / `∂` is not supported, and higher-order or mixed partials (`∂^2u/∂x^2`, `∂^2f/∂x∂y`) still report a parse error for manual review rather than converting. Only the `∂f/∂x` shape converts. State this plainly — it is a deliberate safety choice, not an oversight.
3. A quoted text atom reverses through `omml_to_text` as its bare content, without the quotes, matching how chemistry formulas reverse.

- [ ] **Step 2: Update the remaining docs**

- `docs/workflow.md`: a short subsection on scanning a LaTeX document — delimited spans are high confidence, bare macros are medium and need review.
- `README.md`: one bilingual line in the feature list.
- `CHANGELOG.md`: a `## [1.3.0]` section listing the LaTeX subset, the three new constructs, the scanner detectors, and the tokenizer additions.
  - **Required, under a `### Changed` heading (not `Added`):** `accent` is now a reserved alias token, so an existing alias profile that defines `accent` will be rejected at load. Task 2's spec review flagged this: `docs/api.md` says changing *accepted input* requires a major version, and `RESERVED_ALIAS_TOKENS` had never been extended since it was created in v0.4.0 — this is the first time. It ships in a minor release because the alternative is worse (the alias branch at `core.py:824` runs before the construct dispatch, so an unreserved `accent` alias would silently shadow a documented construct instead of failing loudly at load), but it must not ship silently.
  - Also add `accent` — and `root` and the quoted text atom once Tasks 5 and 7 land — to the reserved-name examples in `docs/formula-syntax.md`'s alias section (around line 230).
- `ROADMAP.md`: a v1.3 entry that states plainly that this revises the stable-maintenance policy's "no supported-syntax changes" clause, and why.
- `src/mathfmt/_version.py`: bump to `1.3.0`.

- [ ] **Step 3: Update the self-update tests**

Run: `grep -rn "1\.2\.0" tests/test_update.py`
Any fixture that fakes a "newer release" must be greater than 1.3.0, or update detection will correctly report no update and the test will fail.

- [ ] **Step 4: Run the full suite and lint**

Run: `pytest -m "not native_xsl"`
Expected: PASS with coverage at or above 85%.

Run: `ruff check .` and `ruff format --check .`
Expected: clean. If ruff fails with `OSError: [WinError 4551]`, a Windows Application Control policy is blocking the executable — this is not a code defect. Report that ruff could not run so the maintainer can run it themselves before tagging.

- [ ] **Step 5: Commit**

```bash
git add docs README.md CHANGELOG.md ROADMAP.md src/mathfmt/_version.py tests/test_update.py
git commit -m "docs: document the LaTeX input subset for v1.3"
```

---

## Carried cleanups (from Task 4's code review — fold into any later task touching these files)

Approved without must-fixes; none of these block. In the reviewer's priority order:

1. **`tests/test_omml.py`** — `test_accent_round_trips_through_omml_to_text` duplicates `test_every_accent_kind_survives_the_full_round_trip` exactly (same five kinds, only the base letters differ). Delete the former and parametrize the survivor over the table — `@pytest.mark.parametrize("kind", list(ACCENT_CHARS))` — to keep the auto-extending property while regaining per-case failure names.
2. **`accents.py`** — move `_DEFAULT_ACCENT_CHAR` there as `DEFAULT_OMML_ACCENT = OMML_ACCENT_CHARS[ACCENT_CHARS["hat"]]`, under the comment that already states the spec fact, and import it into `omml.py`. The derivation currently sits in `omml.py`, where the two-step `name → spacing → combining` chain crosses key spaces the module names ambiguously, and states the spec fact a second time. A rename of the `hat` row would also fail at import time — acceptable three lines from the table, worse in `omml.py`.
3. **`omml.py`** — give the "present `m:chr` with no `m:val`" case its own branch and message. It currently reaches the unrecognised-value raise only because `char` becomes `None` and misses the dict, producing `accent character None`, which no document author can act on, and forcing the test to match that literal string. A distinct message (`m:chr has no m:val`) would let the five-line explanatory comment shrink to one sentence.
4. **`tests/test_omml.py`** — the round-trip test's comment says "Iterating ACCENTS directly" while the code iterates `ACCENT_CHARS` imported from `mathfmt.core`; the file already imports `ACCENTS` from `mathfmt.accents`. Read the table from `accents`, and trim the twelve-line comment to the residual risk it actually covers.
5. **`omml.py:335-337`** — `omml_to_text`'s docstring gained a garbled clause ("including a base of its own accent for a nested…"; meaning "an accent whose base is itself an accent") and a 100-char line in a paragraph otherwise wrapped at 70-83. This is public-API documentation.
6. **Unpinned behaviour worth a test:** a third-party bare `<m:acc><m:e>x</m:e></m:acc>` reverses to `accent(x,hat)` and re-emits with an explicit `m:chr` U+0302 — a spec-correct normalization on a second pass through MathFmt. Nothing asserts the second pass.

## Self-review

**Spec coverage:**

| Spec section | Tasks |
|---|---|
| §2.1 architecture, additive tokenizer changes | 1, 7, 12 |
| §2.2 `expand_latex` / `contains_latex_macro` | 8 |
| §2.3 structure macros | 9, 10 |
| §2.3 symbol macros | 8 |
| §2.3 tokenizer additions (`∂` `∇` `∓`) | 1 |
| §2.3 environments | 11 |
| §2.4 expansion order | 9, 10, 11 (composed in `expand_latex`) |
| §3.1 accent | 2, 3, 4 |
| §3.2 upright text (as a quoted atom — see the deviation note) | 7, 9 |
| §3.3 n-th root | 5, 6, 9 |
| §4 scanner | 13 |
| §6 error handling and hints | 2, 8 |
| §7 tests | every task, plus 14 |
| §8 documentation | 15 |
| §5 GUI preview | **out of scope — separate plan** |

**Naming consistency:** `expand_latex` and `contains_latex_macro` are used with those names in Tasks 8–13. `_read_group(source, index, opener, closer)` is defined in Task 9 and reused by `_expand_scripts` in Task 10. AST node kinds are `accent`, `root`, and `text` throughout Tasks 2, 5, 7, and their MathML/OMML counterparts. Accent naming, after Task 3's follow-up unified the tables: `src/mathfmt/accents.py` holds `ACCENTS`, a tuple of `(kind name, MathML spacing character, Word combining mark)` rows, and derives all three mappings from it — `ACCENT_CHARS` (name → spacing, imported by `core`), `OMML_ACCENT_CHARS` (spacing → combining, imported by `omml`), and `ACCENT_NAMES` (combining → name, for Task 4's reverse conversion). `ACCENT_MACROS` (latex, Task 9) maps LaTeX macro name → accent name. Never write a fourth literal table; derive from `ACCENTS`.

**Placeholder scan:** The first draft of Tasks 13 and 14 told the engineer to `grep` for the delimiter-stripping code and to copy `doc06`'s structure. Both were placeholders under this skill's rules and have been replaced with the actual code, after checking three things in the source:

1. `CandidateSpan` is `FormulaCandidate` with positional fields `(start, end, source, linear, display, explicit)` — delimiter stripping is inline in `_latex_delimited_spans`, not a separate step.
2. `span.confidence` is honoured only when `span.recognizer is not None` (`core.py:1756`), so a built-in detector needs its own branch in the confidence chain.
3. `gen_docs.py` factories take no arguments and write through `_write(name, paragraphs)` into a module-level `OUT` that `test_acceptance.py`'s session fixture patches.

**One remaining judgement call for the implementer:** Task 11 splits on `\\` inside `expand_latex` and rejoins with `r" \\ "`. If a future macro ever needs to see across a row boundary, that split has to move. Nothing in this subset does.
