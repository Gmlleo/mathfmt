# Workflow Guide

How to use MathFmt from installation to a finished document.

---

## 1. Install and Verify

```powershell
pip install mathfmt
mathfmt doctor
```

`doctor` checks:

- Python version
- Platform
- `lxml` availability
- OMML backend: built-in Python (always available) or Office XSL (auto-detected)

All platforms are ready out of the box. On Windows, `doctor` will indicate when it
finds Microsoft Office and prefers its XSL backend.

If you need to point to a specific XSL file:

```powershell
mathfmt doctor --xsl "C:\path\to\MML2OMML.XSL"
```

All commands that produce OMML (`apply`, `convert`) accept `--xsl` to override backend selection.

---

## 2. GUI: Drag-and-Drop (Fastest)

For a single document, or if you would rather not touch a terminal command beyond
launching it:

```powershell
mathfmt gui
```

This starts a local server bound to `127.0.0.1` and opens the page in your default
browser. Drag a `.docx` onto the drop zone (or click it to choose a file), pick a
confidence level if you want something other than the conservative default, and
download the converted document plus its JSON scan report from the page. Nothing is
uploaded anywhere — the server only listens on localhost, and each upload is
processed in a private temporary directory that is cleaned up automatically. Press
Ctrl+C in the terminal to stop the server.

`mathfmt gui` mirrors `mathfmt convert`'s conservative one-step pipeline (see
section 4 below). For batch processing, custom aliases, custom recognizers, or the
full review-before-apply workflow, use the CLI commands in the rest of this guide.

---

## 3. Review-First Workflow (Recommended)

For documents with mixed technical prose, code, images, and formulas:

### Step 1 — Scan

```powershell
mathfmt scan document.docx --report candidates.json
```

To use custom symbols, pass a JSON alias profile:

```json
{
  "name": "engineering",
  "aliases": {
    "ohm": "Ω",
    "mapsTo": "↦"
  }
}
```

```powershell
mathfmt scan document.docx --report candidates.json --aliases symbols.json
```

The report records the profile name, resolved path, alias count, and SHA-256 digest.
Alias values must be one Unicode mathematical symbol. Parser keywords and core
operators cannot be overridden.

This produces `candidates.json` containing every detected formula candidate:

```json
{
  "schema_version": 2,
  "input": "C:\\path\\to\\document.docx",
  "profile": {
    "derivatives": "fraction",
    "unit_step": "u(t)",
    "output": "native_word_omml",
    "aliases": null
  },
  "summary": {
    "paragraphs": 42,
    "candidates": 15,
    "existing_equations": 3,
    "drawing_paragraphs": 2,
    "code_paragraphs": 8
  },
  "candidates": [
    {
      "id": "f0001",
      "selected": true,
      "part": "word/document.xml",
      "paragraph_index": 3,
      "start": 10,
      "end": 20,
      "source": "x^2 + 1 = 2",
      "linear": "x^2 + 1 = 2",
      "display": false,
      "explicit": false,
      "multiline": false,
      "line_count": 1,
      "paragraph_text": "Inline: x^2 + 1 = 2 and more text.",
      "parse_status": "ok"
    }
  ]
}
```

If a formula is wrapped in LaTeX-style delimiters, the report keeps the exact DOCX
text in `source` and strips the delimiters in `linear`:

```json
{
  "source": "$x^2 + 1$",
  "linear": "x^2 + 1",
  "confidence": "high",
  "confidence_reason": "explicit LaTeX delimiter",
  "explicit": true
}
```

To create an aligned multiline equation, edit `linear` during review while keeping
`source` and its character span unchanged:

```json
{
  "source": "a = b",
  "linear": "a = b \\\\ c = d",
  "multiline": true,
  "line_count": 2
}
```

An actual line break may be used instead of `\\`. Each line must be a valid formula.

### Step 2 — Review

Open `candidates.json` and for each candidate:

| Field | What to check |
|---|---|
| `source` | The original text from the DOCX |
| `linear` | The formula string that will be parsed (edit this to fix notation, e.g. change `p1,2` to `p1, p2` if you prefer comma-separated subscripts) |
| `selected` | Set to `true` to convert, `false` to skip |
| `parse_status` | `"ok"` = parsable; `"review"` = failed, check `parse_error` |
| `parse_error_details` | Structured parse location: column, nearby context, expected token, and found token when available |
| `explicit` | `true` when detected from `$...$` or `$$...$$` delimiters |
| `chemistry` | `true` when the conservative chemistry parser recognized the candidate |
| `chemistry_kind` | `"formula"`, `"reaction"`, or `null` |
| `physics` | `true` when supported partial, tensor, or bra-ket notation was recognized |
| `physics_kind` | `"partial_derivative"`, `"tensor"`, `"braket"`, or `null` |
| `multiline` | `true` when `linear` contains two or more reviewed formula lines |
| `line_count` | Number of reviewed formula lines |

