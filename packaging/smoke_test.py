"""Smoke-test the standalone MathFmt GUI executable built by ``build_exe.py``.

Launches the built binary, waits for it to bind its local server port, makes
one HTTP request to confirm it actually serves the GUI page from outside the
source checkout, then stops it. This only proves the PyInstaller bundle boots
and serves traffic — it does not exercise the scan/apply flow (see
``tests/test_gui.py`` for that, against the in-process server).

Port discovery goes through ``tasklist``/``netstat`` instead of parsing the
process's own stdout for the printed URL: a frozen console app's stdout is
fully buffered once it's redirected to a pipe rather than a real console, so
its startup ``print()`` can sit unflushed for the life of the process even
though the server underneath is already accepting connections — polling for
the bound port sidesteps that entirely. For the same onefile-bootloader
reason (it re-execs itself, so the process we launch is not always the one
holding the listening socket), cleanup targets every process with the built
executable's name rather than just the ``Popen`` handle's own PID.

Windows-only, matching ``build_exe.py``'s own Windows-first packaging target
and the ``exe-smoke-test`` CI job that runs this on ``windows-latest``.

Usage::

    python packaging/build_exe.py
    python packaging/smoke_test.py
"""

from __future__ import annotations

import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# A frozen onefile executable re-extracts itself on every launch, and a first
# run on a machine that has never seen this exact binary before can also sit
# through several minutes of Defender real-time-protection scanning before
# it's allowed to actually execute — generous on purpose. The CI job excludes
# dist/build from scanning to avoid needing this, but a plain local run does
# not, so the timeout still has to tolerate an unscanned first execution.
STARTUP_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 0.5
PROGRESS_INTERVAL_SECONDS = 15
REQUEST_TIMEOUT_SECONDS = 10


def find_exe() -> Path:
    dist = ROOT / "dist"
    candidates = sorted(p for p in dist.glob("MathFmt-GUI*") if p.suffix != ".spec")
    if not candidates:
        raise SystemExit(f"No built executable found in {dist}. Run packaging/build_exe.py first.")
    return candidates[0]


def _pids_by_name(image_name: str) -> set[int]:
    result = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh", "/fi", f"IMAGENAME eq {image_name}"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        fields = [f.strip('"') for f in line.split(",")]
        if len(fields) >= 2 and fields[0].lower() == image_name.lower():
            try:
                pids.add(int(fields[1]))
            except ValueError:
                continue
    return pids


def _find_listening_port(image_name: str, start: float, deadline: float) -> int | None:
    next_progress = start + PROGRESS_INTERVAL_SECONDS
    while time.monotonic() < deadline:
        pids = _pids_by_name(image_name)
        if pids:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) < 5 or parts[0] != "TCP" or parts[3].upper() != "LISTENING":
                    continue
                try:
                    pid = int(parts[-1])
                except ValueError:
                    continue
                local = parts[1]
                if pid in pids and local.startswith("127.0.0.1:"):
                    return int(local.rsplit(":", 1)[1])
        now = time.monotonic()
        if now >= next_progress:
            state = (
                f"{len(pids)} matching process(es), none listening yet" if pids else "no matching process yet"
            )
            print(f"  ... still waiting after {now - start:.0f}s ({state})")
            next_progress = now + PROGRESS_INTERVAL_SECONDS
        time.sleep(POLL_INTERVAL_SECONDS)
    return None


def _kill_all(image_name: str) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/IM", image_name],
        capture_output=True,
        text=True,
        timeout=10,
    )


def main() -> int:
    exe = find_exe()
    print(f"Launching {exe}")
    # Captured to a real file rather than a pipe: a frozen console app's
    # stdout is fully buffered once redirected somewhere that isn't a real
    # console, so a live pipe read can stay empty for the process's whole
    # life even after it has exited — a file still holds whatever it wrote
    # once we go read it after the fact.
    log_path = ROOT / "packaging" / "smoke_test_exe_output.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen([str(exe)], stdout=log_file, stderr=subprocess.STDOUT)
    try:
        start = time.monotonic()
        port = _find_listening_port(exe.name, start, start + STARTUP_TIMEOUT_SECONDS)
        if port is None:
            output = log_path.read_text(encoding="utf-8", errors="replace")
            raise SystemExit(
                f"No listening MathFmt GUI server (process {exe.name}) found "
                f"within {STARTUP_TIMEOUT_SECONDS}s. proc.poll()={proc.poll()!r}, "
                f"pids matching name now: {sorted(_pids_by_name(exe.name))!r}.\n"
                f"--- {log_path.name} ---\n{output or '(empty)'}\n---"
            )
        url = f"http://127.0.0.1:{port}/"
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read()
            if resp.status != 200 or b"MathFmt" not in body:
                raise SystemExit(f"Unexpected response from {url}: status={resp.status}, {len(body)} bytes")
        print(f"OK: {url} served {len(body)} bytes containing 'MathFmt'.")
        return 0
    finally:
        proc.terminate()
        _kill_all(exe.name)
        log_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
