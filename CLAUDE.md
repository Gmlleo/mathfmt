# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# MathFmt — Project Reference for Claude Code

> Typeset plain-text formulas in DOCX files as native Word OMML equations — cross-platform, no Office required.

## Overview

MathFmt is a Python CLI tool & library that converts plain-text math formulas (e.g. `x^2+1`, `sqrt(a/b)`, `lim(x->0)`) embedded in `.docx` files into native Office Math Markup Language (OMML) equations. Designed for textbooks, exams, and technical reports.

- **Author:** Leo (gml853503962@gmail.com)
- **Version:** 1.4.0 (see `src/mathfmt/_version.py`)
- **License:** MIT
- **Repo:** https://github.com/Gmlleo/mathfmt
- **Python:** 3.10–3.14 (pure Python, no native extensions)
- **Sole runtime dependency:** `lxml >= 5.0`
- **Dev dependencies:** `build`, `pytest`, `pytest-cov`, `ruff`

---

## Directory Structure

```
MathFmt/
├── src/mathfmt/           # Package source
│   ├── __init__.py        # Stable public API exports (18 symbols)
│   ├── _version.py        # Single version source: "1.1.0"
│   ├── __main__.py        # `python -m mathfmt` entry point
│   ├── cli.py             # argparse CLI: 7 subcommands (~590 lines)
│   ├── gui.py              # mathfmt gui: stdlib-only local server + the whole page (~1000 lines)
│   ├── aliases.py         # Validated user symbol-alias profiles
│   ├── accents.py         # The accent kinds, in every representation they need
│   ├── nary.py            # The n-ary big operators, in every representation they need
│   ├── core.py            # Formula parser, scanner, and conversion pipeline (~2500 lines — the engine)
│   ├── docxio.py          # Bounded ZIP I/O and hardened OOXML parsing
│   ├── latex.py           # LaTeX input subset → linear syntax (pure text-to-text)
│   ├── omml.py            # Pure-Python MathML→OMML converter
│   ├── plugins.py         # Stable custom-recognizer extension API
│   ├── update.py          # Self-update checker (GitHub Releases API)
│   └── validate.py        # Multi-layer DOCX/OMML validator (~500 lines)
├── tests/                 # pytest unit and acceptance suite
│   ├── helpers.py         # Synthetic DOCX builder, fake XSL, OMML template
│   ├── fixtures/          # Static test fixtures
│   ├── acceptance/        # gen_docs.py: builds versioned acceptance documents (doc01…doc07)
│   ├── test_acceptance.py, test_aliases.py, test_benchmark.py, test_cli.py,
│   │   test_core.py, test_docx.py, test_docxio.py, test_formula.py, test_gui.py,
│   │   test_latex.py, test_omml.py, test_plugins.py, test_public_api.py,
│   │   test_skill.py,
│   │   test_update.py, test_validate.py
├── docs/
│   ├── formula-syntax.md  # Complete grammar reference, preprocessing, MathML mapping
│   ├── workflow.md        # Install, scan/review/apply cycle, CI usage, troubleshooting
│   ├── api.md              # 1.x stability and deprecation contract
│   ├── plugins.md         # Custom recognizer protocol and CLI loading
│   └── performance.md     # 100-page benchmark and CI gate
├── benchmarks/             # Reproducible large-DOCX performance workload
├── skills/mathfmt/         # Claude Code skill
│   ├── SKILL.md            # Skill workflow instructions
│   ├── agents/openai.yaml  # Agent interface
│   └── references/paper-notation.md  # Design conventions
├── examples/
│   └── README.md           # New-user walkthrough: test doc → scan → apply
├── ROADMAP.md               # Release history and stable-maintenance status
├── .github/workflows/
│   ├── ci.yml               # CI: 9-version matrix + package/performance/render jobs
│   └── publish.yml          # CD: tag → PyPI + GitHub Release
├── .claude/
│   ├── memory.md            # Project lessons learned (accumulated, see below)
│   └── settings.local.json
├── pyproject.toml           # Build config, metadata, tool settings
├── CHANGELOG.md
├── CONTRIBUTING.md
└── README.md                 # Bilingual (zh/en) overview
```

---

## Architecture — Module Responsibilities

### `core.py` — The engine
The heart of the project. Data flow:
1. **Preprocessing** — derivative normalization (`ds/dt` → Leibniz form), Unicode sub/superscript → ASCII, operator aliases
2. **Tokenization** — regex-based lexer. Grammar keywords that separate two expressions (e.g. `if` in `cases(...)` syntax) must be tokenized *before* the generic identifier rule, or implicit multiplication silently consumes them and swallows branch-level parse errors.
3. **Parsing** — recursive-descent parser following the BNF grammar (see `docs/formula-syntax.md`)
4. **AST → MathML** — tree walker builds `<math>` element tree
5. **DOCX injection** — finds text runs matching formula spans, replaces with OMML markup, handles table and multi-line/eqArr splitting

