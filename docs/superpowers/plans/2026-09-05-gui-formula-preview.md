# Implementation plan — GUI formula preview and inline editing

Implements §5 of `docs/superpowers/specs/2026-09-03-latex-input-and-gui-preview-design.md`,
the half deliberately left out of the v1.3 plan. The LaTeX input subset shipped in
v1.3.0; this closes the review loop it created.

## Why this is worth doing now

v1.3.0 made an undelimited LaTeX macro a **medium**-confidence candidate that is
never auto-selected. That was the right call — the author did not mark it as
math — but it means the reader now has more to review, and the GUI's review step
shows only the *source text* of each candidate. To see what a formula will
actually look like, or to fix one that parsed wrong, the reader has to leave the
GUI, edit `candidates.json` by hand, and run the CLI. The feature that created
the review burden did not extend the tool that handles it.

## Scope

In (spec §5):

- `/scan` returns `linear` and `mathml` per candidate.
- New `POST /preview/<token>`: linear text in, MathML or a structured error out.
- Each candidate renders its MathML natively in the browser.
- The linear text is editable; blurring re-previews it.
- `/apply` accepts an edited `linear` and writes it back to `candidates.json`
  before calling `apply_docx` — which is the hand-edit review flow apply has
  supported since v0.3, so the conversion side needs no new logic.
- Graceful degradation when the browser cannot render MathML.

Out (spec §9 plus one addition):

- Everything in the spec's YAGNI list.
- **Paragraph-context highlighting** — explicitly out per spec §9.
- **Live preview on every keystroke.** Blur-triggered only. Each preview is a
  parse; per-keystroke would turn a 200-candidate document into a request storm
  against a single-threaded stdlib server.

## Current shape this builds on

Read before starting; the plan assumes these:

- `gui.py:136 do_POST` routes `["scan"]` and `["apply", <token>]` by path
  segments. A third route goes here.
- `gui.py:178 _scan` builds the per-candidate dict sent to the page. Two fields
  are added there; `scan_docx` itself is not touched.
- `gui.py:240 _apply` reads the selection as `id → bool`
  (`candidate["selected"] = bool(selection[candidate_id])`), writes
  `candidates.json`, then calls `apply_docx` under `sessions.apply_lock(token)`.
- `_json_error`/`_json_response` put every message in a **JSON body**, so the
  latin-1 status-line trap that `send_error(message=...)` has does not apply
  here. Do not reach for `send_error` in the new route.
- The page builds rows with `innerHTML` and escapes every interpolated value
  through `escapeHtml` (`gui.py:569`). MathML is the first thing this page
  inserts that is *meant* to be markup — see Task 3.

---

## Task 1: `/scan` returns `linear` and `mathml`

**Files:** `src/mathfmt/gui.py` (`_scan`), `tests/test_gui.py`

- [ ] **Step 1: Write the failing test**

```python
def test_scan_returns_linear_and_mathml_for_each_candidate(tmp_path: Path) -> None:
    payload = _scan_docx_through_server(tmp_path, "公式 $x^2 + 1$ 在此。")
    candidate = payload["candidates"][0]
    assert candidate["linear"] == "x^2 + 1"
    assert candidate["mathml"].startswith("<math")
    assert "msup" in candidate["mathml"]


def test_scan_sends_no_mathml_for_an_unparseable_candidate(tmp_path: Path) -> None:
    # parse_status is already reported; mathml is simply absent rather than an
    # empty string, so the page can distinguish "no preview" from "empty formula".
    payload = _scan_docx_through_server(tmp_path, "坏公式 $x = +$ 在此。")
    candidate = payload["candidates"][0]
    assert candidate["parse_status"] != "ok"
    assert candidate["mathml"] is None
```

- [ ] **Step 2: Run to verify they fail** — `KeyError: 'linear'`.

- [ ] **Step 3: Implement**

In `_scan`'s candidate comprehension add `"linear": c.get("linear") or c.get("source", "")`
and `"mathml": _mathml_for(c)`, with:

```python
def _mathml_for(candidate: Mapping[str, object]) -> str | None:
    """Serialized MathML for a candidate, or None when it does not parse.

    Rendering is a preview, not a gate: a candidate that fails here is still
    listed, with its existing parse_status and hint. Returning None rather than
    "" lets the page tell "no preview available" from "an empty formula".
    """
    if candidate.get("parse_status") != "ok":
        return None
    try:
        return etree.tostring(formula_to_mathml(str(candidate.get("linear") or "")), encoding="unicode")
    except FormulaError:
        return None
```

Note the `linear`/`source` distinction (see `CLAUDE.md`): parse `linear`, never
`source`, or a delimited candidate previews as `$x^2+1$` and fails.

- [ ] **Step 4: Run the tests** — PASS.
- [ ] **Step 5: Commit** — `feat(gui): send linear text and MathML with each candidate`

