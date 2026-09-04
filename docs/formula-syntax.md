# Formula Syntax

What MathFmt accepts as plain-text input, how it transforms it, and what MathML it produces.

---

## 1. Preprocessing

Before the tokenizer runs, `preprocess_formula` applies these transformations in order:

### Derivative normalization

| Input pattern | Normalized form | MathML output |
|---|---|---|
| `ds(t)/dt` | `DERV0` (1st-order Leibniz) | Stacked fraction d s(t) / d t |
| `d²s(t)/dt²` or `d^2s(t)/dt^2` | `DERV0` (2nd-order Leibniz) | d² s(t) / d t² |
| `s'(t)` or `s˙(t)` | `DERV0` (1st-order Newton) | ds(t)/dt fraction |
| `s''(t)` or `s¨(t)` | `DERV0` (2nd-order Newton) | d²s(t)/dt² fraction |

All derivatives render as **stacked Leibniz fractions**. The prime/Newton and dot notations are accepted as input shorthands but always produce fraction output.

### Superscript characters

Adjacent Unicode superscript chars become `^` notation:

| Input | Normalized |
|---|---|
| `x²` | `x^2` |
| `e⁺ˣ` | `e^(+x)` |
| `x⁻¹` | `x^(-1)` |

### Subscript characters

Unicode subscript chars become plain ASCII:

| Input | Normalized |
|---|---|
| `p₁` | `p1` |
| `e₀` | `e0` |
| `p₁,₂` | `pPAIR` (special — renders as p₁,₂) |

### Operator aliases

| Input | Normalized | Renders as |
|---|---|---|
| `!=` | `≠` | ≠ |
| `<=` | `≤` | ≤ |
| `>=` | `≥` | ≥ |
| `->` | `→` | → |
| `=>` | `⇒` | ⇒ |
| `+/-` | `±` | ± |
| `√(...)` | `sqrt(...)` | √(...) |
| `×` | `*` | · (invisible multiply) |
| `·` | `*` | · (invisible multiply) |
| `÷` | `/` | fraction bar |

### Function and constant normalization

| Input | Normalized | Renders as |
|---|---|---|
| `1(t)` or `Γ(t)` | `u(t)` | u(t) |
| `Delta` | `Δ` | Δ |
| `inf` | `∞` | ∞ |
| `pi` | `π` | π |
| `lim_{p→0}` | `lim(p->0)` | lim under p→0 |

### Exponent brace unwrapping

| Input | Normalized |
|---|---|
| `e^{p1t}` | `e^(p1t)` |

---

## 2. Tokenizer

The tokenizer uses this regex (simplified):

```
NUMBER  : \d+(?:\.\d+)?
IDENT   : sqrt | lim | exp | sin | cos | tan | Delta | pi | inf
        | e[pv] | pPAIR | DERV\d+
        | [A-Za-z](?:\d+)? | [ΔπΓ∞]
OP      : <= | >= | != | ~= | -> | => | +/- | [+−*/^=<>±≠≤≥≈→⇒·×÷]
LPAREN  : ( [ {
RPAREN  : ) ] }
COMMA   : ,
IF      : if
SEMI    : ;
```

Whitespace between tokens is ignored.

A comma is always a separator — for sequences, function arguments, and
matrix/vector entries — never a decimal point. Decimals use `.` only:
`3.14` is one number, but `3,14` is the two-element sequence `3, 14`.
This also means a matrix or vector literal must not put a decimal
comma next to its entry separator: write `[1, 2, 3]`, not a form that
would make a comma do double duty.

### Token examples

| Input | Tokens |
|---|---|
| `x^2 = 4` | IDENT(x) OP(^) NUMBER(2) OP(=) NUMBER(4) |
| `sin(x)` | IDENT(sin) LPAREN(() IDENT(x) RPAREN()) |
| `p1 = ep` | IDENT(p1) OP(=) IDENT(ep) |
| `a, b, c` | IDENT(a) COMMA IDENT(b) COMMA IDENT(c) |
| `3.14` | NUMBER(3.14) |
| `3,14` | NUMBER(3) COMMA NUMBER(14) |

