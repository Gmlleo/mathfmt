# Standalone GUI Executable

Build a single double-clickable binary of `mathfmt gui` for people who don't have
Python installed — teachers, students, anyone who just wants to drag a `.docx`
onto a window.

```powershell
pip install -e ".[dev]"
pip install pyinstaller
python packaging/build_exe.py
```

This produces `dist/MathFmt-GUI.exe` (Windows) or `dist/MathFmt-GUI` (macOS/Linux —
build on the target platform; PyInstaller does not cross-compile). Double-clicking
it starts the same local server as `mathfmt gui`, opens the default browser to it,
and prints its URL and stop instructions to the console window. Closing that
console window (or pressing Ctrl+C in it) stops the server, exactly like the CLI
command.

## What this is and isn't

- `gui_entry.py` is a thin wrapper around `mathfmt.gui.serve()` — no source,
  public API, or CLI behavior changes. See `docs/api.md` for the actual stability
  contract; this directory is outside it.
- The build is **not** part of `.github/workflows/publish.yml` — running
  `build_exe.py` and distributing the result (e.g. attaching it to a GitHub
  Release) is a manual, deliberate step, not something a tag push triggers.
- Verify a fresh build on a clean machine (or at least a clean virtual machine)
  before distributing it — PyInstaller bundles what it finds in the *build*
  environment, so a build made from a repo with extra local packages installed
  can silently pull in more than intended.
