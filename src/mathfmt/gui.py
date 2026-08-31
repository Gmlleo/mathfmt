"""Local browser drag-and-drop interface for MathFmt.

Launched via ``mathfmt gui``. Starts a plain-stdlib HTTP server bound to localhost,
opens the default browser, and serves a single self-contained page: drop a ``.docx``
onto it (or click to choose one) to scan it, review the detected formula candidates
(pre-checked by MathFmt's own confidence defaults, individually adjustable), then
apply the conversion using the same engine as ``mathfmt apply``.

No files leave the machine — the server only binds to localhost by default and every
upload is written to a private per-request temporary directory that is cleaned up
after a short time-to-live or when the server stops.
"""

from __future__ import annotations

import json
import secrets
import shutil
import tempfile
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ._version import __version__
from .core import apply_docx, scan_docx

_MAX_UPLOAD_BYTES = 128 * 1024 * 1024
_MAX_SELECTION_BYTES = 2 * 1024 * 1024
_SESSION_TTL_SECONDS = 30 * 60
_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PARAGRAPH_PREVIEW_LIMIT = 160


class _SessionStore:
    """Maps a random session token to a private per-upload temp directory."""

    def __init__(self, ttl_seconds: float = _SESSION_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[Path, float]] = {}

    def store(self, session_dir: Path) -> str:
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._sweep_locked()
            self._sessions[token] = (session_dir, time.monotonic())
        return token

    def get(self, token: str) -> Path | None:
        with self._lock:
            entry = self._sessions.get(token)
        return entry[0] if entry is not None else None

    def clear(self) -> None:
        with self._lock:
            for session_dir, _ in self._sessions.values():
                shutil.rmtree(session_dir, ignore_errors=True)
            self._sessions.clear()

    def _sweep_locked(self) -> None:
        now = time.monotonic()
        expired = [token for token, (_, stored_at) in self._sessions.items() if now - stored_at > self._ttl]
        for token in expired:
            session_dir, _ = self._sessions.pop(token)
            shutil.rmtree(session_dir, ignore_errors=True)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        base_dir: Path,
        xsl_path: Path | None,
    ) -> None:
        super().__init__(address, handler_cls)
        self.base_dir = base_dir
        self.xsl_path = xsl_path
        self.sessions = _SessionStore()
        self.max_upload_bytes = _MAX_UPLOAD_BYTES


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class _Handler(BaseHTTPRequestHandler):
    server_version = f"MathFmtGUI/{__version__}"
    protocol_version = "HTTP/1.1"
    server: _Server

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep the terminal quiet; errors are surfaced in the page instead

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            self._send_html(PAGE_HTML)
            return
        if len(segments) == 2 and segments[0] == "download":
            self._send_session_file(segments[1], "output.docx", _DOCX_CONTENT_TYPE)
            return
        if len(segments) == 2 and segments[0] == "report":
            self._send_session_file(segments[1], "result.json", "application/json; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        segments = [segment for segment in urlsplit(self.path).path.split("/") if segment]
        if segments == ["scan"]:
            self._handle_scan()
            return
        if len(segments) == 2 and segments[0] == "apply":
            self._handle_apply(segments[1])
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    # -- scan: upload a .docx and return its formula candidates for review -----

    def _handle_scan(self) -> None:
        params = parse_qs(urlsplit(self.path).query)
        filename = (params.get("filename", [""])[0] or "upload.docx").strip()

        if not filename.lower().endswith(".docx"):
            self.close_connection = True
            self._json_error(HTTPStatus.BAD_REQUEST, "只支持 .docx 文件")
            return

        length = self._read_content_length()
        if length is None:
            return
        if length > self.server.max_upload_bytes:
            self.close_connection = True
            self._json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "文件太大（超过 128 MB）")
            return

        session_dir = Path(tempfile.mkdtemp(prefix="upload-", dir=str(self.server.base_dir)))
        try:
            input_path = session_dir / "input.docx"
            if not self._save_upload(input_path, length):
                shutil.rmtree(session_dir, ignore_errors=True)
                return
            payload = self._scan(session_dir, input_path, filename)
        except Exception as exc:  # surface any scan failure to the page instead of a 500 traceback
            shutil.rmtree(session_dir, ignore_errors=True)
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc) or exc.__class__.__name__)
            return
        self._json_response(HTTPStatus.OK, payload)

    def _scan(self, session_dir: Path, input_path: Path, filename: str) -> dict[str, object]:
        review_path = session_dir / "candidates.json"
        scan_docx(input_path, review_path)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        candidates = [
            {
                "id": c.get("id"),
                "source": c.get("source", ""),
                "context": _truncate(c.get("paragraph_text", ""), _PARAGRAPH_PREVIEW_LIMIT),
                "confidence": c.get("confidence"),
                "confidence_reason": c.get("confidence_reason"),
                "parse_status": c.get("parse_status"),
                "parse_error": c.get("parse_error"),
                "parse_hint": (c.get("parse_error_details") or {}).get("hint"),
                "selected": bool(c.get("selected")),
            }
            for c in review.get("candidates", [])
        ]
        token = self.server.sessions.store(session_dir)
        return {
            "token": token,
            "filename": filename,
            "stem": Path(filename).stem or "output",
            "candidates": candidates,
        }

    # -- apply: convert the reviewed selection for an existing scan session ----

    def _handle_apply(self, token: str) -> None:
        session_dir = self.server.sessions.get(token)
        if session_dir is None:
            self.close_connection = True
            self._json_error(HTTPStatus.NOT_FOUND, "会话已失效，请重新上传文件")
            return

        params = parse_qs(urlsplit(self.path).query)
        strict = params.get("strict", ["0"])[0] == "1"
        stem = (params.get("stem", [""])[0] or "output").strip() or "output"

        length = self._read_content_length()
        if length is None:
            return
        if length > _MAX_SELECTION_BYTES:
            self.close_connection = True
            self._json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "选择数据过大")
            return
        body = self.rfile.read(length)
        try:
            selection = json.loads(body.decode("utf-8"))
            if not isinstance(selection, dict):
                raise ValueError("selection must be a JSON object")
        except (ValueError, UnicodeDecodeError):
            self._json_error(HTTPStatus.BAD_REQUEST, "选择数据格式错误")
            return

        try:
            payload = self._apply(session_dir, token, selection, stem=stem, strict=strict)
        except Exception as exc:  # surface any apply failure to the page instead of a 500 traceback
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc) or exc.__class__.__name__)
            return
        self._json_response(HTTPStatus.OK, payload)

    def _apply(
        self,
        session_dir: Path,
        token: str,
        selection: dict[str, object],
        *,
        stem: str,
        strict: bool,
    ) -> dict[str, object]:
        review_path = session_dir / "candidates.json"
        input_path = session_dir / "input.docx"
        output_path = session_dir / "output.docx"
        result_path = session_dir / "result.json"

        review = json.loads(review_path.read_text(encoding="utf-8"))
        for candidate in review.get("candidates", []):
            candidate_id = candidate.get("id")
            if candidate_id in selection:
                candidate["selected"] = bool(selection[candidate_id])
        review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

        result = apply_docx(
            input_path,
            review_path,
            output_path,
            result_path,
            self.server.xsl_path,
            command_name="gui",
            strict=strict,
        )

        strict_failed = bool(result.get("summary", {}).get("strict_failed"))
        skipped_items = [
            {
                "source": str(item.get("source", item.get("id", "?"))),
                "reason": str(item.get("error", "")),
            }
            for item in result.get("skipped", [])
        ]
        return {
            "converted": result["converted_count"],
            "skipped": result["skipped_count"],
            "skipped_items": skipped_items,
            "strict_failed": strict_failed,
            "output_available": output_path.is_file() and not strict_failed,
            "token": token,
            "output_name": f"{stem}.mathfmt.docx",
            "report_name": f"{stem}.mathfmt.report.json",
        }

    # -- shared request/response helpers ----------------------------------------

    def _read_content_length(self) -> int | None:
        header = self.headers.get("Content-Length")
        try:
            length = int(header) if header is not None else 0
        except ValueError:
            length = 0
        if length <= 0:
            self.close_connection = True
            self._json_error(HTTPStatus.LENGTH_REQUIRED, "缺少或无效的请求内容")
            return None
        return length

    def _save_upload(self, input_path: Path, length: int) -> bool:
        remaining = length
        with input_path.open("wb") as stream:
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    self.close_connection = True
                    self._json_error(HTTPStatus.BAD_REQUEST, "上传中断")
                    return False
                stream.write(chunk)
                remaining -= len(chunk)
        return True

    def _send_session_file(self, token: str, member: str, content_type: str) -> None:
        session_dir = self.server.sessions.get(token)
        if session_dir is None:
            self.send_error(HTTPStatus.NOT_FOUND, explain="链接已失效，请重新转换")
            return
        path = session_dir / member
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, explain="文件不存在")
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", "attachment")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, page: str) -> None:
        body = page.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: HTTPStatus, message: str) -> None:
        self._json_response(status, {"error": message})

    def _json_response(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _create_server(host: str, port: int, xsl_path: Path | None) -> _Server:
    base_dir = Path(tempfile.mkdtemp(prefix="mathfmt-gui-"))
    return _Server((host, port), _Handler, base_dir=base_dir, xsl_path=xsl_path)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    xsl_path: Path | None = None,
    open_browser: bool = True,
) -> None:
    """Start the local GUI server and block until interrupted (Ctrl+C)."""
    server = _create_server(host, port, xsl_path)
    try:
        bound_host, bound_port = server.server_address[0], server.server_address[1]
        url = f"http://{bound_host}:{bound_port}/"
        print(f"MathFmt GUI: {url}")
        print("按 Ctrl+C 停止服务；文件只在本机临时目录处理，不会上传到网络。")
        if open_browser:
            threading.Timer(0.3, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n正在停止 MathFmt GUI…")
    finally:
        server.sessions.clear()
        server.server_close()
        shutil.rmtree(server.base_dir, ignore_errors=True)


PAGE_HTML = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MathFmt</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2.5rem 1.5rem 4rem; font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #f6f5f2; color: #1f2430; display: flex; flex-direction: column; align-items: center;
  }}
  main {{ width: 100%; max-width: 720px; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
  .sub {{ color: #666; margin: 0 0 1.75rem; font-size: .9rem; }}
  #drop {{
    border: 2px dashed #b8b2a4; border-radius: 14px; padding: 3rem 1.5rem; text-align: center;
    cursor: pointer; background: #fff; transition: border-color .15s, background .15s;
  }}
  #drop.drag {{ border-color: #6b5bd6; background: #f1eefb; }}
  #drop p {{ margin: 0; color: #444; }}
  #drop .hint {{ font-size: .8rem; color: #999; margin-top: .5rem; }}
  #status {{ margin: 1rem 0; padding: .6rem .9rem; border-radius: 8px; background: #eef1ff; font-size: .9rem; }}
  #status.error {{ background: #fde8e8; color: #a12222; }}
  #review {{ margin-top: 1rem; }}
  #review .toolbar {{ display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; margin-bottom: .6rem; font-size: .85rem; }}
  #review .toolbar .presets {{ display: flex; gap: .35rem; flex-wrap: wrap; }}
  .chip {{
    border: 1px solid #d8d3c4; background: #fff; border-radius: 999px; padding: .3rem .7rem;
    font-size: .78rem; cursor: pointer; color: #444;
  }}
  .chip:hover {{ border-color: #6b5bd6; color: #6b5bd6; }}
  #candidate-count {{ margin-left: auto; color: #777; font-size: .8rem; }}
  #candidate-list {{
    border: 1px solid #e5e1d8; border-radius: 12px; background: #fff; max-height: 360px; overflow-y: auto;
  }}
  .candidate {{ display: flex; gap: .6rem; padding: .6rem .8rem; border-bottom: 1px solid #f0eee7; align-items: flex-start; }}
  .candidate:last-child {{ border-bottom: none; }}
  .candidate input[type=checkbox] {{ margin-top: .2rem; flex-shrink: 0; }}
  .candidate .body {{ min-width: 0; flex: 1; }}
  .candidate .source {{ font-family: ui-monospace, Consolas, monospace; font-size: .88rem; word-break: break-all; }}
  .candidate .context {{ font-size: .76rem; color: #888; margin-top: .15rem; word-break: break-all; }}
  .badge {{
    display: inline-block; font-size: .7rem; padding: .05rem .4rem; border-radius: 5px; margin-right: .35rem;
    background: #eef1ff; color: #3a4bbf; white-space: nowrap;
  }}
  .badge.medium {{ background: #fff4e0; color: #9a6400; }}
  .badge.low {{ background: #f2f0ea; color: #767267; }}
  .badge.warn {{ background: #fde8e8; color: #a12222; }}
  .candidate.parse-warn .source {{ color: #a12222; }}
  #options {{ display: flex; gap: 1.25rem; align-items: center; margin: 1rem 0; font-size: .85rem; flex-wrap: wrap; }}
  #apply-btn {{
    border: none; border-radius: 8px; background: #6b5bd6; color: #fff; padding: .6rem 1.2rem;
    font-size: .9rem; cursor: pointer;
  }}
  #apply-btn:disabled {{ opacity: .4; cursor: default; }}
  #reset-btn {{ background: none; border: none; color: #777; font-size: .82rem; cursor: pointer; text-decoration: underline; }}
  #result {{ margin-top: 1rem; padding: 1rem 1.25rem; border-radius: 12px; background: #fff; border: 1px solid #e5e1d8; }}
  #result b {{ color: #111; }}
  #skipped ul {{ margin: .4rem 0 0; padding-left: 1.1rem; font-size: .85rem; color: #555; }}
  #skipped code {{ background: #f2f0ea; padding: 0 .25rem; border-radius: 4px; }}
  .btn {{
    display: inline-block; margin: .9rem .6rem 0 0; padding: .55rem 1.1rem; border-radius: 8px;
    background: #6b5bd6; color: #fff; text-decoration: none; font-size: .9rem;
  }}
  .btn.secondary {{ background: #e4e1f6; color: #3a2f8f; }}
  .btn.disabled {{ pointer-events: none; opacity: .4; }}
  footer {{ margin-top: 2rem; color: #999; font-size: .75rem; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1b1c22; color: #e7e5df; }}
    #drop {{ background: #23242c; border-color: #46485a; }}
    #drop.drag {{ background: #2c2a45; border-color: #8f7ff0; }}
    #drop p {{ color: #d8d6cf; }}
    #status {{ background: #262a3f; }}
    #status.error {{ background: #3a2222; color: #ff9d9d; }}
    .chip {{ background: #23242c; border-color: #46485a; color: #ccc; }}
    #candidate-list {{ background: #23242c; border-color: #35374a; }}
    .candidate {{ border-color: #2c2e38; }}
    .candidate .context {{ color: #999; }}
    .badge {{ background: #262a3f; color: #aab6ff; }}
    .badge.medium {{ background: #3a2f10; color: #e3b463; }}
    .badge.low {{ background: #2d2f38; color: #aaa; }}
    .badge.warn {{ background: #3a2222; color: #ff9d9d; }}
    #result {{ background: #23242c; border-color: #35374a; }}
    #result b {{ color: #fff; }}
    #skipped code {{ background: #2d2f38; }}
    .btn.secondary {{ background: #2d2a45; color: #c9c0ff; }}
    #reset-btn {{ color: #999; }}
  }}
</style>
</head>
<body>
<main>
  <h1>MathFmt</h1>
  <p class="sub">把纯文本公式转换成 Word 原生公式 — 拖进来，勾选要转换的公式即可。</p>

  <div id="drop" tabindex="0">
    <p>将 .docx 文件拖到这里，或点击选择文件</p>
    <p class="hint">文件只在本机处理，不会上传到互联网</p>
    <input type="file" id="file-input" accept=".docx" hidden>
  </div>

  <div id="status" hidden></div>

  <div id="review" hidden>
    <div class="toolbar">
      <span class="presets">
        <button type="button" class="chip" data-preset="high">仅高置信度</button>
        <button type="button" class="chip" data-preset="medium">中及以上</button>
        <button type="button" class="chip" data-preset="all">全部候选</button>
        <button type="button" class="chip" data-preset="none">全不选</button>
      </span>
      <span id="candidate-count"></span>
    </div>
    <div id="candidate-list"></div>
    <div id="options">
      <label><input type="checkbox" id="strict"> 严格模式（任一已选公式失败则不写出文件）</label>
      <button type="button" id="apply-btn">转换所选</button>
      <button type="button" id="reset-btn">转换另一个文件</button>
    </div>
  </div>

  <div id="result" hidden>
    <div id="stats"></div>
    <div id="skipped"></div>
    <a id="download-docx" class="btn" href="#">下载转换后的 DOCX</a>
    <a id="download-report" class="btn secondary" href="#">下载扫描报告 (JSON)</a>
  </div>
</main>
<footer>MathFmt {__version__}</footer>
<script>
(function () {{
  var drop = document.getElementById('drop');
  var fileInput = document.getElementById('file-input');
  var statusEl = document.getElementById('status');
  var reviewEl = document.getElementById('review');
  var listEl = document.getElementById('candidate-list');
  var countEl = document.getElementById('candidate-count');
  var applyBtn = document.getElementById('apply-btn');
  var resetBtn = document.getElementById('reset-btn');
  var strictBox = document.getElementById('strict');
  var resultEl = document.getElementById('result');
  var statsEl = document.getElementById('stats');
  var skippedEl = document.getElementById('skipped');
  var downloadDocx = document.getElementById('download-docx');
  var downloadReport = document.getElementById('download-report');

  var scanState = null; // {{ token, filename, stem, candidates }}

  function escapeHtml(text) {{
    var div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }}

  function setStatus(message, isError) {{
    statusEl.hidden = !message;
    statusEl.textContent = message || '';
    statusEl.className = isError ? 'error' : '';
  }}

  function confidenceLabel(level) {{
    if (level === 'high') return '高';
    if (level === 'medium') return '中';
    return '低';
  }}

  function candidateRowHtml(c) {{
    var warn = c.parse_status && c.parse_status !== 'ok';
    var badges = '<span class="badge ' + escapeHtml(c.confidence || 'low') + '">' +
      confidenceLabel(c.confidence) + '置信度</span>';
    if (warn) badges += '<span class="badge warn">解析失败</span>';
    var note = warn
      ? escapeHtml(c.parse_error || '无法解析，转换时会跳过') + (c.parse_hint ? '（' + escapeHtml(c.parse_hint) + '）' : '')
      : escapeHtml(c.confidence_reason || '');
    return (
      '<label class="candidate' + (warn ? ' parse-warn' : '') + '" data-id="' + escapeHtml(c.id) + '">' +
      '<input type="checkbox" class="candidate-check"' + (c.selected ? ' checked' : '') + '>' +
      '<span class="body">' +
      '<div class="source">' + badges + escapeHtml(c.source) + '</div>' +
      '<div class="context">' + note + '</div>' +
      '</span></label>'
    );
  }}

  function renderCandidates() {{
    var candidates = scanState.candidates;
    if (!candidates.length) {{
      reviewEl.hidden = true;
      setStatus('未在文档中发现候选公式：' + scanState.filename, false);
      return;
    }}
    listEl.innerHTML = candidates.map(candidateRowHtml).join('');
    reviewEl.hidden = false;
    resultEl.hidden = true;
    setStatus('已扫描：' + scanState.filename + '，请勾选要转换的公式', false);
    updateCount();
  }}

  function updateCount() {{
    var boxes = listEl.querySelectorAll('.candidate-check');
    var checked = 0;
    boxes.forEach(function (box) {{ if (box.checked) checked++; }});
    countEl.textContent = '已选 ' + checked + ' / ' + boxes.length;
    applyBtn.disabled = checked === 0;
  }}

  function applyPreset(preset) {{
    var rows = listEl.querySelectorAll('.candidate');
    rows.forEach(function (row) {{
      var id = row.getAttribute('data-id');
      var candidate = scanState.candidates.find(function (c) {{ return c.id === id; }});
      var box = row.querySelector('.candidate-check');
      var ok = candidate.parse_status === 'ok';
      var include;
      if (preset === 'none') include = false;
      else if (preset === 'all') include = ok;
      else if (preset === 'medium') include = ok && (candidate.confidence === 'high' || candidate.confidence === 'medium');
      else include = ok && candidate.confidence === 'high';
      box.checked = include;
    }});
    updateCount();
  }}

  function currentSelection() {{
    var selection = {{}};
    listEl.querySelectorAll('.candidate').forEach(function (row) {{
      var id = row.getAttribute('data-id');
      selection[id] = row.querySelector('.candidate-check').checked;
    }});
    return selection;
  }}

  function showResult(data) {{
    resultEl.hidden = false;
    var parts = [
      '转换成功 <b>' + data.converted + '</b> 个',
      '跳过 <b>' + data.skipped + '</b> 个'
    ];
    statsEl.innerHTML = parts.join('，') + '。';

    if (data.skipped_items && data.skipped_items.length) {{
      var rows = data.skipped_items.map(function (item) {{
        return '<li><code>' + escapeHtml(item.source) + '</code> — ' + escapeHtml(item.reason || '未知原因') + '</li>';
      }}).join('');
      skippedEl.innerHTML = '<p>以下内容未被转换，请检查：</p><ul>' + rows + '</ul>';
    }} else {{
      skippedEl.innerHTML = '';
    }}

    if (data.output_available) {{
      downloadDocx.href = '/download/' + data.token;
      downloadDocx.setAttribute('download', data.output_name);
      downloadDocx.classList.remove('disabled');
    }} else {{
      downloadDocx.classList.add('disabled');
    }}
    downloadReport.href = '/report/' + data.token;
    downloadReport.setAttribute('download', data.report_name);

    if (data.strict_failed) {{
      setStatus('严格模式：已选公式中存在失败项，未写出文件', true);
    }} else {{
      setStatus('转换完成：' + scanState.filename, false);
    }}
  }}

  function resetToDropzone() {{
    scanState = null;
    reviewEl.hidden = true;
    resultEl.hidden = true;
    setStatus('', false);
    fileInput.value = '';
  }}

  function scanFile(file) {{
    reviewEl.hidden = true;
    resultEl.hidden = true;
    setStatus('正在扫描 ' + file.name + ' …', false);

    var params = new URLSearchParams({{ filename: file.name }});
    fetch('/scan?' + params.toString(), {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/octet-stream' }},
      body: file
    }}).then(function (resp) {{
      return resp.json().then(function (data) {{
        if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        return data;
      }});
    }}).then(function (data) {{
      scanState = data;
      renderCandidates();
    }}).catch(function (err) {{
      setStatus('扫描失败：' + err.message, true);
    }});
  }}

  function applySelection() {{
    if (!scanState) return;
    var selection = currentSelection();
    var params = new URLSearchParams({{
      strict: strictBox.checked ? '1' : '0',
      stem: scanState.stem
    }});
    setStatus('正在转换 ' + scanState.filename + ' …', false);
    applyBtn.disabled = true;

    fetch('/apply/' + scanState.token + '?' + params.toString(), {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(selection)
    }}).then(function (resp) {{
      return resp.json().then(function (data) {{
        if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        return data;
      }});
    }}).then(function (data) {{
      showResult(data);
    }}).catch(function (err) {{
      setStatus('转换失败：' + err.message, true);
    }}).then(function () {{
      updateCount();
    }});
  }}

  function handleFiles(files) {{
    if (!files || !files.length) return;
    var file = files[0];
    if (!/\\.docx$/i.test(file.name)) {{
      setStatus('只支持 .docx 文件：' + file.name, true);
      return;
    }}
    scanFile(file);
  }}

  drop.addEventListener('dragover', function (e) {{ e.preventDefault(); drop.classList.add('drag'); }});
  drop.addEventListener('dragleave', function () {{ drop.classList.remove('drag'); }});
  drop.addEventListener('drop', function (e) {{
    e.preventDefault();
    drop.classList.remove('drag');
    handleFiles(e.dataTransfer.files);
  }});
  drop.addEventListener('click', function () {{ fileInput.click(); }});
  drop.addEventListener('keydown', function (e) {{
    if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); fileInput.click(); }}
  }});
  fileInput.addEventListener('change', function () {{ handleFiles(fileInput.files); }});

  listEl.addEventListener('change', function (e) {{
    if (e.target.classList.contains('candidate-check')) updateCount();
  }});
  document.querySelectorAll('.chip').forEach(function (chip) {{
    chip.addEventListener('click', function () {{ applyPreset(chip.getAttribute('data-preset')); }});
  }});
  applyBtn.addEventListener('click', applySelection);
  resetBtn.addEventListener('click', resetToDropzone);
}})();
</script>
</body>
</html>
"""