Common review actions:

- **False positive** (prose misidentified as formula): set `"selected": false`.
- **Notation fix**: edit the `linear` field. For example, if the source is `s'(t) + s''(t)` and you want both derivatives, keep it as-is. If you want only first-order, shorten it.
- **Parse failure**: read `parse_error` and `parse_error_details`, adjust `linear`,
  re-run `scan` to verify.

### Step 3 — Apply

```powershell
mathfmt apply document.docx --review candidates.json --output result.docx --report result.json
```

If `scan` used aliases, pass the same profile to `apply`:

```powershell
mathfmt apply document.docx --review candidates.json --output result.docx --report result.json --aliases symbols.json
```

MathFmt rejects a missing or changed profile before writing output, so reviewed
notation cannot silently acquire different symbol meanings.

To preview the same conversions without writing a DOCX:

```powershell
mathfmt apply document.docx --review candidates.json --report preview.json --dry-run
```

For stricter production runs, use `--strict`. If any selected formula fails or is skipped,
MathFmt writes the report but does not write the output DOCX:

```powershell
mathfmt apply document.docx --review candidates.json --output result.docx --report result.json --strict
```

Normal apply writes `result.docx` with native Word equations and `result.json` with conversion statistics:

```json
{
  "schema_version": 3,
  "report_type": "conversion",
  "command": {"name": "apply"},
  "options": {"backend": "python", "dry_run": false, "strict": false},
  "summary": {
    "selected": 15,
    "converted": 12,
    "skipped": 3,
    "failed": 3,
    "warnings": 0,
    "dry_run": false,
    "output_written": true,
    "strict_failed": false
  },
  "converted_count": 12,
  "skipped_count": 3,
  "formulas": [
    {
      "id": "f0001",
      "status": "converted",
      "source": "x^2 + 1 = 2",
      "linear": "x^2 + 1 = 2",
      "confidence": "high",
      "lines": 1,
      "multiline": false,
      "layout": "single",
      "location": {"part": "word/document.xml", "paragraph_index": 3, "start": 10, "end": 20}
    }
  ],
  "converted": [
    {"id": "f0001", "source": "x^2 + 1 = 2", "part": "word/document.xml", "lines": 1}
  ],
  "skipped": [
    {"id": "f0005", "source": "…", "error": "Reviewed source no longer matches the paragraph span"}
  ]
}
```

Check `skipped` entries for errors. A non-zero skip count produces exit code 2.

### Step 4 — Verify

Open `result.docx` in Word and inspect:
- Each converted formula renders as a native equation
- Surrounding text is intact
- Tables, headers, and footers are correct
- Code blocks remain as plain text

---

## 4. One-Step Conversion

For documents where most candidates are likely formulas (e.g., all-math problem sets):

```powershell
mathfmt convert input.docx
```

This runs `scan` + `apply` internally, producing:

- `input.mathfmt.docx` — the converted document
- `input.mathfmt.report.json` — the conversion report

Custom output paths:

```powershell
mathfmt convert input.docx --output final.docx --report conversion.json
```

One-step conversion also accepts aliases and automatically uses the same profile
for its internal scan and apply phases:

```powershell
mathfmt convert input.docx --output final.docx --report conversion.json --aliases symbols.json
```

**Important**: `convert` uses default `selected: true` for all parseable candidates. It does not apply human judgment. If your document has prose that resembles formulas, use `scan` + `apply` instead.

**Safety**: `convert` never overwrites the input file. The output name always differs from the input name.

### Batch conversion

Pass multiple files, a quoted glob, or a directory to convert a batch. Quoting the glob
keeps behavior consistent between PowerShell, Command Prompt, and POSIX shells:

```powershell
mathfmt convert "notes/*.docx" `
  --output-dir converted `
  --report-dir reports `
  --batch-report batch.json

