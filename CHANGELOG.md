# Changelog

All notable changes to MathFmt are documented here.

## [Unreleased]

### Fixed
- **A big operator no longer stretches across a following relation.** When
  reading MathML in which the operator and its operand are flat siblings — the
  shape LaTeXML and MathJax produce for `\sum_{i=1}^{n} a = S` — the operand
  slot took the whole rest of the row, so the summation sign grew to span the
  `= S` as well. It now takes the single next sibling, unwrapping an `mrow`,
  which is the same selection Word's own converter makes and matches how
  MathFmt's grammar binds `sum(i=1,n) a = S`. Output for formulas written in
  MathFmt's own syntax is unchanged.
- **`omml_to_text` no longer lets a relation escape a big operator.** An
  `m:nary` from Word whose operand contains a relation (`a = S`) came back as
  `sum(i=1,n)a=S`, which re-parses with a body of just `a` and the `= S`
  outside the summation. Such an operand is now parenthesized. Operands
  containing only arithmetic are still emitted bare, so no parentheses appear
  that the source document did not have.

## [1.4.0] - 2026-09-05

### Added
- **`mathfmt gui` previews and edits each formula before converting.** Every
  candidate in the review list now renders as a real equation, with its
  parser-ready text in an editable field; editing the text and clicking away
  re-renders it, or shows the parse error and hint inline while keeping the
  last good rendering visible but dimmed. What you leave in the field is what
  gets converted. The server re-parses every edit, so a bad one is reported in
  the conversion's skipped list rather than written into the document, and
  clearing a field falls back to the scanned text rather than converting an
  empty formula.
  This is what makes v1.3's medium-confidence LaTeX candidates reviewable
  without leaving the GUI to hand-edit `candidates.json`.
  Previews need a browser with MathML support (every current Chromium, Firefox
  and Safari has it); without it the page says so once and falls back to the
  linear text, with editing and validation unaffected.
- New `POST /preview/<token>` route on the GUI server, and two new fields
  (`linear`, `mathml`) on each candidate in the `/scan` response. The `/apply`
  selection payload accepts `{"selected", "linear"}` alongside the bare boolean
  it has taken since v1.2.

### Changed
- The `dev` extra pins ruff to one minor series (`ruff>=0.16,<0.17`) instead of
  `ruff>=0.6`. Ruff is pre-1.0, so its formatter's stable style may change in
  any `0.x.0`: 0.16.0 began formatting Python blocks inside Markdown, which
  turned a green local run into a nine-platform CI failure with no code change
  behind it. The floor matches the ceiling's series so a contributor's
  `pip install -e ".[dev]"` and CI agree on one style rather than disagreeing
  until a push. No effect on the published package — this is a development
  dependency only. Contributors on an older ruff should re-run
  `pip install -e ".[dev]"`.
- `omml_to_text` reports an `m:acc`/`m:nary` whose `m:chr` is present but
  carries no `m:val` with its own message (`found an m:acc m:chr with no
  m:val`) instead of the previous `does not support the accent character
  None`. Both cases already raised `OmmlConversionError`; only the message
  changed, so code matching on the old text needs updating.
- **A bounded `sum`/`prod` now writes its operand inside the equation's own
  operand slot**, and marks the operator as growing. Previously the slot was
  left empty and the body emitted beside it: the equation rendered in the right
  order, but Word's equation editor showed an empty placeholder with the body
  outside the template, and the operator did not stretch to a tall operand
  (`sum(i=1,n) (a+b)/c` drew a small sigma next to a full-height fraction).
  Documents converted before this are still valid and still render; re-run
  `mathfmt convert` to pick up the new shape.
- `omml_to_text` reads an `m:nary` that omits `m:naryPr`, or its `m:chr`, as a
  summation — the operator ISO/IEC 29500 documents as that element's default —
  instead of rejecting it. A *present* `m:chr` naming an operator it does not
  know still raises.

### Fixed
- **A `munderover` that is not a big operator no longer produces a malformed
  equation.** Any such element — a doubly-annotated reaction arrow, or any base
  that is not one of `∑ ∏ ∫` — was written as an n-ary object whose operator
  attribute held the base's whole text (`lim`, three characters in an attribute
  the format defines as one), with an empty operand slot and the body stranded
  beside it. These now become the stacked under/over annotation Word uses.
