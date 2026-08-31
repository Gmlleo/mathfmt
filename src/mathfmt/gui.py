"""Local browser drag-and-drop interface for MathFmt.

Launched via ``mathfmt gui``. Starts a plain-stdlib HTTP server bound to localhost,
opens the default browser, and serves a single self-contained page: drop a ``.docx``
onto it (or click to choose one) and MathFmt converts it in place using the same
conservative pipeline as ``mathfmt convert`` (scan, filter by confidence, apply).

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

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_MAX_UPLOAD_BYTES = 128 * 1024 * 1024
_SESSION_TTL_SECONDS = 30 * 60
_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class _SessionStore:
    """Maps a random download token to a private per-upload temp directory."""

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
        if urlsplit(self.path).path == "/convert":
            self._handle_convert()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_convert(self) -> None:
        params = parse_qs(urlsplit(self.path).query)
        filename = (params.get("filename", [""])[0] or "upload.docx").strip()
        confidence = (params.get("confidence", ["high"])[0] or "high").lower()
        if confidence not in _CONFIDENCE_ORDER:
            confidence = "high"
        strict = params.get("strict", ["0"])[0] == "1"

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
            payload = self._convert(session_dir, input_path, filename, confidence, strict)
        except Exception as exc:  # surface any conversion failure to the page instead of a 500 traceback
            shutil.rmtree(session_dir, ignore_errors=True)
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc) or exc.__class__.__name__)
            return
        self._json_response(HTTPStatus.OK, payload)

    def _read_content_length(self) -> int | None:
        header = self.headers.get("Content-Length")
        try:
            length = int(header) if header is not None else 0
        except ValueError:
            length = 0
        if length <= 0:
            self.close_connection = True
            self._json_error(HTTPStatus.LENGTH_REQUIRED, "缺少或无效的上传内容")
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

    def _convert(
        self,
        session_dir: Path,
        input_path: Path,
        filename: str,
        confidence: str,
        strict: bool,
    ) -> dict[str, object]:
        review_path = session_dir / "candidates.json"
        output_path = session_dir / "output.docx"
        result_path = session_dir / "result.json"

        scan = scan_docx(input_path, review_path)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        min_level = _CONFIDENCE_ORDER[confidence]
        filtered_out = 0
        for candidate in review.get("candidates", []):
            level = _CONFIDENCE_ORDER.get(candidate.get("confidence"), 2)
            if level > min_level:
                candidate["selected"] = False
                filtered_out += 1
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
        token = self.server.sessions.store(session_dir)
        stem = Path(filename).stem or "output"
        return {
            "candidates": scan["summary"]["candidates"],
            "filtered_by_confidence": filtered_out,
            "converted": result["converted_count"],
            "skipped": result["skipped_count"],
            "skipped_items": skipped_items,
            "strict_failed": strict_failed,
            "output_available": output_path.is_file() and not strict_failed,
            "token": token,
            "output_name": f"{stem}.mathfmt.docx",
            "report_name": f"{stem}.mathfmt.report.json",
        }

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
  main {{ width: 100%; max-width: 640px; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
  .sub {{ color: #666; margin: 0 0 1.75rem; font-size: .9rem; }}
  #drop {{
    border: 2px dashed #b8b2a4; border-radius: 14px; padding: 3rem 1.5rem; text-align: center;
    cursor: pointer; background: #fff; transition: border-color .15s, background .15s;
  }}
  #drop.drag {{ border-color: #6b5bd6; background: #f1eefb; }}
  #drop p {{ margin: 0; color: #444; }}
  #drop .hint {{ font-size: .8rem; color: #999; margin-top: .5rem; }}
  #options {{ display: flex; gap: 1.25rem; align-items: center; margin: 1rem 0; font-size: .85rem; flex-wrap: wrap; }}
  #status {{ margin: 1rem 0; padding: .6rem .9rem; border-radius: 8px; background: #eef1ff; font-size: .9rem; }}
  #status.error {{ background: #fde8e8; color: #a12222; }}
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
    #result {{ background: #23242c; border-color: #35374a; }}
    #result b {{ color: #fff; }}
    #skipped code {{ background: #2d2f38; }}
    .btn.secondary {{ background: #2d2a45; color: #c9c0ff; }}
  }}
</style>
</head>
<body>
<main>
  <h1>MathFmt</h1>
  <p class="sub">把纯文本公式转换成 Word 原生公式 — 拖进来即可，无需终端命令。</p>

  <div id="drop" tabindex="0">
    <p>将 .docx 文件拖到这里，或点击选择文件</p>
    <p class="hint">文件只在本机处理，不会上传到互联网</p>
    <input type="file" id="file-input" accept=".docx" hidden>
  </div>

  <div id="options">
    <label>置信度
      <select id="confidence">
        <option value="high" selected>高（保守，推荐）</option>
        <option value="medium">中</option>
        <option value="all">全部</option>
      </select>
    </label>
    <label><input type="checkbox" id="strict"> 严格模式（任一公式失败则不写出文件）</label>
  </div>

  <div id="status" hidden></div>
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
  var resultEl = document.getElementById('result');
  var statsEl = document.getElementById('stats');
  var skippedEl = document.getElementById('skipped');
  var downloadDocx = document.getElementById('download-docx');
  var downloadReport = document.getElementById('download-report');

  function escapeHtml(text) {{
    var div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }}

  function setStatus(message, isError) {{
    statusEl.hidden = false;
    statusEl.textContent = message;
    statusEl.className = isError ? 'error' : '';
  }}

  function showResult(data, filename) {{
    resultEl.hidden = false;
    var parts = [
      '发现候选公式 <b>' + data.candidates + '</b> 个',
      '转换成功 <b>' + data.converted + '</b> 个',
      '跳过 <b>' + data.skipped + '</b> 个'
    ];
    if (data.filtered_by_confidence) {{
      parts.push('因置信度过滤 <b>' + data.filtered_by_confidence + '</b> 个（未尝试）');
    }}
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
      setStatus('严格模式：存在失败的公式，未写出文件（' + filename + '）', true);
    }} else {{
      setStatus('转换完成：' + filename, false);
    }}
  }}

  function handleFiles(files) {{
    if (!files || !files.length) return;
    var file = files[0];
    if (!/\\.docx$/i.test(file.name)) {{
      setStatus('只支持 .docx 文件：' + file.name, true);
      return;
    }}
    resultEl.hidden = true;
    setStatus('正在转换 ' + file.name + ' …', false);

    var confidence = document.getElementById('confidence').value;
    var strict = document.getElementById('strict').checked ? '1' : '0';
    var params = new URLSearchParams({{ filename: file.name, confidence: confidence, strict: strict }});

    fetch('/convert?' + params.toString(), {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/octet-stream' }},
      body: file
    }}).then(function (resp) {{
      return resp.json().then(function (data) {{
        if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        return data;
      }});
    }}).then(function (data) {{
      showResult(data, file.name);
    }}).catch(function (err) {{
      setStatus('转换失败：' + err.message, true);
    }});
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
}})();
</script>
</body>
</html>
"""