A scan report distinguishes the original matched `source` text from the parser-ready `linear` text (delimiters like `$…$` stripped, etc.). `apply`, `validate`, and cross-backend checks must all parse `linear`, not `source` — otherwise formulas that convert successfully can still fail validation. When one reviewed candidate expands to multiple parse units (e.g. multi-line aligned formulas), split it consistently across scan, apply, and validation; keep coverage counts candidate-based and assemble the final layout only during apply.

Key functions exported via `__init__.py`:
- `scan_docx(input_path, report_path)` → writes JSON report, returns stats dict
- `apply_docx(input_path, review_path, output_path, result_path, xsl_path=None)` → writes formatted DOCX + result JSON
- `formula_to_mathml(source)` → parse single formula → MathML element
- `mathml_to_omml(math, transform=None)` → convert MathML → OMML (auto-selects backend)
- `find_xsl(explicit=None)` → locate Office MML2OMML.XSL if available
- `validate_docx(...)` → validate structure, formula coverage, and compatibility
- `FormulaRecognizer` / `FormulaCandidate` → typed custom candidate detection

### `latex.py` — LaTeX input subset expander

A pure text-to-text transform (no lxml, no MathML): the documented LaTeX subset
becomes MathFmt's linear syntax before parsing. Anything outside the subset raises
`FormulaError` naming the macro rather than being guessed at. Five passes, in a
load-bearing order — environments, argument macros, scripts, limit binding, symbols
— documented on `expand_latex`.

`core` imports it from *inside* `formula_to_mathml`, not at module scope, because
`latex` imports `core` for its error type; a module-scope import would close the cycle.

Two questions with different jobs, and they must not be swapped: `contains_latex_macro`
("is this LaTeX I can handle?") gates *discovery*, where a false positive offers a
candidate that can never convert; `looks_like_latex` ("is this LaTeX at all?") gates
*expansion* of a formula already chosen, so an unsupported macro is named rather than
reaching the tokenizer as an unrecognized backslash.

### `accents.py` / `nary.py` — Shared symbol tables

One row per accent kind / big operator, so the linear name, the MathML character, and
the OMML/Word mark cannot drift apart. Both exist because the correspondence previously
lived in three independent tables and a row added to one but not the others produced
output the reverse converter then refused to read. Adding a row teaches every direction
at once. `nary.py` also holds the two n-ary defaults, deliberately under different
names and different characters: `FALLBACK_NARY_CHAR` is what the writer emits for an
unknown name, `OMML_IMPLIED_NARY_CHAR` is what ISO/IEC 29500 says an absent `m:naryPr`
means.

### `omml.py` — Built-in MathML→OMML converter
Pure Python, no Office required. Cross-platform default backend. Key function:
- `mathml_to_omml_py(mathml_elem)` → OMML element tree

A literal `&` inside an OMML `m:eqArr` acts as a Word alignment marker but renders visibly in other applications (e.g. LibreOffice). For cross-application relation alignment, a two-column native `m:m` (right-justified left column, left-justified relation column) is used instead; `m:eqArr` remains only the no-common-relation fallback.

### `cli.py` — Command-line interface
Seven subcommands via `argparse`:
| Command | Purpose |
|---|---|
| `mathfmt scan` | Scan DOCX for formulas → JSON report |
| `mathfmt apply` | Apply reviewed candidates → output DOCX |
| `mathfmt convert` | One-step conservative conversion (scan + apply high-confidence only) |
| `mathfmt gui` | Local browser drag-and-drop UI over the same convert pipeline (see `gui.py` below) |
| `mathfmt validate` | Multi-layer offline validation (`--compatibility wps` selects the WPS lint; there is no `--wps` shorthand) |
| `mathfmt doctor` | Environment diagnostics |
| `mathfmt update` | Check for newer version on GitHub |

Library functions return structured results; the CLI translates them to exit codes. When adding an error field to a library result, also add a CLI exit-code test for that path — displaying an error message while the process still exits 0 breaks CI callers silently.

### `gui.py` — Local browser server *and* the entire front end

`mathfmt gui` starts a plain-stdlib `http.server` bound to `127.0.0.1` and serves one
self-contained page. Both halves live in this one file: the request handler, and
`PAGE_HTML` — the HTML, CSS and JavaScript as a single f-string.

Routes: `POST /scan` (upload → candidates), `POST /preview/<token>` (one formula →
MathML), `POST /apply/<token>` (convert the reviewed selection), `GET /download|/report`.
Each upload gets a private temp directory; a `_SessionStore` token maps to it and sweeps
after a TTL. A token is only ever issued by `/scan`, which is what keeps `/preview` from
being an open formula compiler on localhost.