- The operator character is normalized before being written, so pretty-printed
  MathML (an `<mo>` carrying newlines and indentation around its symbol) no
  longer produces an equation that MathFmt's own reader then refuses.

### Validation
- `mathfmt validate` now structurally checks `m:nary`, reporting a missing
  `m:sub`, `m:sup` or `m:e` the same way it already reports a fraction missing
  its denominator. **This can flag documents that previously passed** — the
  check is new, not the malformation.

## [1.3.0] - 2026-09-05

### Added
- **A documented subset of LaTeX may now be used as formula input.** Greek
  letters, relation/set operators, function names and spacing macros;
  `\frac`/`\dfrac`/`\tfrac`; `\sqrt{x}` and `\sqrt[n]{x}`; the accent macros
  `\bar` `\overline` `\hat` `\vec` `\dot` `\ddot`; `\text{…}`/`\mathrm{…}`;
  `\left`/`\right`; `_{…}`/`^{…}` scripts; bounded `\sum`/`\int`/`\prod` and
  `\lim`; and the `matrix`/`pmatrix`/`bmatrix`/`cases`/`aligned`/`align`
  environments. Anything outside the subset is **rejected with an error naming
  the macro** and a hint pointing at the full list, rather than being guessed
  at. See `docs/formula-syntax.md` §10 for the table and the six documented
  limitations.
- **Scanning learned two LaTeX shapes.** `\(…\)` and `\[…\]` join `$…$`/`$$…$$`
  as explicit, high-confidence, auto-selected spans (inline and display
  respectively). An *undelimited* macro in prose — `\bar{x}`, `\sum_{i=1}^{n} i`
  — is a new **medium**-confidence candidate that is never auto-selected, so it
  reaches the review list without being converted unattended. A span must both
  contain a macro MathFmt knows and actually parse before it is offered at all,
  so a Windows path such as `C:\Users\name` and an unsupported macro such as
  `\substack{a}` stay prose.
- `root(x, 3)` — an n-th root as a native `m:rad` with a degree, distinct from
  `sqrt(x)`. Reverses through `omml_to_text`.
- `accent(x, bar)` — overbar, hat, vector arrow, dot and double-dot accents as
  native `m:acc` with Word's combining marks. Reverses through `omml_to_text`.
- A quoted upright text atom: `x = 3 "kg"` renders `kg` as upright `m:mtext`
  rather than italic variables. Its contents are never parsed as math, so
  `"a + 1, b"` stays text. It reverses as its bare content, without the quotes.
- `∇` and `∓` are now tokenized, so they parse when they reach a formula. Like
  the other bare Unicode symbols they are not picked up by generic candidate
  discovery — wrap them in `$…$`.

### Changed
- A comma is no longer accepted as a decimal separator in formula numbers: the
  `NUMBER` token is now `\d+(?:\.\d+)?` (was `\d+(?:[.,]\d+)?`). A comma is
  MathFmt's sequence/argument/matrix separator everywhere else, and the two
  readings collided — the decimal reading always won, so `[[1,2],[3,4]]`
  silently parsed as a 2x1 matrix of the "numbers" `1,2` and `3,4` instead of
  a 2x2 integer matrix, and `[1,2,3]` silently lost an element and became the
  2-item vector `1,2` / `3`. Input like `x = 3,14` (European decimal) is no
  longer one number; it now parses as the sequence `3, 14`, which still
  renders as `3,14`. Use `.` for decimals, e.g. `x = 3.14`.
  This one tokenizer change is user-visible in a few more places:
  - An explicit subscript like `A_1,2` used to bind the whole `1,2` into the
    subscript (`A` with subscript `1,2`); it now binds only `1`, and the
    trailing `,2` becomes a separate sequence item next to it. Write
    `A_(1,2)` if you want both digits in the subscript.
  - A thousands separator inside an explicit formula span, e.g. `$1,234$`,
    used to convert as a single number; it now converts as the three-item
    sequence `1`, `,`, `234`, with comma-operator spacing. This candidate
    scores `confidence=high` and is auto-selected, so `mathfmt convert`
    applies this reformatting without a review step — re-check any existing
    document containing comma-grouped thousands after upgrading.
  - Fixed a related, newly-reachable bug in bracket call syntax: an
    identifier followed by a `[...]` group whose elements are comma-separated
    (e.g. `x in [0,1]`, `f [a,b]`) used to silently keep only the first
    element and force the brackets to `()` — `x in [0,1]` rendered as
    `in(0)`, dropping the `1`. It now falls back to implicit multiplication
    (`x`⁢`in`⁢`[0,1]`) and keeps every element with its original square
    brackets. This was already broken for non-numeric elements before this
    release (`f [a,b]` already dropped `b`); the number tokenizer change made
    it reachable for numeric intervals too, which is the more common shape
    in textbooks.
  - `bra(1,2)` and `braket(1,2)` swap behavior as a consequence: `bra(...)`
    takes exactly 1 argument, so `bra(1,2)` — previously parsed as `bra` of
    the single number "1,2" — now raises (`bra requires 1 argument`).
    `braket(...)` takes exactly 2, so `braket(1,2)` — previously rejected for
    the same reason — now converts.