---

## 3. Grammar (BNF)

```
sequence   → relation ("," relation)*
relation   → add (OP_relation add)*
add        → mul (OP_add mul)*
mul        → power (OP_mul power | power)*     // implicit multiply via adjacency
power      → unary ("^" power)?
unary      → OP_unary unary | atom
atom       → NUMBER | IDENT | group | function | sqrt | limit | derivative
group      → "(" sequence ")" | "[" sequence "]" | "{" sequence "}"
function   → IDENT "(" sequence ")"
sqrt       → "sqrt" "(" sequence ")"
limit      → "lim" "(" sequence ")"
derivative → DERV{N}                            // injected by preprocessor
```

### Operator sets

| Level | Operators |
|---|---|
| `OP_relation` | `=` `<` `>` `≤` `≥` `≠` `~=` `→` `⇒` `⇌` |
| `OP_add` | `+` `-` `±` |
| `OP_mul` | `*` `·` `×` `/` `÷` |
| `OP_unary` | `+` `-` |

### Precedence (lowest to highest)

1. `,` (sequence separator)
2. `=` `<` `>` `≤` `≥` `≠` `~=` `→` `⇒` `⇌` (relations)
3. `+` `-` `±` (addition)
4. `*` `/` implicit (multiplication — implicit multiply binds tighter than explicit)
5. `^` (power — right-associative)
6. Unary `+` `-`

### Grouping

Brackets must match: `(...)`, `[...]`, `{...}`. Brackets inside a fraction's numerator/denominator are stripped from the MathML output (e.g. `(a+b)/(c-d)` renders without the literal parentheses).

### Piecewise and cases notation

Two equivalent forms are supported:

| Form | Example |
|---|---|
| Compact brace syntax | `f(x) = {0, x<0; 1, x>=0}` |
| Explicit cases syntax | `cases(0 if x<0; 1 if x>=0)` |

Each branch requires exactly one expression and one condition. Semicolons separate
branches. The result is a left brace with a two-column table: expressions on the
left and `if` conditions on the right. Errors identify the failing branch and whether
`if`, a condition, or a `;`/`)` separator is missing.

### Chemical formulas and reactions

Chemical element symbols are case-sensitive and render upright. A count immediately
after an element or parenthesized group becomes a native subscript:

| Input | Result |
|---|---|
| `H2O` | H₂O |
| `CO2` | CO₂ |
| `NaCl` | NaCl with upright element symbols |
| `Ca(OH)2` | Ca(OH)₂ |

Reaction sides may contain integer coefficients and `+`-separated compounds. Arrow
spellings are normalized as follows:

| Input | Native arrow |
|---|---|
| `2H2 + O2 -> 2H2O` | `→` |
| `H2(g) + I2(g) <-> 2HI(g)` | `⇌` |
| `CaCO3 =>[heat] CaO + CO2` | `⇒` with `heat` above the arrow |

The supported physical-state suffixes are `(aq)`, `(g)`, `(l)`, and `(s)`. An
optional ASCII annotation in square brackets may immediately follow an arrow, as in
`->[heat]`. MathFmt formats notation only; it does not check reaction balancing or
chemical validity beyond recognizing standard element symbols.

### Physics notation

First-order partial derivatives accept equivalent ASCII, Unicode, and explicit
function forms:

| Input | Result |
|---|---|
| `partial f / partial x` | Stacked `∂f/∂x` fraction |
| `∂f/∂x` | Stacked `∂f/∂x` fraction |
| `partial(f,x)` | Stacked `∂f/∂x` fraction |

Tensor indices use subscript-then-superscript order. Both `T_i^j` and
`T_{i}^{j}` render as one combined native subscript/superscript structure; the
braces are grouping syntax and are not displayed.

Bra-ket notation accepts compact ASCII or Unicode, plus explicit functions:

