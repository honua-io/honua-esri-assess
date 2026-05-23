"""Command-line entry point for honua-esri-assess."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import report as report_module
from .footprint import build_footprint, write_footprint
from .scanners import agol as agol_scanner
from .scanners import filegdb as filegdb_scanner
from .scanners import server as server_scanner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="honua-esri-assess")
    parser.add_argument("--version", action="store_true", help="Print package version and exit.")
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="Scan an Esri backend and emit EsriFootprint.json.")
    scan_sub = scan.add_subparsers(dest="backend")

    agol = scan_sub.add_parser("agol", help="Scan an ArcGIS Online portal (read-only).")
    agol.add_argument(
        "--target",
        required=True,
        help="Portal Sharing REST base URL, e.g. https://example.maps.arcgis.com/sharing/rest",
    )
    agol.add_argument("--output", required=True, type=Path, help="Path to write EsriFootprint.json.")

    server = scan_sub.add_parser("server", help="Scan an ArcGIS Server REST endpoint (read-only).")
    server.add_argument("--target", required=True, help="ArcGIS Server REST base URL.")
    server.add_argument("--output", required=True, type=Path, help="Path to write EsriFootprint.json.")

    filegdb = scan_sub.add_parser("filegdb", help="Inventory a FileGDB on disk (read-only).")
    filegdb.add_argument("--target", required=True, help="Path to the FileGDB or inventory descriptor.")
    filegdb.add_argument("--output", required=True, type=Path, help="Path to write EsriFootprint.json.")

    report = sub.add_parser("report", help="Render an EsriFootprint.json to a Markdown report.")
    report.add_argument("--input", required=True, type=Path, help="Path to EsriFootprint.json.")
    report.add_argument("--output", required=True, type=Path, help="Path to write the Markdown report.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command == "scan":
        return _dispatch_scan(args)
    if args.command == "report":
        return _dispatch_report(args)

    parser.print_help()
    return 0


def _dispatch_scan(args: argparse.Namespace) -> int:
    backend = args.backend
    if backend == "agol":
        return _run_agol(args.target, args.output)
    if backend == "server":
        return _run_server(args.target, args.output)
    if backend == "filegdb":
        return _run_filegdb(args.target, args.output)
    print("error: scan requires a backend (agol|server|filegdb).", file=sys.stderr)
    return 2


def _run_agol(target: str, output: Path) -> int:
    try:
        result = agol_scanner.scan(target)
    except Exception:
        return _emit_typed_failure("AGOL scan failed before producing an inventory.")
    footprint = build_footprint(
        source_kind="arcgis-online",
        target=target,
        inventory=result["inventory"],
        diagnostics=result["diagnostics"],
        portal=result["portal"],
    )
    if not _write_footprint_safely(footprint, output):
        return 1
    _emit_diagnostics_to_stderr(footprint)
    return 0


def _run_server(target: str, output: Path) -> int:
    try:
        result = server_scanner.scan(target)
    except Exception:
        return _emit_typed_failure("ArcGIS Server scan failed before producing an inventory.")
    footprint = build_footprint(
        source_kind="arcgis-server",
        target=target,
        inventory=result["inventory"],
        diagnostics=result["diagnostics"],
        server=result["server"],
    )
    if not _write_footprint_safely(footprint, output):
        return 1
    _emit_diagnostics_to_stderr(footprint)
    return 0


def _run_filegdb(target: str, output: Path) -> int:
    try:
        result = filegdb_scanner.scan(target)
    except Exception:
        return _emit_typed_failure("FileGDB scan failed before producing an inventory.")
    footprint = build_footprint(
        source_kind="filegdb",
        target=Path(target).name,
        inventory=result["inventory"],
        diagnostics=result["diagnostics"],
        filegdb=result["filegdb"],
    )
    if not _write_footprint_safely(footprint, output):
        return 1
    _emit_diagnostics_to_stderr(footprint)
    return 0


def _dispatch_report(args: argparse.Namespace) -> int:
    try:
        footprint = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _emit_typed_failure("Could not load EsriFootprint.json for report rendering.")
    try:
        report_module.write(footprint, args.output)
    except OSError:
        return _emit_typed_failure("Could not write the Markdown report output.")
    return 0


def _write_footprint_safely(footprint: dict, output: Path) -> bool:
    try:
        write_footprint(footprint, output)
    except OSError:
        _emit_typed_failure("Could not write the EsriFootprint.json output.")
        return False
    return True


def _emit_diagnostics_to_stderr(footprint: dict) -> None:
    for diag in footprint.get("diagnostics", []) or []:
        code = diag.get("code", "unknown")
        message = diag.get("message", "")
        scope = diag.get("scope")
        suffix = f" [scope={scope}]" if scope else ""
        print(f"{code}: {message}{suffix}", file=sys.stderr)


def _emit_typed_failure(message: str) -> int:
    print(f"partial-coverage: {message}", file=sys.stderr)
    return 1