- `accent` and `root` are now reserved alias tokens (`RESERVED_ALIAS_TOKENS`):
  an existing alias profile that defines either name is rejected at load
  (`Alias token 'accent'/'root' is reserved by MathFmt core syntax`). Both
  names are now documented constructs (`accent(x,bar)`, `root(x,3)`), and the
  alias branch runs before construct dispatch, so an unreserved alias would
  otherwise silently shadow the construct instead of failing loudly.
- `sum(i=1,n) i` / `prod(k=1,m) k` — a bounded n-ary operator — now converts
  with both bounds correctly attached as a native OMML big-operator (`m:nary`
  with `m:sub`/`m:sup`), and `omml_to_text` reverses that shape back to
  `sum(...)`/`prod(...)`. Previously the MathML `munderover` carrying the
  bounds fell through `mathml_to_omml_py`'s unknown-tag fallback and was
  flattened: both bounds were silently dropped into plain adjacent text runs
  (e.g. `sum(i=1,n) i` converted as if it read `∑i=1ni`, with no subscript or
  superscript at all). `int(0,1) f` was and remains unaffected — integral
  bounds already used `m:sSubSup`, not `m:nary`.

### Fixed
- A `munderover` whose base is not an n-ary operator — a doubly-annotated
  arrow, or any base that is not `∑`/`∏`/`∫` in an `mo` — no longer becomes a
  malformed `m:nary` whose `m:chr` holds the base's entire text (`m:val="lim"`,
  three characters in an attribute the format defines as one) with an empty
  `m:e` and the operand orphaned as a following sibling. It now becomes the
  nested `m:limUpp`/`m:limLow` pair Word writes for that shape, which is
  lossless.
- Pretty-printed MathML input no longer produces an `m:chr` padded with the
  newlines and indentation around the operator character, which MathFmt's own
  reverse converter then refused to read. The operator's text is normalized the
  way `MML2OMML.XSL` normalizes it.
- `mroot` is no longer flattened by `mathml_to_omml_py`'s unknown-tag fallback,
  which silently dropped the radical.
- Bracket call syntax no longer drops arguments (see the `Changed` entry above
  for the full description).
- `omml_to_text` reads an `m:nary` that omits `m:naryPr`/`m:chr` as the
  summation ISO/IEC 29500 documents as that element's default, instead of
  rejecting it. A *present* `m:chr` carrying no `m:val` still raises — the
  default covers an absent property, not a valueless one.
- `mathfmt validate` flags an `m:nary` missing `m:sub`, `m:sup`, or `m:e`.

## [1.2.0] - 2026-09-03

### Added
- `mathfmt gui` now shows every scanned formula candidate as a checklist (source
  text, confidence, and parse status/reason) before converting, pre-checked with
  the same conservative defaults as `mathfmt convert`. The server-side flow is now
  a `/scan` step followed by an `/apply` step instead of one combined `/convert`
  request; concurrent `/apply` calls for the same session are serialized, and a
  failed/strict re-apply clears any earlier attempt's output so `/download`
  never serves a stale, superseded conversion.
