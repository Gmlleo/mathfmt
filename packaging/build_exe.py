"""Build a standalone single-file MathFmt GUI executable with PyInstaller.

Usage::

    pip install -e ".[dev]"
    pip install pyinstaller
    python packaging/build_exe.py

Produces ``dist/MathFmt-GUI`` (``dist/MathFmt-GUI.exe`` on Windows) — a
double-clickable binary that needs no Python install on the machine that runs it.
MathFmt itself (and its ``lxml`` dependency) must be importable in the environment
that *builds* it, since PyInstaller bundles whatever it can import from there; an
editable install satisfies this.

This script is a packaging convenience only — it does not change MathFmt's source,
public API, or CLI, and is not part of the automated release pipeline
(``.github/workflows/publish.yml``). Build and test the executable locally, or wire
it into a workflow yourself, before distributing it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = Path(__file__).resolve().parent / "gui_entry.py"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: pip install pyinstaller", file=sys.stderr)
        return 1

    try:
        import mathfmt  # noqa: F401
    except ImportError:
        print('mathfmt is not importable here. Run: pip install -e ".[dev]"', file=sys.stderr)
        return 1

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "MathFmt-GUI",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
        "--clean",
        "--noconfirm",
        str(ENTRY),
    ]
    print("Running:", " ".join(args))
    return subprocess.call(args)


if __name__ == "__main__":
    raise SystemExit(main())