| Input | Result |
|---|---|
| `<phi\|psi>` | `⟨phi\|psi⟩` |
| `⟨φ\|ψ⟩` | `⟨φ\|ψ⟩` |
| `braket(phi,psi)` | `⟨phi\|psi⟩` |
| `bra(phi) ket(psi)` | `⟨phi\|psi⟩` |

Standalone Unicode partial derivatives are high-confidence scan candidates.
ASCII partial phrases, tensor indices, and bra-ket forms are reported at medium
confidence so prose-like notation remains reviewable. Use `$...$` to mark any of
these forms explicitly and select them at high confidence.

### User-defined symbol aliases

Use a JSON alias profile to render project-specific ASCII tokens as one Unicode
mathematical symbol without editing MathFmt source code:

```json
{
  "name": "engineering",
  "aliases": {
    "ohm": "Ω",
    "mapsTo": "↦",
    "complexes": "ℂ"
  }
}
```

Alias tokens must start with an ASCII letter and contain only ASCII letters or
digits. Each value must be exactly one Unicode mathematical symbol. Core syntax
names such as `sqrt`, `lim`, `sum`, `cases`, `partial`, `bra`, and `ket` are
reserved and cannot be overridden. Invalid, duplicate, or unsupported entries stop
the command with a clear error.

Aliases affect parsing, not candidate discovery. Keep a custom standalone symbol
inside `$...$`, or use it in a formula with a normal scanner anchor such as `=`.
The same alias profile must be supplied to `scan`, `apply`, and review-aware
`validate`; MathFmt compares the profile SHA-256 digest before conversion.

---

## 4. MathML Output Mapping

| AST node | MathML element(s) |
|---|---|
| `number` | `m:mn` |
| `identifier` (e.g. `x`, `e0`) | `m:mi` or `m:msub` (when subscripted like `p1`) |
| `identifier` `pPAIR` | `m:msub` with `p` and `m:mrow(1, ,, 2)` |
| `identifier` `∞` | `m:mo` (infinity) |
| `identifier` `Δ`, `π` | `m:mi` (Greek letter) |
| `derivative` | `m:mfrac` with stacked numerator/denominator |
| `partial_derivative` | `m:mfrac` with `∂` numerator/denominator runs |
| `subsup` tensor | `m:msubsup` |
| `bra`, `ket`, `braket` | Angle/bar `m:mfenced` delimiters |
| user alias | `m:mi` for letter-like symbols or `m:mo` for operator-like symbols |
| `group` `(...)` | `m:mfenced` |
| `sqrt` | `m:msqrt` |
| `function` `sin(…)` | `m:mrow(m:mi(sin), m:mfenced(…))` |
| `limit` `lim(p→0)` | `m:munder(m:mi(lim), …)` |
| `unary` `−x` | `m:mrow(m:mo(−), …)` |
| `power` `x^2` | `m:msup` |
| `binary` `/` | `m:mfrac` (stacked fraction, outer groups stripped) |
| `binary` `*` or `implicit` | `m:mrow` with invisible-times `m:mo` (U+2062) |
| `binary` `+` `−` `=` `→` etc. | `m:mrow(left, m:mo(op), right)` |
| `sequence` `a, b, c` | `m:mrow` with `m:mo(,)` separators |
| `piecewise` / `cases` | Open-brace `m:mfenced` containing a two-column `m:mtable` |
| Chemical formula | Upright `m:mtext` element symbols with `m:msub` counts |
| Chemical reaction | `m:mrow` sides with `m:mo` arrow; annotated arrows use `m:mover` |

---

## 5. Scanning Heuristics

### Explicit LaTeX-style delimiters

DOCX text can mark formulas explicitly:

| Input in DOCX text | Scan `source` | Parsed `linear` | Display |
|---|---|---|---|
| `$x^2 + 1$` | `$x^2 + 1$` | `x^2 + 1` | `false` |
| `$$y = 2$$` | `$$y = 2$$` | `y = 2` | `true` |