- `FormulaError.to_dict()` (and therefore a scan candidate's `parse_error_details`
  and an apply report's `error_details`) includes a plain-language `hint` for
  recognized mistakes — mismatched brackets, a `cases`/`{...}` branch missing
  `if`, wrong argument counts, and a few other common shapes.
- `omml_to_text(omath_elem)` (in `mathfmt.omml`, re-exported from the top-level
  package) converts a native `m:oMath`/`m:oMathPara` element back to MathFmt's
  linear formula syntax — the reverse of `mathml_to_omml_py`. Chemistry formulas
  and reactions reconstruct in their original bare form (`H2O`, `(OH)2`) so they
  keep their upright styling on reparse. Raises the new `OmmlConversionError`
  for constructs it doesn't reverse (matrices, piecewise/`cases` tables,
  MathFmt's own multi-line/aligned equation output, n-ary operators) instead
  of guessing. See `docs/formula-syntax.md` section 9 for exact scope.
- `packaging/`: a `build_exe.py` script (PyInstaller) that bundles `mathfmt gui`
  into a standalone double-clickable executable for people without Python
  installed. Not part of the automated release pipeline — see
  `packaging/README.md`.

### Changed
- CI now builds the standalone GUI executable and smoke-tests it (boots,
  serves its page, stops cleanly) on every push and PR, via
  `packaging/smoke_test.py`. Building and distributing the executable (e.g.
  attaching it to a GitHub Release) remains a manual, deliberate step outside
  `publish.yml`.

### Fixed
- `mathfmt gui` (and the standalone executable) no longer crashes with
  `UnicodeEncodeError` immediately after printing its startup URL when stdout
  isn't UTF-8 capable — a non-UTF-8 Windows console codepage, or stdout/stderr
  redirected to a file or pipe, which drops the console's codepage entirely.
  `serve()` now reconfigures both streams to UTF-8 (with lossy fallback) before
  printing anything. Found by the new exe smoke test above, which redirects
  output exactly this way.

## [1.1.0] - 2026-08-31

### Added
- `mathfmt gui`: a local, stdlib-only browser drag-and-drop interface. Binds to
  `127.0.0.1`, mirrors `convert`'s conservative scan → confidence filter → apply
  pipeline, and offers the converted DOCX and its JSON scan report for download.
  No new runtime dependency.

## [1.0.0] - 2026-08-08

### Added
- Stable, snapshot-tested top-level Python API with documented Semantic Versioning,
  report compatibility, exception boundaries, and a deprecation policy.
- Typed custom formula recognizers through `FormulaRecognizer` and
  `FormulaCandidate`, repeatable `--recognizer module:object` CLI options,
  deterministic overlap handling, strict plugin validation, and report provenance.
- Reproducible 100-page/800-formula performance benchmark with time, correctness,
  WPS compatibility, and peak-memory gates in GitHub Actions.
- Python 3.14 support across package metadata and the Windows/macOS/Linux CI matrix.

### Changed
- Package status is now Production/Stable.
- Large-document conversion parses and serializes each OOXML part once instead of
  once per paragraph; coverage validation also caches paragraph text per part.
- Conversion reports preserve recognizer provenance from the source review.

### Performance
- On the v1.0 Windows reference run, the 100-page/800-formula workflow completes in
  5.21 seconds with 5.9 MiB peak traced memory (scan 1.13 s, apply 1.33 s,
  validate 2.75 s).

## [0.5.0] - 2026-08-07

### Added
- `mathfmt convert` accepts multiple DOCX files, quoted glob patterns, and directories,
  with recursive discovery, centralized output/report directories, collision checks,
  per-file failure isolation, and an optional aggregate batch report.
- `mathfmt validate --compatibility wps` adds an offline WPS portability profile for
  Word-only alignment markers, alignment controls, and embedded equation objects.
- `scripts/wps_roundtrip.ps1` performs a hidden WPS Writer DOCX round-trip and PDF
  export without overwriting QA artifacts or terminating existing WPS processes.

### Fixed
- Piecewise condition labels use a non-breaking separator so WPS Writer does not
  collapse `if x` into `ifx` during rendering or DOCX round-trips.

## [0.4.0] - 2026-08-06

### Added
- LaTeX-style DOCX text delimiters: `$...$` scans as a high-confidence inline
  formula, and `$$...$$` scans as a high-confidence display formula.
- Scan reports now include `explicit: true` for delimiter-detected formulas while
  preserving delimiter text in `source` and parsing delimiter-free `linear`.
- Reviewed multiline formulas support `\\` and real line-break separators, preserve
  row order, and use a cross-application OMML alignment matrix at the first relation
  symbol, falling back to `m:eqArr` for lines without a common relation.
- Scan and conversion reports include multiline line counts and layout metadata.
- Piecewise formulas support both `{expression, condition; ...}` and
  `cases(expression if condition; ...)`, rendering as a native Word left brace with
  aligned expression and condition columns.
- Basic chemical formulas use upright standard element symbols, native subscripts,
  parenthesized groups, and `(aq)/(g)/(l)/(s)` state suffixes.
- Chemical reactions support `->`, `<->`, and `=>`, integer coefficients,
  `+`-separated compounds, and optional arrow annotations such as `->[heat]`.
- Scan reports identify chemistry candidates and conservatively leave ambiguous
  single-element formulas unselected.
- Physics notation supports ASCII and Unicode partial derivatives, combined tensor
  subscript/superscript indices, and compact or function-style bra-ket forms.
- Scan reports identify `partial_derivative`, `tensor`, and `braket` candidates;
  prose-like ASCII physics notation remains unselected for review by default.
- JSON symbol alias profiles add user-defined ASCII token to Unicode math-symbol
  mappings across `scan`, `apply`, `convert`, and `validate`.
- Scan, conversion, and validation reports record alias profile metadata and reject
  missing or changed profiles before reviewed formulas are processed.
- Common Unicode number sets and set/relation operators are accepted directly.
- DOCX package reads enforce entry-count, uncompressed-size, compression-ratio,
  duplicate-member, and encryption limits before extracting ZIP members.
- OOXML parts are parsed without DTD loading, entity expansion, or network access.
- `mathfmt doctor` reports lxml, libxml2, and libxslt versions in text and JSON output.

### Fixed
- Validation coverage now parses reviewed candidates through `linear` when present,
  so delimiter-detected formulas validate consistently with `apply`.
- Multiline validation parses and compares every reviewed line while keeping
  candidate-level coverage counts stable.
- Cases parser errors identify the failing branch and missing `if`, condition, or
  branch separator.
- Explicit `$...$` and `$$...$$` candidates remain scannable when their semicolon
  syntax would otherwise resemble a code paragraph.
- Formula syntax documentation now matches the supported integral, summation,
  matrix, vector, limit, brace-grouping, and Unicode forms.
- Relation-aligned multiline equations no longer expose Word's literal `&` alignment
  marker when rendered by LibreOffice.

## [0.3.0] - 2026-06-25

### Added
- v3 conversion/validation report metadata: `schema_version`, `report_type`, `command`,
  `inputs`, `outputs`, `options`, `summary`, and per-formula `formulas`.
- `mathfmt apply --dry-run` previews reviewed conversions and writes a report without
  writing a DOCX output file.
- `mathfmt apply --strict` and `mathfmt convert --strict` block DOCX output when any
  selected formula fails or is skipped.
- Structured parser error details in scan, apply, and validation reports: column,
  nearby context, expected token, and found token when available.
- Per-formula warnings for selected formulas that fail or are skipped during apply.

## [0.2.3] - 2026-06-22

### Fixed
- **Parser:** `...` (ellipsis) now tokenized as `…` — `1+2+...+n` parses without error.
- **Parser:** `n!` factorial added as postfix operator.
- **Parser:** `int(...)` / `sum(...)` / `prod(...)` now produce proper n-ary MathML
  (`munderover` for sum/prod, `msubsup` for integrals) with bounds and body, instead
  of being split as implicit multiplication.
- **Parser:** multi-letter identifiers (e.g. `x_bar`) now parse correctly; bar is no
  longer split into `b * a * r`.
- **Scanner:** single-letter `C` removed from French text-boundary rule, so
  `sin(x) + C` is no longer truncated.
- **Scanner:** `1(t)` and `Γ(t)` (unit step) now detected by an exact pattern before
  the general heuristic scan.
- **Validator:** OMML nesting-depth limit raised from 8 to 32; only math-structure
  elements (`f`, `rad`, `sSup`, `sSub`, …) count toward depth, not container/run
  wrappers. Depth exceeding the limit is now a warning, not a hard validation error.

### Documentation
- Bilingual Quick Start section added to README (`pip install`, `doctor`, `convert`).
- `examples/README.md` — step-by-step walkthrough for new users.
- `ROADMAP.md` — phased version plan from v0.2.x through v1.0.0.
- `CLAUDE.md` — comprehensive project reference for Claude Code (fixed several
  factual inaccuracies: API count, function signatures, CI matrix shape, backend
  default, `--output` flag).
- `tests/acceptance/` — 5 real-world test DOCX files with generator script.
- `convert` command examples now use `--output` instead of the non-existent `-o`.
- `apply` command examples now include the required `--report` flag.
- `doctor` output description and candidate review instructions corrected.

### Tests
- 5 new regression tests covering ellipsis, factorial, indefinite integral `+C`,
  step function detection, and deeply nested standard-deviation formula.
- Acceptance test pipeline: scan → convert → validate on 5 real-world DOCX files.

## [0.2.2] - 2026-06-21

### Fixed
- Ruff/CI errors resolved (unused imports, f-string without placeholders, import order).
- Stable and pre-release update caches are now isolated — running `--pre` no longer
  poisons the normal update check, and vice versa.
- SemVer pre-release labels (`alpha`, `beta`, `rc`) are now compared correctly per
  SemVer 2.0 — a stable release sorts after any pre-release with the same base.
- Network failures during `mathfmt update` now exit with code 2 instead of 0,
  so CI scripts can distinguish "up-to-date" from "could not check."
- Malformed cache files (JSON arrays, primitives, missing keys) no longer crash
  `_load_cache`.
- `mathfmt validate` now reports the actual installed version instead of a
  hardcoded string.
- README version roadmaps (Chinese and English) reflect actual release dates.
- Maintainer email `gml853503962@gmail.com` added to package metadata.

## [0.2.1] - 2026-06-21

### Added
- `mathfmt update` — checks GitHub Releases for newer versions and shows upgrade
  instructions. Supports `--check` (CI-friendly exit codes), `--pre` (pre-releases),
  and `--force` (bypass 1-hour cache).
- `mathfmt.update` public API: `check_for_updates()`, `UpdateInfo`, `fetch_latest_release()`.

## [0.2.0] - 2026-06-21

### Added
- Built-in pure-Python OMML generator — no Microsoft Office or `MML2OMML.XSL` required.
  Works on Windows, macOS, and Linux.
- `mathfmt validate` — offline DOCX structure and OMML correctness checks (package
  integrity, OMML structure, formula coverage, cross-backend comparison).
- Confidence scoring (`high`/`medium`/`low`) on all scan candidates. Default `convert`
  only applies high-confidence formulas. `--confidence` flag on `convert`.
- Parser expansion: integrals (`∫`), summation (`∑`), matrices (`[[a,b],[c,d]]`),
  vectors (`[x,y,z]`), piecewise (`{0,x<0;1,x>=0}`), and subscript limit (`lim_{x→0}`).
- `doctor` now reports `backend: python` (default) or `backend: office-xsl`.
- `apply` and `convert` no longer require `--xsl`; Python backend used automatically.
- `.github/ISSUE_TEMPLATE/` with bug report and feature request templates.
- `SECURITY.md` now includes explicit 7-day response timeline.

### Changed
- `mathml_to_omml` dispatches to XSL or Python backend based on availability.
- `apply_docx(xsl_path)` is now optional (`None` = Python backend).
- `scan_docx` report upgraded to `schema_version: 2` with `confidence` fields.
- Roadmap now includes target dates (Q3 2026, Q4 2026, 2027).

### Documentation
- Added `docs/formula-syntax.md`, `docs/workflow.md`.
- Expanded `README.md` with 12 quick examples, compatibility matrix, and version roadmap.

## [0.1.0] - 2026-06-21

- Initial release: review-first `scan` and `apply`, conservative `convert`,
  environment `doctor`, native Word OMML output, Codex Skill, tests, bilingual docs.