The review loop, and the invariants that hold it together:

- `/scan` sends each candidate's `linear` (parser-ready) **and** `mathml`. Anything that
  previews or converts parses `linear`, never `source` — `source` still carries its
  `$…$` delimiters.
- `/preview` answers **200** with `{ok: false, error, hint}` for a formula that does not
  parse. That is a normal answer to a valid request; 4xx is reserved for an expired
  session or an over-cap body.
- `/apply` accepts `{"selected", "linear"}` or a bare boolean (the pre-v1.4 shape). An
  edited `linear` is written into `candidates.json` and re-parsed by `apply_docx`, so a
  bad edit lands in `skipped` rather than in the document. Never trust the client's
  preview.

**Two traps when editing this file:**

1. **MathML must enter the DOM through `DOMParser` + `importNode`, never `innerHTML`.**
   Every other value the page inserts goes through `escapeHtml`; MathML is the only one
   that must stay markup. Parsing it as XML keeps server-supplied document text away
   from the HTML parser entirely. A test in `test_gui.py` guards this.
2. **`PAGE_HTML` is an f-string.** Every literal JS/CSS brace must be doubled (`{{`,
   `}}`), and every backslash the JavaScript needs must be written doubled in the Python
   source (`/\\s+/g` to get `/\s+/g`). A single `\f`/`\b`/`\n` there silently becomes a
   control character in the served page.

`BaseHTTPRequestHandler.send_error`'s `message` becomes the HTTP status line and must stay
ASCII (latin-1 encoded by the stdlib) — pass non-ASCII detail via `explain=`. The JSON
helpers here (`_json_error`/`_json_response`) put everything in the body, so they are not
subject to that; do not reach for `send_error` in a new route.

### `validate.py` — Validator
Five validation layers:
1. ZIP package integrity
2. OMML structural checks
3. Formula coverage analysis
4. Cross-backend comparison (Python vs Office XSL)
5. Optional WPS portability lint

### `update.py` — Self-update checker
- Polls GitHub Releases API
- SemVer 2.0 parsing
- 1-hour response caching. Caches for option-sensitive checks (e.g. stable-only vs. prerelease) must include the option in the cache key, and decoded cache JSON must be validated as a mapping with usable value types before calling mapping methods on it.

---

## Development Commands

All commands run from the project root (`C:\Users\gml85\Desktop\个人\MathFmt`).

```powershell
# Install in editable mode with dev deps — REQUIRED before running tests or the CLI locally.
# Without -e, `python -c "import mathfmt"` / a bare `mathfmt` on PATH can silently resolve to a
# stale, non-editable version already present in site-packages instead of this checkout.
pip install -e ".[dev]"

# Run the full test suite (coverage threshold: 85%, matches CI)
pytest -m "not native_xsl"

# Run a single test file / test
pytest tests/test_core.py
pytest tests/test_core.py::test_specific_case -v

# Lint + format check (both run in CI; run both before tagging a release)
ruff check .
ruff format --check .

# Build distribution
python -m build

# Run CLI locally (editable install)
mathfmt doctor
mathfmt convert input.docx --output output.docx
```

**Pytest notes:**
- Markers: `native_xsl` tests require Microsoft Office — CI runs them only on Windows; skip locally on non-Windows or non-Office machines (`pytest -m "not native_xsl"`).
- Coverage: branch coverage, 85% threshold enforced by `pyproject.toml` `addopts`, HTML report in `htmlcov/`. A targeted/single-file run still inherits this repo-wide threshold and can exit nonzero on coverage alone even when every selected test passes — use the full suite for release validation, and don't mistake a subset-coverage failure for a product defect.
- If `WinError 5` on Windows, use a fresh, uniquely named `--basetemp` (a fixed one can become undeletable after an interrupted/sandboxed run).
- A nested `--basetemp=".pytest_tmp/run1"` fails with `WinError 3` (~130 setup errors, no product defect) unless the **parent** already exists: `mkdir -p .pytest_tmp` first, or pass a top-level path. `.pytest_tmp/` is the gitignored name.
- Acceptance/render documents are generated via `tests/acceptance/gen_docs.py`; only `all_docs()` auto-creates its `OUT` directory — redirecting `gen_docs.OUT` to call a single document factory directly requires creating that directory first.

---

## Coding Conventions