Explicit delimiter candidates are treated as high-confidence formulas even when the
inner formula has no heuristic anchor operator. During `apply`, MathFmt removes the
delimiters and inserts only the native Word equation. Simple currency-like spans such
as `$12.00$` are ignored.

### Chemistry-specific detection

Full valid reaction spans are high-confidence candidates. Standalone formulas with
two or more recognized elements, such as `H2O`, `CO2`, and `NaCl`, are also
high-confidence. A single-element numbered formula such as `O2` is reported at
medium confidence and is not selected automatically. Bare element symbols such as
`C` or `Fe` are not auto-detected in prose; keep them inside a larger chemical
formula or reaction when chemistry styling is required. A bare one-letter symbol
remains an ordinary math identifier. This keeps ordinary prose, acronyms, and
letter-to-letter mappings such as `A -> B` from being over-selected.

### Reviewed multiline and aligned formulas

Use either a LaTeX-style double backslash or a real line break in a reviewed
candidate's `linear` value:

| Reviewed `linear` | Result |
|---|---|
| `a = b \\ c = d` | Two-row native Word equation array |
| `x = y` followed by a real line break and `z = w` | Two-row native Word equation array |

Each row is parsed with the normal formula grammar. When every row has a top-level
relation, MathFmt emits a native two-column OMML alignment matrix: the left column is
right-aligned and the relation/right side is left-aligned. This preserves row order and
aligns at the first relation symbol (`=`, `<`, `>`, `≤`, `≥`, `≠`, `≈`, `→`, `⇒`, or
`⇌`) in both Word and LibreOffice. Rows without a common relation fall back to native
`m:eqArr`. Empty rows are rejected with `FormulaError`.

Outside the explicit-delimiter, step-function, and chemistry detectors described
above, formulas are detected by walking character runs. A generic span must satisfy
**all** of:

1. **Character whitelist**: every character in `"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789₀₁₂₃₄₅₆₇₈₉ₚᵥₜ⁰¹²³⁴⁵⁶⁷⁸⁹+-*/^=<>!...()[]{}.,"` (full list in `MATH_CHARS` in `core.py`).
2. **Anchor operator**: must contain at least one of `=` `≠` `<=` `>=` `!=` `→` `⇒` `⇌` `<->` `->` `±` `+/-` `√` `sqrt` `lim`.
3. **Minimum score** ≥ 4: scored by `math_score` from relation symbols, arithmetic operators, function-call patterns, and digits.

### Code exclusion

A paragraph is skipped entirely when `likely_code` returns `True`:

- Starts with `%`, `#`, `pkg`, `clear`, `close`, `plot`, `grid`, `xlabel`, `ylabel`, `title`, `legend`, `hold`, `for`, `while`, `if`, `function`, `import`, `from`.
- Contains `;` with assignment (e.g. `y = step(sys, t);`).
- Matches known function patterns that end with `;` (e.g. `tf(…);`, `step(…);`, `roots(…);`, `exp(…);`).

### Existing equations and images

Paragraphs containing `m:oMath`, `m:oMathPara`, `w:drawing`, or `w:pict` are skipped entirely during scanning. They appear in the report summary as `existing_equations` and `drawing_paragraphs`.

### Pre/post trimming

Candidates are cleaned by removing:

- Leading/trailing punctuation (`.`, `,`, `;`, `:`)
- Trailing prose after a sentence-ending `.` followed by a capital letter
- Trailing French/English linking words: `avec`, `si`, `et`, `Elle`, `C`, `La`, `Pour`, `est`, `sont`, `vaut`, `discriminant`, `vers`, `equals`, `is`

---

## 6. Limitations

### Supported structured forms

| Structure | Supported example | Regression test |
|---|---|---|
| Integral | `∫x*dx` | `test_integral_notation` |
| Summation | `∑_{i=1}^{n} x_i` | `test_summation_notation` |
| Matrix | `[[a,b],[c,d]]` | `test_matrix_notation` |
| Vector | `v = [x, y, z]` | `test_vector_notation` |
| Limit subscript | `lim_{x→0} f(x)` | `test_limit_subscript_notation` |
| Explicit brace grouping | `{a+b}` | `test_explicit_brace_grouping` |