---

## Task 2: `POST /preview/<token>`

**Files:** `src/mathfmt/gui.py`, `tests/test_gui.py`

- [ ] **Step 1: Write the failing tests**

Cover, at minimum: a success returning `{ok: true, mathml}`; a parse failure
returning `{ok: false, error, hint}` with **HTTP 200** (a formula that does not
parse is a normal answer to a valid request, not a transport failure); an
unknown token returning 404; a body over the size cap returning 413; and a
LaTeX macro outside the subset producing a `hint` that names the macro —
the v1.3 error path reaching the GUI unchanged.

- [ ] **Step 2: Run to verify they fail** — 404 from the router.

- [ ] **Step 3: Implement**

Add to `do_POST`, next to the existing two:

```python
        if len(segments) == 2 and segments[0] == "preview":
            self._handle_preview(segments[1])
            return
```

`_handle_preview` mirrors `_handle_apply`'s opening: resolve the token through
`self.server.sessions.get`, 404 with `"会话已失效，请重新上传文件"` when it is gone,
read the body under a new `_MAX_PREVIEW_BYTES = 64 * 1024` cap (one formula, not
a document), decode UTF-8, then:

```python
        try:
            mathml = etree.tostring(formula_to_mathml(linear), encoding="unicode")
        except FormulaError as error:
            details = error.to_dict()
            self._json_response(
                HTTPStatus.OK,
                {"ok": False, "error": str(details.get("message", "")), "hint": details.get("hint")},
            )
            return
        self._json_response(HTTPStatus.OK, {"ok": True, "mathml": mathml})
```

The session lookup is what makes this not an open formula-compiler on
`127.0.0.1`: a token is only issued by `/scan`, and `_SessionStore` sweeps it
after the TTL.

- [ ] **Step 4: Run the tests** — PASS.
- [ ] **Step 5: Commit** — `feat(gui): add a /preview route for one formula`

---

## Task 3: Render the MathML in the page

**Files:** `src/mathfmt/gui.py` (the embedded page), `tests/test_gui.py`

- [ ] **Step 1: Decide how the markup enters the DOM — do not use `innerHTML`**

Every other value this page inserts goes through `escapeHtml`. MathML is the
first that must stay markup, so it cannot follow that path, and it must not go
through the HTML parser either:

```js
function mathmlNode(xml) {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  if (doc.querySelector('parsererror')) return null;
  return document.importNode(doc.documentElement, true);
}
```

Parsing as XML and importing the element means no HTML parsing of
server-supplied text at any point, so event-handler attributes and script
elements have no way in — regardless of what the source document contained.
`innerHTML` here would put document text on the other side of the HTML parser
for the first time in this file. The cost of the safe version is four lines.

- [ ] **Step 2: Render under each candidate**

After building each row, insert `mathmlNode(candidate.mathml)` into that row's
preview slot when `mathml` is non-null; otherwise leave the slot empty and show
the existing `parse_error`/`parse_hint`.

- [ ] **Step 3: Test what a headless test can actually test**

`tests/test_gui.py` drives the HTTP API, not a browser. Assert the page source
contains the `DOMParser`-based helper and does **not** assign candidate MathML
through `innerHTML` — a regression guard for the decision above, not a
rendering test. Real rendering is checked by hand, per the QA note below.

- [ ] **Step 4: Commit** — `feat(gui): render each candidate's MathML natively`

---

## Task 4: Editable linear text, re-previewed on blur

**Files:** `src/mathfmt/gui.py` (page), `tests/test_gui.py`

- [ ] **Step 1: Make the linear text an editable field** per candidate, seeded
  from `candidate.linear`, with the original kept so an edit can be reverted and
  so an unedited candidate sends nothing extra to `/apply`.

- [ ] **Step 2: On blur**, if the value changed, `POST /preview/<token>`; on
  `ok` swap the preview node, on `!ok` show `error` and `hint` in the row's
  existing error slot and leave the previous preview visible with a "stale"
  marker. Do not auto-deselect a candidate whose edit fails to parse — the
  reader is mid-edit, and silently unchecking their work is worse than showing
  it is broken.

- [ ] **Step 3: Serialize per row.** Ignore an in-flight preview's response if a
  newer one has been issued for the same row (compare a monotonically increasing
  request id), or a slow first response can overwrite a fast second one.

- [ ] **Step 4: Commit** — `feat(gui): edit a candidate's linear text and re-preview`

---

## Task 5: `/apply` accepts the edited `linear`