# Search all nested directories. Existing *.mathfmt.docx files found through a
# directory scan are skipped so generated outputs are not processed again.
mathfmt convert notes --recursive --output-dir converted --batch-report batch.json
```

Batch processing is deterministic and de-duplicates repeated inputs. It validates the
complete output plan before writing anything, refuses output-name collisions, and never
uses `--output` or `--report` for a batch; use their directory variants instead. A bad
DOCX is recorded as a failed item while the remaining files continue. The aggregate
report contains per-file input, output, report, status, exit code, and formula counts.

Batch exit codes:

- `0` — every file converted without skipped formulas
- `1` — at least one file failed or strict conversion failed
- `2` — no file failed, but at least one file completed with skipped formulas

---

## 5. Understanding the Report

### Scan report (`candidates.json`)

| Field | Meaning |
|---|---|
| `summary.paragraphs` | Total paragraphs scanned |
| `summary.candidates` | Formulas found |
| `summary.existing_equations` | Paragraphs that already contain native Word equations (skipped) |
| `summary.drawing_paragraphs` | Paragraphs containing images or drawings (skipped) |
| `summary.code_paragraphs` | Paragraphs identified as code (skipped) |
| `profile.aliases` | Alias profile name, resolved path, SHA-256 digest, and symbol count, or `null` |
| `profile.recognizers` | Ordered custom-recognizer names, modules, versions, and CLI specs |
| `candidates[].source` | Original DOCX text span; explicit formulas keep `$...$` or `$$...$$` here |
| `candidates[].linear` | Parsed formula text; explicit formulas remove the delimiters here |
| `candidates[].display` | `true` if the formula fills the entire paragraph (renders as display equation) |
| `candidates[].explicit` | `true` when the candidate came from LaTeX-style delimiters |
| `candidates[].multiline` | Whether `linear` contains multiple reviewed formula lines |
| `candidates[].line_count` | Number of reviewed formula lines |
| `candidates[].parse_status` | `"ok"` or `"review"` (see above) |
| `candidates[].recognizer` | Custom recognizer name, or `null` for built-in detection |
| `candidates[].recognizer_kind` | Optional plugin-defined candidate category |

### Apply report (`result.json`)

| Field | Meaning |
|---|---|
| `schema_version` | Report schema version (`3` for conversion/validation reports) |
| `report_type` | `"conversion"` for `apply` and `convert` |
| `command.name` | `"apply"` or `"convert"` |
| `options.dry_run` | `true` when previewing without writing DOCX output |
| `options.strict` | `true` when failures prevent DOCX output |
| `inputs.aliases` | Resolved alias profile path, or `null` |
| `options.alias_profile` | Alias profile metadata used for conversion, or `null` |
| `options.recognizers` | Recognizer provenance copied from the scan report |
| `summary.output_written` | Whether a DOCX output file was written |
| `summary.strict_failed` | Whether strict mode blocked DOCX output |
| `formulas[].status` | Per-formula result: `"converted"`, `"skipped"`, or `"failed"` |
| `formulas[].location` | DOCX part, paragraph index, and character span |
| `formulas[].confidence` | Per-formula confidence copied from the review report |
| `formulas[].lines` | Number of converted formula lines |
| `formulas[].multiline` | Whether the converted formula contains multiple lines |
| `formulas[].layout` | `"single"`, `"equation_array"`, or legacy table `"line_breaks"` |
| `formulas[].warnings` | Manual-review warnings such as failed conversion or stale location |
| `formulas[].error_details` | Structured parser details such as column, context, expected token, and found token |
| `converted_count` | Formulas successfully converted |
| `skipped_count` | Formulas that could not be converted |
| `converted[].lines` | Number of equation lines (1 normally; >1 for aligned or split table formulas) |
| `skipped[].error` | Reason for skipping |

The legacy `converted_count`, `skipped_count`, `converted`, and `skipped` fields remain
for compatibility. New automation should prefer `summary` and `formulas`.

---

## 6. Validating Output

Use `mathfmt validate` to check DOCX correctness without opening Word:

```powershell
mathfmt validate output.docx --report validation.json
```

For WPS Writer portability checks, add the compatibility profile:

```powershell
mathfmt validate output.docx --compatibility wps --report validation-wps.json
```

The WPS profile rejects visible Word-only equation alignment markers, Word-only
alignment controls, and embedded objects inside equation paragraphs. It also reports
relation-less equation arrays that deserve a visual check.

The repository CI also generates the comprehensive notation acceptance document, converts it with the
built-in backend, renders it through LibreOffice, and checks the resulting PDF for
visible Word-only alignment markers. This complements structural validation with a
repeatable cross-application rendering smoke test.

When validating formula coverage from a review created with aliases, pass the same
profile:

```powershell
mathfmt validate output.docx --review candidates.json --report validation.json --aliases symbols.json
```

It performs four checks:

| Layer | What | Detects |
|---|---|---|
| Package | ZIP validity, required XML parts | Corrupt files, missing parts |
| OMML structure | Equation count, child checks, nesting depth | Empty equations, broken fractions, missing script parts |
| Coverage | Formula parse & OMML round-trip (requires `--review`) | Unparseable sources, OMML generation failures |
| Cross-backend | Python vs XSL element count (requires `--xsl`) | Structural divergence between backends |
| Compatibility | Portable OMML checks (requires `--compatibility wps`) | Constructs known to render inconsistently in WPS/non-Word suites |

Exit codes:
- `0` — all checks passed
- `1` — issues found (see report)
- `2` — input is unreadable or not a DOCX

### Native WPS Writer round-trip (Windows)

When WPS Writer is installed, the repository script opens a DOCX through the hidden
`KWps.Application` automation interface, saves a new DOCX, and exports a PDF. It refuses
to overwrite existing QA artifacts and preserves pre-existing WPS processes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/wps_roundtrip.ps1 `
  -InputPath output.docx `
  -OutputDirectory work/wps-qa

mathfmt validate work/wps-qa/output.wps-roundtrip.docx `
  --compatibility wps `
  --report work/wps-qa/validation-wps.json
```