Common Unicode number sets (`ℝ`, `ℂ`, `ℕ`, `ℤ`, `ℚ`, `ℙ`, `ℍ`) and operators
(`∈`, `∉`, `⊂`, `⊆`, `⊃`, `⊇`, `∪`, `∩`, `∧`, `∨`, `⊕`, `⊗`, `∝`, `≡`, `≅`)
are accepted directly. Wrap short standalone expressions in `$...$` when automatic
scanning would otherwise treat them as prose.

### Heuristic limitations

- **False positives**: prose that resembles a formula may be selected as a candidate. Always review the `candidates.json` before applying.
- **False negatives**: most formulas without anchor operators (`=`, `≠`, `≤`, `≥`,
  `!=`, `→`, `->`, `±`, `+/-`, `√`, `sqrt`, `lim`) are not detected. Supported
  chemistry and physics patterns have dedicated conservative detectors.
- **Cross-paragraph**: each paragraph is scanned independently; a formula split across two paragraphs is not
  merged. Keep the formula in one paragraph or mark each complete expression explicitly with `$...$`.

### Chemistry limitations

- Element capitalization must be standard (`NaCl`, not `NACL` or `nacl`).
- Supported states are limited to `(aq)`, `(g)`, `(l)`, and `(s)`.
- Ionic charges, isotope notation, electron notation, hydrate dots, and conditions
  below an arrow are outside the supported chemistry grammar. In chemistry mode, `+` separates compounds.
- Arrow annotations use the explicit form `->[text]`; free-standing condition words
  are not inferred from surrounding prose.
- MathFmt does not balance reactions or verify stoichiometry.

### Physics limitations

- Partial-derivative shorthand is first-order. Higher-order and mixed partials are
  not inferred; use reviewed lower-level notation when needed.
- Tensor scripts must use subscript-then-superscript order (`T_i^j`). Automatic
  raising/lowering, index contraction, and tensor semantics are not evaluated.
- Compact bra-ket syntax supports one separator (`<phi|psi>` or `⟨φ|ψ⟩`). Operator
  matrix elements such as `⟨φ|A|ψ⟩` are outside the compact-form grammar;
  compose them with explicit `bra(...)` and `ket(...)` notation.

### Symbol alias limitations

- Alias profiles are JSON files with `name` and `aliases` fields; TOML is not
  currently supported.
- Alias values are one Unicode symbol, not replacement expressions or multi-symbol
  macros.
- Alias files do not create new scanner heuristics. Use explicit `$...$` delimiters
  for standalone custom symbols.
- A reviewed report that records aliases must be applied or validated with the same
  profile contents; renaming or editing the profile changes its digest.

### Structural limitations

