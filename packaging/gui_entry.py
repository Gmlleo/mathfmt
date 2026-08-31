"""Entry point for the standalone MathFmt GUI executable.

Built with PyInstaller (see ``build_exe.py`` in this directory). This is a thin
wrapper around :func:`mathfmt.gui.serve` so people who don't have Python installed
can get the drag-and-drop GUI as a single double-clickable file — no ``pip install``
required.

Behavior is identical to running ``mathfmt gui`` from an editable/pip install: a
local server binds to 127.0.0.1, the default browser opens automatically, and
closing the console window (or pressing Ctrl+C in it) stops the server.
"""

from __future__ import annotations

from mathfmt.core import find_xsl
from mathfmt.gui import serve


def main() -> None:
    try:
        xsl_path = find_xsl()
    except FileNotFoundError:
        xsl_path = None
    serve(xsl_path=xsl_path)


if __name__ == "__main__":
    main()
