# MathFmt Roadmap · 路线图

This document records the completed path to the final stable release. MathFmt is a
single-maintainer project and is now in stable maintenance mode.

---

## v0.2.x — Documentation & Stability · 文档与稳定性

**Focus:** Make the project easier to discover, install, and trust.

- [x] v0.2.2 — CI/Ruff fixes, cache crash fix, exit code correction
- [x] v0.2.3 — Parser fixes (ellipsis, factorial, n-ary, 1(t), x_bar, C boundary); depth validation; docs & examples
- [x] Bilingual Quick Start in README (`pip install`, `doctor`, basic conversion)
- [x] `examples/` directory with a walkthrough for new users
- [x] `ROADMAP.md` (this file)
- [x] Improve `mathfmt doctor` output — show versions of key dependencies
- [x] Release audit found no open crash or `bug` issues; edge-input regression suite passes
- [x] Expand test coverage for boundary cases (empty runs, malformed XML, Unicode edge cases)
- [x] Triage issues labeled `bug` on GitHub (none open at the 2026-08-08 audit)

## v0.3.0 — Conversion Reports & Safety · 转换报告与安全

**Focus:** Give users confidence in automated conversion and visibility into what changed.

### Planned implementation order

1. **Report schema first** — stabilize the JSON fields so `apply`, `convert`,
   `validate`, and future docs can point to one consistent structure.
2. **Dry-run second** — reuse the same report schema, but guarantee the source
   DOCX and output path are not modified.
3. **Safety flags third** — add strict failure behavior and clearer parse hints
   once reporting has a stable place to surface them.
4. **Docs and examples last** — update the workflow guide and example walkthrough
   only after the CLI behavior is covered by tests.

### Feature backlog

- [x] **Conversion report** — after `apply`, generate a structured JSON report plus
  an optional human-readable summary showing:
  - source document, output document, and command options
  - each selected candidate, its paragraph/run location, original text, normalized
    formula, confidence, and conversion status
  - warnings for skipped or failed formulas
  - aggregate counts: scanned, selected, converted, skipped, failed, warnings
- [x] **Dry-run mode** — `mathfmt apply --dry-run` previews the same changes and
  report data without writing a DOCX.
- [x] **Failed-formula warnings** — selected formulas that fail or are skipped are
  flagged in `formulas[].warnings` so users know to review them manually.
- [x] **Per-formula confidence in reports** — include individual confidence scores
  alongside each converted formula, not just aggregate stats.
- [x] **Better error messages** — when parsing fails, show _where_ in the formula
  the parser got stuck (column number, nearby text, expected token when known).
- [x] **`--strict` flag** — fail on any parse/conversion warning instead of silently
  skipping, useful for CI pipelines.

### Acceptance criteria

- `mathfmt apply --dry-run input.docx --review candidates.json --report result.json`
  exits successfully, writes `result.json`, and leaves all DOCX files unchanged.
- `mathfmt apply ... --report result.json` and `mathfmt convert ... --report result.json`
  use the same top-level report schema.
- Reports are deterministic enough for regression tests: stable keys, stable counts,
  and no absolute temporary paths unless explicitly requested.
- Strict mode returns a non-zero exit code when any selected formula fails or emits
  a warning that requires manual review.
- Unit tests and acceptance tests cover success, skipped formula, parse failure,
  failed-formula warning, dry-run, and strict-mode failure paths.
- Documentation includes one minimal quick example and one production review-flow
  example.

## v0.4.0 — Formula Coverage · 公式覆盖 (released 2026-08-06)

**Focus:** Handle more real-world formula patterns.

- [x] LaTeX-style explicit delimiters: `$...$` and `$$...$$` in DOCX text
- [x] Nested bracketed constructs: `{ ... }` for explicit grouping
- [x] Multi-line equations and aligned environments (`a = b \\ c = d`)
- [x] Piecewise and `cases` environments
- [x] Chemical formulas and reaction arrows
- [x] Physics notation: bra-ket `⟨φ|ψ⟩`, tensor indices, partial derivatives `∂f/∂x`
- [x] Improved Unicode symbol mapping for common number sets and relation/set operators
- [x] User-extensible symbol aliases (e.g. custom shorthand → MathML)