- **Hyperlinks**: formulas inside `w:hyperlink` are skipped (the run nesting can't be reconstructed reliably).
- **Images**: paragraph-level image detection skips the whole paragraph; an image embedded mid-paragraph before a formula will cause the formula to be missed.
- **Formatting preservation**: when a formula occupies part of a single `w:r` (run), the suffix text after the formula inherits the original run's formatting. When a formula spans multiple runs, formatting of the boundary runs is preserved but intermediate runs' formatting is discarded.

### Platform

- **Built-in Python backend**: MathFmt includes a pure-Python OMML generator that works on
  Windows, macOS, and Linux without Microsoft Office. This is the default when `MML2OMML.XSL`
  is not detected.
- **Office XSL backend** (optional): when Microsoft Office is installed, MathFmt automatically
  detects and uses `MML2OMML.XSL`. The `--xsl` flag overrides automatic detection.

---

## 7. Error Handling

### Parse failures

When `formula_to_mathml` raises `FormulaError`, the candidate is marked:

```json
{
  "id": "f0012",
  "selected": false,
  "parse_status": "review",
  "parse_error": "Unrecognized formula text near: '@ 2'"
}
```

Common parse errors:

| Error message | Cause |
|---|---|
| `Unrecognized formula text near: …` | Character not in tokenizer vocabulary |
| `Expected …, got …` | Syntax error (e.g. missing operator or bracket) |
| `Mismatched group: (}` | Opening/closing bracket mismatch |
| `Unsupported AST node: …` | Internal — valid parse but unknown node kind |

### Apply failures

During `apply`, a candidate is skipped (not converted) when:

- The DOCX part is not found in the file (`error: "DOCX part not found"`)
- The paragraph index is out of range (`error: "Paragraph index out of range"`)
- The source text no longer matches the document (`error: "Reviewed source no longer matches the paragraph span"`)
- The formula spans a hyperlink boundary (`error: "Formula span crosses a hyperlink or unsupported nested run"`)
- Any `FormulaError` or `etree` error during conversion

Skipped candidates appear in the result report under `skipped` and do not block other candidates.

---

## 8. Design Philosophy

See `skills/mathfmt/references/paper-notation.md` for the notation conventions MathFmt targets:

- Stacked fractions for division
- Radical bars for `sqrt(…)`
- True superscripts and subscripts (not `^`/`_` characters)
- Leibniz fraction derivatives
- `u(t)` for the unit-step function
- Standard mathematical operator glyphs (`±`, `≠`, `≤`, `≥`, `→`, `∞`, `Δ`, `π`)
- Invisible multiplication for coefficient-variable products
- Top-level `+`/`-` splitting for long table formulas

---

## 9. Reverse Conversion: OMML → Text

`omml_to_text(omath_elem)` (in `mathfmt.omml`) does the reverse of section 4's
mapping: given a native `m:oMath`/`m:oMathPara` element, it reconstructs a linear
string that re-parses to an equivalent formula through `formula_to_mathml`. It is
not guaranteed to reproduce the exact original input text — only an equivalent
one — for example, both `2*x` and `2x` reconstruct as `2x`. A subscript
reconstructs with an explicit `_` (`p_1` rather than the bare `p1` shorthand),
*except* a chemistry element/group count, described next.

Supported: numbers, identifiers, operators and relations, fractions (including
derivative and partial-derivative fractions, via `d`/`∂` detection), radicals,
super/subscripts, delimited groups (parentheses, brackets, braces, bra-ket
delimiters, vectors), `lim(...)` / annotated reaction arrows (`=>[heat]`),
bounded n-ary big operators (`m:nary` with both bounds present, e.g.
`sum(i=1,n) i` / `prod(k=1,m) k`), and chemistry formulas and reactions
(`H2O`, `(OH)2`, `2H2 + O2 -> 2H2O`) — these reconstruct in their original
bare form (no `_`) so they re-parse through MathFmt's dedicated chemistry
grammar rather than as a generic subscript.

Chemistry detection is a heuristic, not a guarantee: it looks for the
upright/plain OMML run styling MathFmt's own chemistry grammar marks element
symbols with, narrowed by also requiring the subscript to be all digits (an
element count always is). `omml_to_text` accepts any `m:oMath`, not just
MathFmt's own output, so hand-authored OMML that happens to combine an
upright-styled subscript base with an all-digit subscript for an unrelated
reason would be misread as chemistry.

Not supported — `OmmlConversionError` is raised naming the element rather than
guessing at a wrong answer:

- Matrices, piecewise/`cases` tables, **and MathFmt's own multi-line/aligned
  equation output** — all use native OMML `m:m` (a two-column relation-aligned
  matrix for aligned lines, or a matrix wrapped in `{` for `cases`), and a
  one-column layout uses `m:eqArr`. Section 5's multi-line/aligned-equation
  support is otherwise a separately documented, commonly-used feature; it is
  specifically *not* covered by `omml_to_text` despite not being a
  mathematical matrix.
- An `m:nary` missing one of its two bounds (`m:sub`/`m:sup`), or naming an
  operator character other than `∑`, `∏`, or `∫` — and other elements outside
  the list above
