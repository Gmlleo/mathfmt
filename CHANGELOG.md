# Changelog

All notable changes to MathFmt are documented here.

## [Unreleased]

### Added
- `mathfmt gui` now shows every scanned formula candidate as a checklist (source
  text, confidence, and parse status/reason) before converting, pre-checked with
  the same conservative defaults as `mathfmt convert`. The server-side flow is now
  a `/scan` step followed by an `/apply` step instead of one combined `/convert`
  request.
- `FormulaError.to_dict()` (and therefore a scan candidate's `parse_error_details`
  and an apply report's `error_details`) includes a plain-language `hint` for
  recognized mistakes — mismatched brackets, a `cases`/`{...}` branch missing
  `if`, wrong argument counts, and a few other common shapes.
- `omml_to_text(omath_elem)` (in `mathfmt.omml`, re-exported from the top-level
  package) converts a native `m:oMath`/`m:oMathPara` element back to MathFmt's
  linear formula syntax — the reverse of `mathml_to_omml_py`. Raises the new
  `OmmlConversionError` for constructs it doesn't reverse (matrices,
  piecewise/`cases` tables, n-ary operators) instead of guessing. See
  `docs/formula-syntax.md` section 9 for scope and known limitations.
- `packaging/`: a `build_exe.py` script (PyInstaller) that bundles `mathfmt gui`
  into a standalone double-clickable executable for people without Python
  installed. Not part of the automated release pipeline — see
  `packaging/README.md`.

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
