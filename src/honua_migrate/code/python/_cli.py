"""Command-line entrypoint for the ArcPy -> Honua GP migration codemod.

Usage (either form works once the SDK is installed)::

    honua-migrate scan path/to/script.py
    python -m honua_migrate.code.python scan path/to/script.py
    honua-migrate translate path/to/script.py --evidence out.json
    honua-migrate run path/to/script.py --server https://example.test
    honua-migrate pyt path/to/toolbox.pyt

The ``scan`` and ``translate`` commands work offline (AST-only, no ArcGIS or
network). The ``run`` command executes the translatable steps through
``HonuaClient.ogc_processes().execute(...)`` against ``--server``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .arcpy import (
    ArcPyProcessRunner,
    build_parity_evidence,
    scan_arcpy_file,
    translate_arcpy_report,
)
from .pyt import (
    UnsupportedToolboxError,
    build_pyt_parity_evidence,
    parse_binary_toolbox,
    parse_pyt_file,
)

_BINARY_TOOLBOX_SUFFIXES = {".tbx", ".atbx"}


def _emit(obj: object, *, out: Path | None) -> None:
    text = json.dumps(obj, indent=2, sort_keys=False)
    if out is None:
        print(text)
    else:
        out.write_text(text + "\n", encoding="utf-8")


def _cmd_scan(args: argparse.Namespace) -> int:
    report = scan_arcpy_file(args.path)
    _emit(report.to_dict(), out=args.output)
    if report.syntax_error is not None:
        print(f"syntax error: {report.syntax_error}", file=sys.stderr)
        return 2
    return 0


def _cmd_translate(args: argparse.Namespace) -> int:
    report = scan_arcpy_file(args.path)
    if report.syntax_error is not None:
        print(f"syntax error: {report.syntax_error}", file=sys.stderr)
        return 2
    plan = translate_arcpy_report(report)
    evidence = build_parity_evidence(plan)
    if args.evidence is not None:
        _emit(evidence, out=args.evidence)
        _emit(plan.to_dict(), out=args.output)
    else:
        _emit(plan.to_dict(), out=args.output)

    summary = evidence["summary"]
    print(
        f"coverage: {summary['translatableCalls']}/{summary['totalCalls']} translatable "
        f"({summary['coveragePercent']}%), {summary['manualReviewCalls']} manual-review, "
        f"{summary['unsupportedCalls']} unsupported",
        file=sys.stderr,
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    # Imported lazily so scan/translate/pyt work without httpx/network deps wired.
    from honua_sdk import HonuaClient

    report = scan_arcpy_file(args.path)
    plan = translate_arcpy_report(report)
    # Only execute the steps the reconciled server can job-execute. Supported
    # but non-job-executable tools (manual-review) are reported as skipped.
    runnable = tuple(t for t in plan.translations if t.call.translatable)
    skipped = [c.qualified_name for c in plan.manual_review_calls]
    if not runnable:
        print("no translatable ArcPy calls to execute", file=sys.stderr)
        _emit({"executions": [], "skipped": skipped}, out=args.output)
        return 0

    if args.dry_run:
        _emit(
            {
                "dryRun": True,
                "server": args.server,
                "executions": [t.to_dict() for t in runnable],
                "skipped": skipped,
            },
            out=args.output,
        )
        return 0

    results: list[dict[str, Any]] = []
    with HonuaClient(args.server) as client:
        runner = ArcPyProcessRunner(client)
        for translation in runnable:
            execution = runner.execute(translation)
            results.append(
                {
                    "processId": execution.translation.process_id,
                    "jobProcessId": execution.translation.job_process_id,
                    "qualifiedName": execution.translation.call.qualified_name,
                    "result": execution.result,
                }
            )
    _emit({"server": args.server, "executions": results, "skipped": skipped}, out=args.output)
    return 0


def _cmd_pyt(args: argparse.Namespace) -> int:
    suffix = Path(args.path).suffix.lower()
    if suffix in _BINARY_TOOLBOX_SUFFIXES:
        try:
            parse_binary_toolbox(args.path)
        except UnsupportedToolboxError as exc:
            print(str(exc), file=sys.stderr)
            return 3

    toolbox = parse_pyt_file(args.path)
    if args.evidence is not None:
        _emit(build_pyt_parity_evidence(toolbox), out=args.evidence)
    _emit(toolbox.to_dict(), out=args.output)
    if toolbox.syntax_error is not None:
        print(f"syntax error: {toolbox.syntax_error}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="honua-migrate", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Classify ArcPy calls in a Python script (offline).")
    scan.add_argument("path", type=Path, help="Path to an arcpy .py script.")
    scan.add_argument("--output", type=Path, default=None, help="Write JSON report to this path (default: stdout).")
    scan.set_defaults(func=_cmd_scan)

    translate = sub.add_parser(
        "translate",
        help="Emit OGC Processes payloads + a parity-evidence coverage report (offline).",
    )
    translate.add_argument("path", type=Path, help="Path to an arcpy .py script.")
    translate.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the migration plan JSON here (default: stdout).",
    )
    translate.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="Write the parity-evidence JSON report to this path.",
    )
    translate.set_defaults(func=_cmd_translate)

    run = sub.add_parser("run", help="Execute translatable steps via ArcPyProcessRunner against --server.")
    run.add_argument("path", type=Path, help="Path to an arcpy .py script.")
    run.add_argument("--server", required=True, help="Honua server base URL.")
    run.add_argument("--output", type=Path, default=None, help="Write execution results JSON here (default: stdout).")
    run.add_argument("--dry-run", action="store_true", help="Emit payloads without contacting the server.")
    run.set_defaults(func=_cmd_run)

    pyt = sub.add_parser("pyt", help="Parse a .pyt Python toolbox and classify its tools' GP calls.")
    pyt.add_argument("path", type=Path, help="Path to a .pyt Python toolbox (or .tbx/.atbx to see the stub TODO).")
    pyt.add_argument("--output", type=Path, default=None, help="Write the toolbox JSON here (default: stdout).")
    pyt.add_argument("--evidence", type=Path, default=None, help="Write the aggregated parity-evidence JSON here.")
    pyt.set_defaults(func=_cmd_pyt)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