Inspect the exported `output.wps.pdf` for clipping, overlap, missing glyphs, visible
alignment markers, and lost spacing. WPS Writer 12.0 on Windows was used for the v0.5
acceptance pass. The offline compatibility profile is cross-platform; native Linux WPS
rendering remains a manual environment-specific check.

---

## 7. Working with Tables

Formulas in table cells are automatically detected and rendered with reduced font size.

Long formulas that exceed the column width are split at top-level `+`/`-` operators into multiple lines. This is applied when:

- The paragraph is inside a table cell (`w:tc`)
- The formula covers the entire paragraph
- The estimated formula width (accounting for derivative expansion) exceeds the threshold

The split logic respects bracket nesting — it will not break inside `(...)`, `[...]`, or `{...}`.

---

## 8. Headers and Footers

MathFmt scans `word/header*.xml` and `word/footer*.xml` in addition to the document body. Formulas in headers and footers are converted the same way as body text formulas.

---

## 9. CI / Headless Use

MathFmt can run without a display:

```powershell
# Uses built-in Python OMML backend on any platform
mathfmt convert input.docx

# Or with explicit XSL backend
mathfmt convert input.docx --xsl "C:\path\to\MML2OMML.XSL"

# Scan-only (no conversion backend needed)
mathfmt scan input.docx --report candidates.json
```

The `doctor --json` output is machine-readable:

```json
{"mathfmt": "0.1.0", "python": "3.12.0", "platform": "Linux-...", "windows": false, "lxml": [5, 3, 0], "xsl": null, "backend": "python", "ready": true}
```

---

## 10. Troubleshooting

| Problem | Solution |
|---|---|
| `MML2OMML.XSL was not found` | Normal — the built-in Python backend is used automatically. To use Office XSL, pass `--xsl` |
| `Refusing to overwrite the input DOCX` | MathFmt never overwrites the source; choose a different `--output` path |
| `Input must be a .docx file` | MathFmt only handles `.docx` (Office Open XML); convert older `.doc` files first |
| `Alias profile must be a .json file` | Alias profiles intentionally use the documented strict JSON format |
| `Recognizer must use the form module:object` | Pass a trusted importable recognizer such as `my_plugin:Recognizer`; see `docs/plugins.md` |
| `Review report uses alias profile ...` | Pass the same profile used for `scan` with `--aliases` |
| `Alias profile ... does not match` | The profile changed after review; restore the reviewed file or scan again |
| `Review report was created without an alias profile` | Re-run `scan --aliases ...`; aliases cannot be introduced only at apply time |
| Formula not detected | Check whether it contains an anchor operator (`=`, `≠`, `<=`, `>=`, `!=`, `→`, `->`, `±`, `+/-`, `√`, `sqrt`, `lim`) or a documented chemistry/physics pattern. Otherwise mark it explicitly with `$...$` |
| `parse_status: "review"` | The formula couldn't be parsed. Edit `linear` in the candidate report, or set `selected: false` |
| Table formula is cut off | The formula may be too long even after splitting. Shorten the `linear` text or split it manually into multiple paragraphs |
| `hyperlink` in skipped error | The formula is inside a hyperlink. Move it outside the `w:hyperlink` element in the DOCX |