**Files:** `src/mathfmt/gui.py` (`_apply`), `tests/test_gui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_apply_writes_an_edited_linear_into_the_output(tmp_path: Path) -> None:
    # The whole point of the feature: what the reader typed is what gets
    # converted, not what the scanner found.
    ...
    selection = {candidate_id: {"selected": True, "linear": "y^3"}}
    ...
    assert "msup" in document_xml and "y" in document_xml


def test_apply_still_accepts_a_bare_boolean_selection(tmp_path: Path) -> None:
    # The v1.2 payload shape stays valid; spec §7 requires the existing tests to
    # pass unchanged.
    ...


def test_apply_reports_an_edited_linear_that_does_not_parse(tmp_path: Path) -> None:
    # The client already previews, but never trust it: the server re-parses.
    # A bad edit is reported through the existing `skipped` channel rather than
    # failing the whole request.
    ...
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement** — normalize each entry to `(selected, linear)`,
  accepting both a bare bool and an object:

```python
            for candidate in review.get("candidates", []):
                entry = selection.get(candidate.get("id"))
                if entry is None:
                    continue
                if isinstance(entry, dict):
                    candidate["selected"] = bool(entry.get("selected"))
                    edited = entry.get("linear")
                    if isinstance(edited, str) and edited.strip():
                        candidate["linear"] = edited.strip()
                else:
                    candidate["selected"] = bool(entry)
```

An edit that does not parse needs no new handling: `apply_docx` already records
a failing candidate in `skipped` with its error, which `_apply` already forwards
as `skipped_items`.

- [ ] **Step 4: Run the full suite** — every pre-existing `test_gui.py` test must
  pass untouched.
- [ ] **Step 5: Commit** — `feat(gui): apply the reviewer's edited formula text`

---

## Task 6: Degrade when the browser cannot render MathML

**Files:** `src/mathfmt/gui.py` (page)

Spec §5: falling back to plain text is **not** an error.

- [ ] **Step 1: Feature-detect once** at startup rather than per row.
  `document.createElement('math')` plus a measured-height probe is the usual
  approach; pick one and comment why.
- [ ] **Step 2: When unsupported**, show the linear text in a monospace slot and
  one dismissible note explaining that previews need a MathML-capable browser.
  Editing, `/preview` validation, and `/apply` all keep working — validation is
  server-side, so only the picture is missing.
- [ ] **Step 3: Commit** — `feat(gui): fall back to linear text without MathML support`

---

## Task 7: Documentation

**Files:** `docs/workflow.md`, `README.md`, `CHANGELOG.md`

- [ ] `docs/workflow.md` §2 (GUI): the review step now previews and edits; note
  that an edit is validated server-side and that a failed edit does not silently
  drop the candidate.
- [ ] `README.md`: one bilingual line.
- [ ] `CHANGELOG.md`: under the existing `[Unreleased]`, an `### Added` entry.
  This is a feature addition to a stable minor line — v1.4.0, not a patch.
- [ ] `docs/api.md`: **no change**; no exported symbol is added.

---

## Verification beyond the test suite

`tests/test_gui.py` exercises the HTTP API with no browser, so three things it
cannot see must be checked outside it.

**Done 2026-09-05**, driven through the `agent-browser` CLI against
`mathfmt gui --port 8768 --no-browser` on `doc07_latex.docx` (Chromium):

1. **MathML renders.** All five candidates produced a real `<math>` element,
   with heights matching actual layout rather than inline fallback —
   `\frac{a}{b}` 24px, `cases` 40px, `\bar{x}` 10px.
2. **Edit → blur → re-preview updates the picture.** `\frac{a}{b}` → `mfrac`,
   edited to `sqrt(x^2+1)` → `msqrt`, then to `root(x,7)` → `mroot`. A broken
   edit (`x +`) showed the error, dimmed the last good rendering rather than
   blanking it, and left the candidate checked. `\substack{a}` reported the
   macro by name, so v1.3's rejection path reaches the GUI intact.
3. **The edited formula reaches the DOCX.** Converting with `root(x,7)` in the
   first row produced `m:rad` with `<m:t>7</m:t>` in `word/document.xml` — the
   scanner had found `\frac{a}{b}` there.

One defect this found, fixed in the same branch: a `FormulaError` message
carries a caret line aligned for a monospace terminal, which in a proportional
div pointed at nothing and broke the message across lines. Both the inline edit
error and the pre-existing candidate-list error now collapse whitespace first.

Recorded in `.claude/memory.md` the way the WPS and LibreOffice QA notes are.

## Risks

- **Preview cost on a large document.** A 200-candidate scan now parses every
  candidate twice (once in `scan_docx`, once for its MathML). Both are pure
  parses of text already in memory, and the 100-page benchmark gate will catch
  a regression — but check `benchmarks/` output before and after Task 1 rather
  than assuming.
- **`linear` vs `source` confusion** is the single most likely defect here; it
  has bitten this project before (see `CLAUDE.md`). Every new code path in this
  plan parses `linear`.
- **Front-end code is not covered by the 85% gate** — it lives in a string. Keep
  the JavaScript small enough to read, and put logic that can be tested on the
  server side.