## v0.5.0 — Compatibility & Integration · 兼容性与集成 (released 2026-08-07)

**Focus:** Work well in more environments and toolchains.

- [x] WPS Writer 12 Windows round-trip save, PDF visual QA, and reusable automation script
- [x] Cross-platform offline WPS compatibility profile (`validate --compatibility wps`)
- [x] Linux portability covered by the offline WPS profile and native LibreOffice CI;
  proprietary Linux WPS rendering is outside the supported automated target set
- [x] LibreOffice Writer compatibility testing and PDF render smoke test
- [x] Batch processing: `mathfmt convert ./folder/*.docx`
- [x] GitHub Actions render recipe for CI integration

## v1.0.0 — Stable API · 稳定 API (released 2026-08-08)

**Focus:** Lock down the public API and establish long-term support.

- [x] Stable Python API with signature snapshot tests and a deprecation policy
- [x] Semantic versioning and report compatibility guarantees documented
- [x] Typed plugin/hook system for custom formula recognizers in Python and the CLI
- [x] 100-page/800-formula benchmark, CI gate, and per-part XML performance optimization

MathFmt's core conversion pipeline (parser, OMML backends, CLI, reports, plugin API)
was feature-complete at v1.0 and remains in stable maintenance mode: no changes to
supported syntax or the documented API are planned. Small, backward-compatible
usability additions that don't touch that surface — like the v1.1 GUI below — may
still land when there's a clear, demonstrated need; otherwise future changes are
limited to necessary security and compatibility maintenance.

## v1.1.0 — Local GUI · 本地图形界面 (released 2026-08-31)

**Focus:** Lower the barrier for users who don't want to use the terminal.

- [x] `mathfmt gui`: a local, stdlib-only browser drag-and-drop interface bound to
  `127.0.0.1`, running the same conservative convert pipeline. No new runtime
  dependency; no change to the stable Python API or CLI commands added in v1.0.

## v1.2.0 — GUI Review & Reverse Conversion · GUI 审核与反向转换 (released 2026-09-03)

**Focus:** Make the GUI safer to use unsupervised, give clearer feedback on parse
failures, and close the OMML → text gap for tooling built on top of MathFmt.

- [x] `mathfmt gui` shows every scanned candidate as a checklist (source text,
  confidence, parse status/reason) before converting, pre-checked with the same
  conservative defaults as `mathfmt convert`.
- [x] `FormulaError.to_dict()` includes a plain-language `hint` for common
  mistakes — mismatched brackets, a `cases`/`{...}` branch missing `if`, wrong
  argument counts — surfaced in scan/apply reports and the GUI's candidate list.
- [x] `omml_to_text(omath_elem)`: the reverse of `mathml_to_omml_py`, converting a
  native OMML equation back to MathFmt's linear formula syntax.
- [x] `packaging/build_exe.py`: an optional standalone GUI executable build for
  people without Python installed, smoke-tested in CI on every push. Building and
  distributing it remains a manual, deliberate step outside the release pipeline.

All additions are backward-compatible per `docs/api.md`; no change to the stable
Python API or CLI commands added through v1.1.

---

## Maintenance Feedback · 维护反馈

- **Bug and compatibility reports** should include a minimal DOCX, the JSON report,
  and `mathfmt doctor` output whenever possible.
- **Security reports** follow the private process in `SECURITY.md` rather than public
  issues.
- **Feature requests** may be discussed, but stable maintenance does not imply a
  commitment to another feature release.
- **Pull requests** are welcome for confirmed defects; open an issue first for any
  change that could affect supported syntax or the stable API.

## Versioning Policy · 版本策略

MathFmt follows [Semantic Versioning 2.0](https://semver.org/):

- **Patch** (1.0.x): necessary defect, security, documentation, and compatibility
  fixes without supported-behavior changes
- **Minor** (1.x.0): backward-compatible additions only when required by a supported
  platform or a demonstrated maintenance need
- **Major** (2.0.0): incompatible API or report changes; no major release is planned

Throughout 1.x, the exported API, documented CLI behavior, and report-field meanings
remain compatible under the guarantees in `docs/api.md`.
