from __future__ import annotations

import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from mathfmt import cli, gui
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


def _post_docx(
    base_url: str,
    path: Path,
    *,
    confidence: str = "high",
    strict: bool = False,
    filename: str | None = None,
) -> tuple[int, dict[str, object]]:
    data = path.read_bytes()
    query = f"filename={filename or path.name}&confidence={confidence}&strict={'1' if strict else '0'}"
    request = urllib.request.Request(
        f"{base_url}/convert?{query}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_index_page_is_served(running_server: Any) -> None:
    base_url, _ = running_server
    with urllib.request.urlopen(f"{base_url}/") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        body = resp.read().decode("utf-8")
    assert "MathFmt" in body
    assert "拖" in body


def test_convert_success_then_download_and_report(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    source = make_docx(tmp_path / "source.docx")

    status, payload = _post_docx(base_url, source)

    assert status == 200
    assert payload["candidates"] >= 1
    assert payload["converted"] >= 1
    assert payload["output_available"] is True
    assert payload["strict_failed"] is False
    token = payload["token"]

    with urllib.request.urlopen(f"{base_url}/download/{token}") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Disposition"] == "attachment"
        assert resp.read().startswith(b"PK")  # a .docx is a ZIP archive

    with urllib.request.urlopen(f"{base_url}/report/{token}") as resp:
        assert resp.status == 200
        report = json.loads(resp.read())
    assert report["converted_count"] == payload["converted"]


def test_convert_rejects_non_docx_extension(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    source = make_docx(tmp_path / "source.docx")

    status, payload = _post_docx(base_url, source, filename="notes.txt")

    assert status == 400
    assert "docx" in payload["error"]


def test_convert_rejects_empty_body(running_server: Any) -> None:
    base_url, _ = running_server
    request = urllib.request.Request(
        f"{base_url}/convert?filename=empty.docx",
        data=b"",
        method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request)
    assert excinfo.value.code == 411


def test_convert_rejects_oversized_upload(tmp_path: Path, running_server: Any) -> None:
    base_url, server = running_server
    server.max_upload_bytes = 10
    source = make_docx(tmp_path / "source.docx")

    status, payload = _post_docx(base_url, source)

    assert status == 413
    assert "error" in payload


def test_convert_reports_broken_docx_as_error(tmp_path: Path, running_server: Any) -> None:
    base_url, _ = running_server
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not actually a zip file")

    status, payload = _post_docx(base_url, broken)

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