- **Line length:** 110 (configured in `pyproject.toml` `[tool.ruff]`)
- **Linter:** ruff with rules `F` (Pyflakes), `I` (isort), `UP` (pyupgrade), plus `ruff format --check`. Pinned to one minor series (`ruff>=0.16,<0.17`) because its pre-1.0 formatter can change stable style in any `0.x.0` — 0.16.0 started formatting Python blocks inside Markdown and broke CI on nine platforms with no code change. Markdown is excluded (`[tool.ruff] extend-exclude`): the docs quote *fragments*, and formatting each fence as a standalone module strips the indentation that shows where the excerpt belongs. Raising the pin is deliberate work: read ruff's changelog, run `ruff format` once, commit the result.
- **Imports:** `from __future__ import annotations` at top of each module
- **Typing:** type hints used throughout, `collections.abc.Sequence` not `typing.Sequence`
- **Docstrings:** Google-style or concise single-line
- **Error handling:** library functions return structured results; CLI translates to exit codes (both must be correct — see `core.py`/`cli.py` note above)
- **No `if __name__ == "__main__":`** in library code (excluded from coverage)
- **Package layout:** `src/` layout with `pyproject.toml` `[tool.setuptools.package-dir] = {"" = "src"}`

---

## Two OMML Backends

1. **Built-in Python** (`omml.py`) — cross-platform, no dependencies beyond lxml. Always available.
2. **Microsoft Office XSL** — used automatically when present.

**The CLI auto-detects the XSL and prefers it.** Every OMML-producing command handler in
`cli.py` (`doctor`, `convert`, `apply`, `validate` — grep `find_xsl(`) calls `find_xsl()`
when `--xsl` is not given and falls back to the Python backend only on
`FileNotFoundError`. So on a machine with Office installed, the default output comes from
Microsoft's XSL, not from `omml.py`. There is no flag that forces the Python backend.

This matters when working on `omml.py`: a change there will not show up in a local `mathfmt convert` on a Windows machine with Office. Exercise the Python backend directly through `mathml_to_omml_py`, or via `mathml_to_omml(math, transform=None)`.

The **library** default is the opposite of the CLI's: `mathml_to_omml` uses the Python backend unless the caller passes a `transform`.

When available, the Office XSL backend generally produces output closer to Word's native equation editor. The Python backend works everywhere and is what non-Windows users, CI, and machines without Office actually get.

---

## CI/CD

- **CI** (`.github/workflows/ci.yml`): Triggers on push/PR. Runs `ruff check .` and `ruff format --check .`, then tests Windows 3.10–3.14 plus Ubuntu/macOS 3.10 and 3.14 (`native_xsl` tests only on Windows), then runs `package`, 100-page `performance`, and `libreoffice-render` gates.
- **CD** (`.github/workflows/publish.yml`): Triggers on tag push `v*`. Builds → publishes to PyPI via Trusted Publishing → creates GitHub Release. After publishing, verify the PyPI wheel's SHA-256 matches the GitHub Release asset digest.

**Releasing** (the established flow — a PyPI version can never be replaced, so nothing here is undoable):
1. Bump `_version.py`; date the `[Unreleased]` CHANGELOG section; add a `ROADMAP.md` entry; update the README status line and both version tables.
2. **Bump the "newer release" fixtures in `tests/test_update.py` past the new version.** They are normally set one minor ahead, so they collide with exactly the release that catches up to them — update detection then correctly reports "no update" and the tests fail.
3. Full gate on the release branch: `ruff check .`, `ruff format --check .`, `pytest -m "not native_xsl"`, `python -m build`.
4. PR → merge to `main` → annotated tag on `main` → `git push origin vX.Y.Z`.
5. Verify: `publish.yml`'s three jobs green, PyPI and GitHub Release digests equal, then install the published version in a clean venv and convert a document. A first `pip install` may report the version missing while the JSON API already serves it — that is PyPI's simple-index propagation lag, not a failed publish; retry.

---

## Key Project Knowledge

`.claude/memory.md` accumulates specific lessons learned during development (Windows tooling quirks, release/QA procedures, OOXML edge cases, etc.) — read it directly for the full, current list. A few of the most broadly relevant ones are folded into the sections above (formula `source` vs. `linear`, grammar keyword tokenization order, `m:eqArr` vs. native `m:m` alignment, pytest coverage/basetemp behavior, CLI exit codes). Consult the file itself rather than relying on any static summary here, since it grows with the project.

---

## Related Files

- Formula syntax reference: `docs/formula-syntax.md` (§10 is the supported LaTeX subset and its limitations)
- 1.x API stability contract: `docs/api.md`
- User workflow guide: `docs/workflow.md`
- Design specs and TDD implementation plans: `docs/superpowers/specs/`, `docs/superpowers/plans/` — each plan records the deviations taken during implementation and why, so read the plan alongside the code it produced
- Examples walkthrough: `examples/README.md`
- Project roadmap: `ROADMAP.md`
- Design conventions: `skills/mathfmt/references/paper-notation.md`
- Claude Code skill: `skills/mathfmt/SKILL.md`
- Changelog: `CHANGELOG.md`
- Lessons learned: `.claude/memory.md`
