from __future__ import annotations

import io
import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from mathfmt import cli, gui
from mathfmt.core import M_NS, W_NS
from tests.helpers import make_docx, make_fake_xsl


@pytest.fixture
def running_server() -> Any:
    server = gui._create_server("127.0.0.1", 0, None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    base_url = f"http://{host}:{port}"
    try:
        yield base_url, server
    finally:
        server.sessions.clear()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        shutil.rmtree(server.base_dir, ignore_errors=True)


def _post_scan(
    base_url: str,
    path: Path,
    *,
    filename: str | None = None,
) -> tuple[int, dict[str, object]]:
    data = path.read_bytes()
    query = f"filename={filename or path.name}"
    request = urllib.request.Request(
        f"{base_url}/scan?{query}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post_apply(
    base_url: str,
    token: str,
    selection: dict[str, bool],
    *,
    strict: bool = False,
    stem: str = "output",
) -> tuple[int, dict[str, object]]:
    query = f"strict={'1' if strict else '0'}&stem={stem}"
    body = json.dumps(selection).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/apply/{token}?{query}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_ensure_utf8_console_streams_fixes_a_non_utf8_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: serve()'s Chinese status text used to crash the server.

    A Windows console on a non-UTF-8 codepage, or stdout/stderr redirected to
    a file or pipe, can leave `print()` unable to encode the banner's Chinese
    punctuation, raising UnicodeEncodeError before `serve_forever()` is ever
    reached (observed for real: a frozen build's stdout redirected to a log
    file on a GitHub Actions Windows runner).
    """
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    with pytest.raises(UnicodeEncodeError):
        print("按 Ctrl+C 停止服务", file=stream)

    monkeypatch.setattr(gui.sys, "stdout", stream)
    gui._ensure_utf8_console_streams()
    print("按 Ctrl+C 停止服务", file=gui.sys.stdout)  # must not raise


def test_ensure_utf8_console_streams_tolerates_a_non_reconfigurable_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoReconfigure:
        pass

    monkeypatch.setattr(gui.sys, "stdout", NoReconfigure())
    monkeypatch.setattr(gui.sys, "stderr", NoReconfigure())
    gui._ensure_utf8_console_streams()  # must not raise


def test_index_page_is_served(running_server: Any) -> None:
    base_url, _ = running_server
    with urllib.request.urlopen(f"{base_url}/") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        body = resp.read().decode("utf-8")
    assert "MathFmt" in body
    assert "拖" in body


def test_scan_returns_candidates_with_defaults(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    source = make_docx(tmp_path / "source.docx")

    status, payload = _post_scan(base_url, source)

    assert status == 200
    assert payload["token"]
    assert payload["candidates"]
    # scan_docx pre-selects only high-confidence candidates by default.
    for candidate in payload["candidates"]:
        assert candidate["selected"] == (candidate["confidence"] == "high")


def test_apply_with_default_selection_then_download_and_report(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    source = make_docx(tmp_path / "source.docx")

    _, scan_payload = _post_scan(base_url, source)
    token = scan_payload["token"]
    selection = {c["id"]: c["selected"] for c in scan_payload["candidates"]}

    status, payload = _post_apply(base_url, token, selection)

    assert status == 200
    assert payload["converted"] >= 1
    assert payload["output_available"] is True
    assert payload["strict_failed"] is False
    assert payload["token"] == token

    with urllib.request.urlopen(f"{base_url}/download/{token}") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Disposition"] == "attachment"
        assert resp.read().startswith(b"PK")  # a .docx is a ZIP archive

    with urllib.request.urlopen(f"{base_url}/report/{token}") as resp:
        assert resp.status == 200
        report = json.loads(resp.read())
    assert report["converted_count"] == payload["converted"]


def test_apply_selection_overrides_scan_defaults(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    source = make_docx(tmp_path / "source.docx")

    _, scan_payload = _post_scan(base_url, source)
    token = scan_payload["token"]

    # deselect everything the scan defaulted to "selected"
    selection = {c["id"]: False for c in scan_payload["candidates"]}
    status, payload = _post_apply(base_url, token, selection)

    assert status == 200
    assert payload["converted"] == 0


def test_apply_can_include_a_non_default_candidate(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    source = make_docx(tmp_path / "source.docx")

    _, scan_payload = _post_scan(base_url, source)
    token = scan_payload["token"]
    parsable = [c for c in scan_payload["candidates"] if c["parse_status"] == "ok"]
    assert parsable  # sanity check on the fixture

    # select every parsable candidate regardless of the scan's own default
    selection = {c["id"]: True for c in parsable}
    status, payload = _post_apply(base_url, token, selection)

    assert status == 200
    assert payload["converted"] == len(parsable)


def test_apply_strict_mode_withholds_output_on_failure(tmp_path: Path, running_server: Any) -> None:
    base_url, server = running_server
    source = make_docx(tmp_path / "source.docx")

    _, scan_payload = _post_scan(base_url, source)
    token = scan_payload["token"]

    # Inject a candidate whose source can't be located in the document, the same
    # way test_cli.py forces an apply-time failure, so strict mode has something
    # selected to fail on.
    session_dir = server.sessions.get(token)
    review_path = session_dir / "candidates.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["candidates"].append(
        {
            "id": "bogus",
            "selected": False,
            "part": "word/document.xml",
            "paragraph_index": 0,
            "start": 0,
            "end": 5,
            "source": "this text does not appear in the fixture document",
        }
    )
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    status, payload = _post_apply(base_url, token, {"bogus": True}, strict=True)

    assert status == 200
    assert payload["strict_failed"] is True
    assert payload["output_available"] is False


def test_apply_does_not_serve_stale_output_after_a_later_failed_reapply(
    tmp_path: Path, running_server: Any
) -> None:
    base_url, server = running_server
    source = make_docx(tmp_path / "source.docx")

    _, scan_payload = _post_scan(base_url, source)
    token = scan_payload["token"]
    selection = {c["id"]: c["selected"] for c in scan_payload["candidates"]}

    # First apply succeeds and produces a downloadable output.docx.
    status, payload = _post_apply(base_url, token, selection)
    assert status == 200
    assert payload["output_available"] is True
    with urllib.request.urlopen(f"{base_url}/download/{token}") as resp:
        assert resp.status == 200

    # Re-apply on the same token/session with a candidate that fails under
    # strict mode. The response correctly reports no output, but /download
    # must not keep serving the earlier successful attempt's leftover file.
    session_dir = server.sessions.get(token)
    review_path = session_dir / "candidates.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["candidates"].append(
        {
            "id": "bogus",
            "selected": False,
            "part": "word/document.xml",
            "paragraph_index": 0,
            "start": 0,
            "end": 5,
            "source": "this text does not appear in the fixture document",
        }
    )
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    status, payload = _post_apply(base_url, token, {"bogus": True}, strict=True)
    assert status == 200
    assert payload["output_available"] is False

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{base_url}/download/{token}")
    assert excinfo.value.code == 404


def test_apply_rejects_unknown_token(running_server: Any) -> None:
    base_url, _ = running_server
    status, payload = _post_apply(base_url, "does-not-exist", {})
    assert status == 404
    assert "error" in payload


def test_apply_rejects_non_object_selection(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    source = make_docx(tmp_path / "source.docx")
    _, scan_payload = _post_scan(base_url, source)
    token = scan_payload["token"]

    body = json.dumps([1, 2, 3]).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/apply/{token}?strict=0&stem=output",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request)
    assert excinfo.value.code == 400


def test_scan_rejects_non_docx_extension(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    source = make_docx(tmp_path / "source.docx")

    status, payload = _post_scan(base_url, source, filename="notes.txt")

    assert status == 400
    assert "docx" in payload["error"]


def test_scan_rejects_empty_body(running_server: Any) -> None:
    base_url, _ = running_server
    request = urllib.request.Request(
        f"{base_url}/scan?filename=empty.docx",
        data=b"",
        method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request)
    assert excinfo.value.code == 411


def test_scan_rejects_oversized_upload(tmp_path: Path, running_server: Any) -> None:
    base_url, server = running_server
    server.max_upload_bytes = 10
    source = make_docx(tmp_path / "source.docx")

    status, payload = _post_scan(base_url, source)

    assert status == 413
    assert "error" in payload


def test_scan_reports_broken_docx_as_error(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not actually a zip file")

    status, payload = _post_scan(base_url, broken)

    assert status == 400
    assert payload["error"]


def test_download_and_report_reject_unknown_token(running_server: Any) -> None:
    base_url, _ = running_server
    for route in ("download", "report"):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(f"{base_url}/{route}/does-not-exist")
        assert excinfo.value.code == 404


def test_unknown_route_returns_404(running_server: Any) -> None:
    base_url, _ = running_server
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{base_url}/nope")
    assert excinfo.value.code == 404


def test_session_store_expires_and_removes_directory(tmp_path: Path) -> None:
    store = gui._SessionStore(ttl_seconds=-1)
    session_dir = tmp_path / "expired"
    session_dir.mkdir()
    token = store.store(session_dir)
    assert store.get(token) == session_dir

    other_dir = tmp_path / "next"
    other_dir.mkdir()
    store.store(other_dir)  # triggers a sweep that should evict the expired entry

    assert store.get(token) is None
    assert not session_dir.exists()


def test_session_store_clear_removes_every_directory(tmp_path: Path) -> None:
    store = gui._SessionStore()
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    token = store.store(session_dir)

    store.clear()

    assert store.get(token) is None
    assert not session_dir.exists()


def test_cli_gui_command_dispatches_to_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_serve(*, host: str, port: int, xsl_path: Path | None, open_browser: bool) -> None:
        calls.update(host=host, port=port, xsl_path=xsl_path, open_browser=open_browser)

    def missing_xsl(_: Path | None = None) -> Path:
        raise FileNotFoundError("no stylesheet in this test environment")

    monkeypatch.setattr(gui, "serve", fake_serve)
    monkeypatch.setattr(cli, "find_xsl", missing_xsl)

    assert cli.main(["gui", "--no-browser", "--port", "5005"]) == 0
    assert calls == {"host": "127.0.0.1", "port": 5005, "xsl_path": None, "open_browser": False}


def test_cli_gui_command_uses_explicit_xsl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    xsl = make_fake_xsl(tmp_path / "fake.xsl")
    calls: dict[str, object] = {}

    def fake_serve(*, host: str, port: int, xsl_path: Path | None, open_browser: bool) -> None:
        calls.update(xsl_path=xsl_path)

    monkeypatch.setattr(gui, "serve", fake_serve)

    assert cli.main(["gui", "--no-browser", "--xsl", str(xsl)]) == 0
    assert calls["xsl_path"] == xsl.resolve()


def _document_with(*paragraphs: str) -> str:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}" xmlns:m="{M_NS}"><w:body>{body}</w:body></w:document>'
    )


def _scan_one(tmp_path: Path, base_url: str, paragraph: str) -> dict[str, object]:
    """Scan a one-paragraph document and return its first candidate."""
    source = make_docx(tmp_path / "preview.docx", document_xml=_document_with(paragraph))
    status, payload = _post_scan(base_url, source)
    assert status == 200
    candidates = [c for c in payload["candidates"] if c["source"]]
    assert candidates, "the paragraph produced no candidate"
    return candidates[0]


def test_scan_returns_linear_and_mathml_for_each_candidate(tmp_path: Path, running_server: Any) -> None:
    # The page needs the parser-ready text to seed its editor, and the MathML to
    # show what the formula will look like. Both come from the scan response so
    # the first render costs no extra round trip.
    base_url, _ = running_server
    candidate = _scan_one(tmp_path, base_url, "公式 $x^2 + 1$ 在此。")

    assert candidate["source"] == "$x^2 + 1$"
    # `linear`, not `source`: the delimiters are stripped for the parser, and a
    # preview built from `source` would fail on the dollar signs.
    assert candidate["linear"] == "x^2 + 1"
    assert str(candidate["mathml"]).startswith("<math")
    assert "msup" in str(candidate["mathml"])


def test_scan_sends_no_mathml_for_an_unparseable_candidate(tmp_path: Path, running_server: Any) -> None:
    # A preview is not a gate: the candidate is still listed with its existing
    # parse_status and hint. None rather than "" so the page can tell "no
    # preview available" from "an empty formula".
    base_url, _ = running_server
    candidate = _scan_one(tmp_path, base_url, "坏公式 $x = +$ 在此。")

    assert candidate["parse_status"] != "ok"
    assert candidate["mathml"] is None
    assert candidate["linear"] == "x = +"


def _post_preview(base_url: str, token: str, linear: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"{base_url}/preview/{token}",
        data=linear.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _token_for(tmp_path: Path, base_url: str) -> str:
    source = make_docx(tmp_path / "session.docx", document_xml=_document_with("公式 $x^2$ 在此。"))
    status, payload = _post_scan(base_url, source)
    assert status == 200
    return str(payload["token"])


def test_preview_renders_a_valid_formula(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    token = _token_for(tmp_path, base_url)

    status, payload = _post_preview(base_url, token, "(a+b)/c")

    assert status == 200
    assert payload["ok"] is True
    assert str(payload["mathml"]).startswith("<math")
    assert "mfrac" in str(payload["mathml"])


def test_preview_reports_a_parse_error_without_failing_the_request(
    tmp_path: Path, running_server: Any
) -> None:
    # A formula that does not parse is a normal answer to a valid request, not a
    # transport failure — the page needs the error text, and an HTTP error
    # status would make it fish the body out of an exception instead.
    base_url, _ = running_server
    token = _token_for(tmp_path, base_url)

    status, payload = _post_preview(base_url, token, "x +")

    assert status == 200
    assert payload["ok"] is False
    assert payload["error"]
    assert "operand is missing" in str(payload["hint"])


def test_preview_names_an_unsupported_latex_macro(tmp_path: Path, running_server: Any) -> None:
    # v1.3's rejection path reaching the GUI unchanged: the reader is told which
    # macro is unsupported, not that a backslash is unrecognized.
    base_url, _ = running_server
    token = _token_for(tmp_path, base_url)

    status, payload = _post_preview(base_url, token, r"\substack{a}")

    assert status == 200
    assert payload["ok"] is False
    assert "substack" in str(payload["error"])
    assert "section 10" in str(payload["hint"])


def test_preview_expands_a_supported_latex_macro(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    token = _token_for(tmp_path, base_url)

    status, payload = _post_preview(base_url, token, r"\frac{a}{b}")

    assert status == 200
    assert payload["ok"] is True
    assert "mfrac" in str(payload["mathml"])


def test_preview_rejects_an_unknown_session(running_server: Any) -> None:
    # A token is only ever issued by /scan, and expires with the session. That
    # is what keeps this from being an open formula compiler on 127.0.0.1.
    base_url, _ = running_server

    status, payload = _post_preview(base_url, "not-a-real-token", "x^2")

    assert status == 404
    assert payload["error"]


def test_preview_rejects_an_oversized_body(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    token = _token_for(tmp_path, base_url)

    status, _ = _post_preview(base_url, token, "x" * (gui._MAX_PREVIEW_BYTES + 1))

    assert status == 413


def test_preview_rejects_an_empty_formula(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    token = _token_for(tmp_path, base_url)

    status, payload = _post_preview(base_url, token, "   ")

    assert status == 200
    assert payload["ok"] is False
