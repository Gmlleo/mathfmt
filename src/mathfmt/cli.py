"""Command-line interface for MathFmt."""

from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from lxml import etree

from . import __version__
from .aliases import AliasProfile, load_alias_profile
from .core import apply_docx, find_xsl, scan_docx
from .plugins import FormulaRecognizer, load_recognizer, recognizers_metadata
from .update import check_for_updates
from .validate import validate_docx


def default_output(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.mathfmt.docx")


def default_result_report(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.report.json")


def load_recognizers(specs: Sequence[str]) -> tuple[FormulaRecognizer, ...]:
    """Load ordered CLI recognizer specifications."""
    return tuple(load_recognizer(spec) for spec in specs)


def _contains_glob(path: Path) -> bool:
    return any(character in str(path) for character in "*?[")


def expand_convert_inputs(inputs: Sequence[Path], *, recursive: bool = False) -> tuple[list[Path], bool]:
    """Expand convert inputs deterministically while preserving single-file behavior."""
    expanded: list[Path] = []
    batch_requested = len(inputs) > 1

    for value in inputs:
        if _contains_glob(value):
            batch_requested = True
            matches = [Path(match) for match in glob.glob(str(value), recursive=True)]
            if not matches:
                raise FileNotFoundError(f"Input pattern matched no files: {value}")
            expanded.extend(path for path in matches if path.is_file())
            continue

        if value.is_dir():
            batch_requested = True
            iterator = value.rglob("*.docx") if recursive else value.glob("*.docx")
            expanded.extend(path for path in iterator if not path.name.casefold().endswith(".mathfmt.docx"))
            continue

        if not value.is_file():
            raise FileNotFoundError(f"Input DOCX was not found: {value}")
        expanded.append(value)

    unique: dict[str, Path] = {}
    for path in sorted(expanded, key=lambda candidate: str(candidate).casefold()):
        if path.suffix.casefold() != ".docx":
            raise ValueError(f"Input must be a .docx file: {path}")
        key = os.path.normcase(str(path.resolve()))
        unique.setdefault(key, path)

    if not unique:
        raise FileNotFoundError("No DOCX files matched the requested inputs")
    return list(unique.values()), batch_requested


def _convert_paths(
    sources: Sequence[Path],
    *,
    batch_requested: bool,
    output: Path | None,
    output_dir: Path | None,
    report: Path | None,
    report_dir: Path | None,
) -> list[tuple[Path, Path, Path]]:
    if batch_requested and output is not None:
        raise ValueError("--output can only be used with one explicit input; use --output-dir for batches")
    if batch_requested and report is not None:
        raise ValueError("--report can only be used with one explicit input; use --report-dir for batches")

    planned: list[tuple[Path, Path, Path]] = []
    for source in sources:
        output_path = output or default_output(source)
        if output_dir is not None:
            output_path = output_dir / default_output(source).name
        report_path = report or default_result_report(output_path)
        if report_dir is not None:
            report_path = report_dir / default_result_report(output_path).name
        planned.append((source, output_path, report_path))

    source_keys = {os.path.normcase(str(source.resolve())) for source in sources}
    output_keys: set[str] = set()
    report_keys: set[str] = set()
    for source, output_path, report_path in planned:
        output_key = os.path.normcase(str(output_path.resolve()))
        report_key = os.path.normcase(str(report_path.resolve()))
        if output_key in source_keys:
            raise ValueError(f"Refusing to overwrite a batch input DOCX: {output_path}")
        if output_key in output_keys:
            raise ValueError(f"Multiple inputs map to the same output DOCX: {output_path}")
        if report_key in report_keys:
            raise ValueError(f"Multiple inputs map to the same result report: {report_path}")
        output_keys.add(output_key)
        report_keys.add(report_key)
    return planned


def run_gui(args: argparse.Namespace) -> int:
    from .gui import serve  # imported lazily: http.server/webbrowser are only needed here

    if args.xsl is not None:
        xsl_path = find_xsl(args.xsl)
    else:
        try:
            xsl_path = find_xsl()
        except FileNotFoundError:
            xsl_path = None
    serve(host=args.host, port=args.port, xsl_path=xsl_path, open_browser=not args.no_browser)
    return 0


def doctor_data(explicit_xsl: Path | None = None) -> dict[str, object]:
    data: dict[str, object] = {
        "mathfmt": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "windows": os.name == "nt",
        "lxml": etree.LXML_VERSION,
        "libxml2": etree.LIBXML_VERSION,
        "libxslt": etree.LIBXSLT_VERSION,
        "xsl": None,
        "backend": "python",
        "ready": True,
    }
    try:
        data["xsl"] = str(find_xsl(explicit_xsl).resolve())
        data["backend"] = "office-xsl"
    except FileNotFoundError:
        pass
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mathfmt",
        description="Typeset plain-text DOCX formulas as native Word equations.",
    )
    parser.add_argument("--version", action="version", version=f"MathFmt {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="create a reviewable formula candidate report")
    scan.add_argument("input", type=Path)
    scan.add_argument("--report", type=Path, required=True)
    scan.add_argument("--aliases", type=Path, help="JSON symbol alias profile")
    scan.add_argument(
        "--recognizer",
        action="append",
        default=[],
        metavar="MODULE:OBJECT",
        help="trusted custom formula recognizer (repeatable; evaluated in order)",
    )

    apply = subparsers.add_parser("apply", help="apply a reviewed candidate report")
    apply.add_argument("input", type=Path)
    apply.add_argument("--review", type=Path, required=True)
    apply.add_argument("--output", "--out", dest="output", type=Path)
    apply.add_argument("--report", type=Path, required=True)
    apply.add_argument("--aliases", type=Path, help="JSON symbol alias profile used during scan")
    apply.add_argument("--dry-run", action="store_true", help="preview changes without writing a DOCX")
    apply.add_argument(
        "--strict", action="store_true", help="do not write output if any selected formula fails"
    )
    apply.add_argument(
        "--xsl",
        type=Path,
        help=(
            "path to MML2OMML.XSL (optional; Office's XSL is auto-detected and preferred "
            "on a machine that has it, otherwise the built-in Python backend is used)"
        ),
    )

    convert = subparsers.add_parser("convert", help="conservatively convert detected formulas in one step")
    convert.add_argument("input", nargs="+", type=Path, help="DOCX files, directories, or glob patterns")
    convert.add_argument("--output", "--out", dest="output", type=Path)
    convert.add_argument("--output-dir", type=Path, help="write batch DOCX outputs into this directory")
    convert.add_argument("--report", type=Path)
    convert.add_argument("--report-dir", type=Path, help="write per-file reports into this directory")
    convert.add_argument("--batch-report", type=Path, help="write an aggregate JSON batch report")
    convert.add_argument(
        "--recursive", action="store_true", help="search input directories recursively for DOCX files"
    )
    convert.add_argument("--xsl", type=Path)
    convert.add_argument("--aliases", type=Path, help="JSON symbol alias profile")
    convert.add_argument(
        "--recognizer",
        action="append",
        default=[],
        metavar="MODULE:OBJECT",
        help="trusted custom formula recognizer (repeatable; evaluated in order)",
    )
    convert.add_argument(
        "--confidence",
        choices=["high", "medium", "all"],
        default="high",
        help="minimum confidence level to convert (default: high)",
    )
    convert.add_argument(
        "--strict", action="store_true", help="do not write output if any selected formula fails"
    )

    gui = subparsers.add_parser(
        "gui", help="launch a local browser drag-and-drop interface (no other commands needed)"
    )
    gui.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1, local only)")
    gui.add_argument("--port", type=int, default=0, help="port to bind (default: 0, pick a free port)")
    gui.add_argument("--no-browser", action="store_true", help="do not automatically open a browser tab")
    gui.add_argument(
        "--xsl",
        type=Path,
        help=(
            "path to MML2OMML.XSL (optional; Office's XSL is auto-detected and preferred "
            "on a machine that has it, otherwise the built-in Python backend is used)"
        ),
    )

    doctor = subparsers.add_parser("doctor", help="check the local MathFmt environment")
    doctor.add_argument("--xsl", type=Path)
    doctor.add_argument("--json", action="store_true", dest="as_json")

    validate = subparsers.add_parser("validate", help="validate DOCX structure and OMML equations offline")
    validate.add_argument("input", type=Path)
    validate.add_argument("--report", type=Path)
    validate.add_argument("--review", type=Path, help="path to candidates.json for formula coverage check")
    validate.add_argument("--xsl", type=Path, help="path to MML2OMML.XSL for cross-backend comparison")
    validate.add_argument("--aliases", type=Path, help="JSON symbol alias profile used during scan")
    validate.add_argument(
        "--compatibility",
        choices=["wps"],
        help="run an offline compatibility profile in addition to structural validation",
    )

    update = subparsers.add_parser("update", help="check for newer MathFmt releases on GitHub")
    update.add_argument(
        "--check", action="store_true", help="only check; exit 0 if up-to-date, exit 1 if update available"
    )
    update.add_argument(
        "--pre", action="store_true", dest="include_prerelease", help="include pre-release versions"
    )
    update.add_argument("--force", action="store_true", help="bypass cache and re-check GitHub immediately")
    return parser


def _convert_one(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    *,
    confidence: str,
    strict: bool,
    xsl: Path | None,
    alias_profile: AliasProfile | None,
    recognizers: Sequence[FormulaRecognizer],
) -> tuple[dict[str, object], dict[str, object], int]:
    with tempfile.TemporaryDirectory(prefix="mathfmt-") as temp_dir:
        review_path = Path(temp_dir) / "candidates.json"
        scan = scan_docx(
            input_path,
            review_path,
            alias_profile=alias_profile,
            recognizers=recognizers,
        )
        if confidence != "all":
            review = json.loads(review_path.read_text(encoding="utf-8"))
            confidence_order = {"high": 0, "medium": 1, "low": 2}
            min_level = confidence_order[confidence]
            for c in review.get("candidates", []):
                c_level = confidence_order.get(c.get("confidence"), 2)
                if c_level > min_level:
                    c["selected"] = False
            review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        result = apply_docx(
            input_path,
            review_path,
            output_path,
            report_path,
            xsl,
            command_name="convert",
            strict=strict,
            alias_profile=alias_profile,
        )
    if result.get("summary", {}).get("strict_failed"):
        code = 1
    else:
        code = 0 if result["skipped_count"] == 0 else 2
    return scan, result, code


def run_convert(args: argparse.Namespace) -> int:
    sources, batch_requested = expand_convert_inputs(args.input, recursive=args.recursive)
    planned = _convert_paths(
        sources,
        batch_requested=batch_requested,
        output=args.output,
        output_dir=args.output_dir,
        report=args.report,
        report_dir=args.report_dir,
    )
    alias_profile = load_alias_profile(args.aliases) if args.aliases is not None else None
    recognizers = load_recognizers(args.recognizer)
    if args.xsl is not None:
        xsl = find_xsl(args.xsl)
    else:
        try:
            xsl = find_xsl()
        except FileNotFoundError:
            xsl = None

    if not batch_requested and len(planned) == 1:
        input_path, output, report_path = planned[0]
        scan, result, code = _convert_one(
            input_path,
            output,
            report_path,
            confidence=args.confidence,
            strict=args.strict,
            xsl=xsl,
            alias_profile=alias_profile,
            recognizers=recognizers,
        )
        print(f"Candidates: {scan['summary']['candidates']}")
        print(f"Converted: {result['converted_count']}")
        print(f"Skipped: {result['skipped_count']}")
        print(f"Output: {output}")
        print(f"Report: {report_path}")
        return code

    items: list[dict[str, object]] = []
    failed = 0
    partial = 0
    converted_total = 0
    skipped_total = 0
    for index, (input_path, output, report_path) in enumerate(planned, start=1):
        print(f"[{index}/{len(planned)}] {input_path}")
        try:
            scan, result, code = _convert_one(
                input_path,
                output,
                report_path,
                confidence=args.confidence,
                strict=args.strict,
                xsl=xsl,
                alias_profile=alias_profile,
                recognizers=recognizers,
            )
            converted_count = int(result["converted_count"])
            skipped_count = int(result["skipped_count"])
            converted_total += converted_count
            skipped_total += skipped_count
            status = "failed" if code == 1 else "partial" if code == 2 else "success"
            failed += int(code == 1)
            partial += int(code == 2)
            items.append(
                {
                    "input": str(input_path.resolve()),
                    "output": str(output.resolve()),
                    "report": str(report_path.resolve()),
                    "status": status,
                    "exit_code": code,
                    "candidates": int(scan["summary"]["candidates"]),
                    "converted": converted_count,
                    "skipped": skipped_count,
                    "output_written": bool(result.get("summary", {}).get("output_written")),
                }
            )
            print(f"  {status}: converted={converted_count}, skipped={skipped_count}")
        except (OSError, ValueError, json.JSONDecodeError, etree.XMLSyntaxError, zipfile.BadZipFile) as exc:
            failed += 1
            items.append(
                {
                    "input": str(input_path.resolve()),
                    "output": str(output.resolve()),
                    "report": str(report_path.resolve()),
                    "status": "failed",
                    "exit_code": 1,
                    "error": str(exc),
                    "output_written": False,
                }
            )
            print(f"  failed: {exc}", file=sys.stderr)

    batch_report = {
        "schema_version": 1,
        "report_type": "batch_conversion",
        "mathfmt": __version__,
        "command": {"name": "convert"},
        "inputs": [str(source.resolve()) for source in sources],
        "options": {
            "recursive": args.recursive,
            "confidence": args.confidence,
            "strict": args.strict,
            "backend": "office-xsl" if xsl is not None else "python",
            "alias_profile": alias_profile.metadata() if alias_profile is not None else None,
            "recognizers": recognizers_metadata(recognizers),
            "output_dir": str(args.output_dir.resolve()) if args.output_dir is not None else None,
            "report_dir": str(args.report_dir.resolve()) if args.report_dir is not None else None,
        },
        "summary": {
            "files": len(items),
            "succeeded": len(items) - failed - partial,
            "partial": partial,
            "failed": failed,
            "converted": converted_total,
            "skipped": skipped_total,
        },
        "files": items,
    }
    if args.batch_report is not None:
        args.batch_report.parent.mkdir(parents=True, exist_ok=True)
        args.batch_report.write_text(json.dumps(batch_report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Batch report: {args.batch_report}")
    print(
        f"Batch summary: files={len(items)}, succeeded={len(items) - failed - partial}, "
        f"partial={partial}, failed={failed}, converted={converted_total}, skipped={skipped_total}"
    )
    if failed:
        return 1
    if partial:
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scan":
            alias_profile = load_alias_profile(args.aliases) if args.aliases is not None else None
            recognizers = load_recognizers(args.recognizer)
            report = scan_docx(
                args.input,
                args.report,
                alias_profile=alias_profile,
                recognizers=recognizers,
            )
            print(f"Candidates: {report['summary']['candidates']}")
            print(f"Report: {args.report}")
            return 0
        if args.command == "apply":
            if args.output is None and not args.dry_run:
                raise ValueError("apply requires --output unless --dry-run is used")
            output = args.output or default_output(args.input)
            alias_profile = load_alias_profile(args.aliases) if args.aliases is not None else None
            if args.xsl is not None:
                xsl_path = find_xsl(args.xsl)
            else:
                try:
                    xsl_path = find_xsl()
                except FileNotFoundError:
                    xsl_path = None
            result = apply_docx(
                args.input,
                args.review,
                output,
                args.report,
                xsl_path,
                dry_run=args.dry_run,
                strict=args.strict,
                alias_profile=alias_profile,
            )
            print(f"Converted: {result['converted_count']}")
            print(f"Skipped: {result['skipped_count']}")
            if args.dry_run:
                print(f"Output: {output} (dry-run, not written)")
            else:
                print(f"Output: {output}")
            print(f"Report: {args.report}")
            if result.get("summary", {}).get("strict_failed"):
                return 1
            return 0 if result["skipped_count"] == 0 else 2
        if args.command == "convert":
            return run_convert(args)
        if args.command == "gui":
            return run_gui(args)
        if args.command == "doctor":
            data = doctor_data(args.xsl)
            if args.as_json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print(f"MathFmt: {data['mathfmt']}")
                print(f"Python: {data['python']}")
                print(f"Platform: {data['platform']}")
                print(f"lxml: {'.'.join(str(part) for part in data['lxml'])}")
                print(f"libxml2: {'.'.join(str(part) for part in data['libxml2'])}")
                print(f"libxslt: {'.'.join(str(part) for part in data['libxslt'])}")
                print(f"OMML backend: {data['backend']}")
                if data["xsl"]:
                    print(f"MML2OMML.XSL: {data['xsl']}")
                print(f"Ready: {'yes' if data['ready'] else 'no'}")
            return 0 if data["ready"] else 1
        if args.command == "validate":
            alias_profile = load_alias_profile(args.aliases) if args.aliases is not None else None
            if args.xsl is not None:
                xsl_path = find_xsl(args.xsl)
            else:
                try:
                    xsl_path = find_xsl()
                except FileNotFoundError:
                    xsl_path = None
            report = validate_docx(
                args.input,
                review_path=args.review,
                xsl_path=xsl_path,
                alias_profile=alias_profile,
                compatibility=args.compatibility,
            )
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Report: {args.report}")
            if report["valid"]:
                print("Validation: PASS")
                compatibility = report.get("compatibility")
                if isinstance(compatibility, dict):
                    label = str(compatibility.get("profile", "compatibility")).upper()
                    status = "PASS" if compatibility.get("compatible") else "FAIL"
                    print(f"{label} compatibility: {status}")
                eq_count = (
                    report.get("omml", {}).get("equation_count", 0)
                    if isinstance(report.get("omml"), dict)
                    else 0
                )
                print(f"Equations: {eq_count}")
                return 0
            else:
                print("Validation: FAIL")
                compatibility = report.get("compatibility")
                if isinstance(compatibility, dict):
                    label = str(compatibility.get("profile", "compatibility")).upper()
                    status = "PASS" if compatibility.get("compatible") else "FAIL"
                    print(f"{label} compatibility: {status}")
                oml = report.get("omml", {})
                if isinstance(oml, dict):
                    errors = oml.get("structural_errors", [])
                    if errors:
                        print(f"OMML errors: {len(errors)}")
                return 1
        if args.command == "update":
            info = check_for_updates(
                include_prerelease=getattr(args, "include_prerelease", False),
                force=getattr(args, "force", False),
            )
            print(info.summary)
            if info.is_update_available:
                if info.release_url:
                    print(f"\nRelease: {info.release_url}")
                if info.published_at:
                    print(f"Published: {info.published_at}")
                if info.release_notes:
                    print(f"\n── Release notes ──\n{info.release_notes}")
                print("\nTo update, run one of:")
                for cmd in info.install_commands:
                    print(f"  {cmd}")
            if args.check:
                if info.error:
                    return 2
                return 0 if not info.is_update_available else 1
            return 0 if not info.error else 2
    except (FileNotFoundError, ValueError, json.JSONDecodeError, etree.XMLSyntaxError) as exc:
        print(f"mathfmt: error: {exc}", file=sys.stderr)
        return 1
    except zipfile.BadZipFile as exc:
        print(f"mathfmt: error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
