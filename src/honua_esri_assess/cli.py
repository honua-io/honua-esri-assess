"""Command-line entry point for honua-esri-assess."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .diagnostics import (
    AssessmentError,
    ReportInputError,
    ReportRenderError,
    ReportSchemaValidationError,
)
from .entitlements import (
    EntitlementsApiError,
    EntitlementsAuthError,
    EntitlementsConnectionError,
    EntitlementsError,
    EntitlementsForbiddenError,
    EntitlementsNotFoundError,
    EntitlementsRateLimitedError,
    EntitlementsSchemaError,
    LicensingFacet,
    PortalEntitlementsCollector,
    RequestsHttpClient,
    ServerEntitlementsCollector,
    ServiceRef,
)
from .footprint import (
    build_footprint,
    footprint_to_json,
    licensing_facet_to_dict,
    write_footprint,
    write_footprint_json,
)
from .report import RenderOptions, render
from .report.validation import validate_footprint_v01
from .scanners import agol as agol_scanner
from .scanners import filegdb as filegdb_scanner
from .scanners import server as server_scanner


_LOG = logging.getLogger("honua_esri_assess")

_EXIT_USAGE = 2
_EXIT_ENTITLEMENTS_TYPED = 3
_EXIT_GENERIC = 1


@dataclass(frozen=True)
class _EntitlementsOutput:
    facet: LicensingFacet
    diagnostics: list[dict[str, object]] = field(default_factory=list)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="honua-esri-assess")
    parser.add_argument(
        "--version", action="store_true", help="Print package version and exit."
    )
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser(
        "scan", help="Scan an Esri backend and emit EsriFootprint.json."
    )
    scan_sub = scan.add_subparsers(dest="backend")

    agol = scan_sub.add_parser(
        "agol", help="Scan an ArcGIS Online portal (read-only)."
    )
    agol.add_argument(
        "--target",
        required=True,
        help=(
            "Portal Sharing REST base URL, "
            "e.g. https://example.maps.arcgis.com/sharing/rest"
        ),
    )
    agol.add_argument(
        "--output", required=True, type=Path, help="Path to write EsriFootprint.json."
    )

    server = scan_sub.add_parser(
        "server", help="Scan an ArcGIS Server REST endpoint (read-only)."
    )
    server.add_argument("--target", required=True, help="ArcGIS Server REST base URL.")
    server.add_argument(
        "--output", required=True, type=Path, help="Path to write EsriFootprint.json."
    )

    filegdb_scan = scan_sub.add_parser(
        "filegdb", help="Inventory a FileGDB on disk (read-only)."
    )
    filegdb_scan.add_argument(
        "--target", required=True, help="Path to the FileGDB or inventory descriptor."
    )
    filegdb_scan.add_argument(
        "--output", required=True, type=Path, help="Path to write EsriFootprint.json."
    )

    filegdb = subparsers.add_parser(
        "filegdb",
        help="Scan a local FileGDB workspace and emit EsriFootprint.json.",
    )
    filegdb.add_argument("workspace", help="Local .gdb directory to scan read-only.")
    filegdb.add_argument(
        "-o",
        "--output",
        default="EsriFootprint.json",
        help="Output path for the footprint JSON, or '-' for stdout.",
    )
    filegdb.add_argument(
        "--path-hash-salt",
        default=os.environ.get("HONUA_ESRI_ASSESS_PATH_HASH_SALT"),
        help=(
            "Salt for the prospect-safe FileGDB path hash. Defaults to "
            "HONUA_ESRI_ASSESS_PATH_HASH_SALT; if unset, a per-run random salt is used."
        ),
    )
    filegdb.add_argument(
        "--force-feature-count",
        action="store_true",
        help="Ask the read-only backend to calculate feature counts even when expensive.",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Render a Markdown readiness report from an EsriFootprint.json file.",
    )
    report_parser.add_argument(
        "--input", required=True, help="Path to EsriFootprint.json, or - for stdin."
    )
    report_parser.add_argument(
        "--output", default="-", help="Output Markdown path, or - for stdout."
    )
    report_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if schema validation reports an invalid EsriFootprint v0.1 input.",
    )
    report_parser.add_argument(
        "--verbose", action="store_true", help="Enable info logging."
    )
    report_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging and tracebacks. Do not enable in customer-facing runs.",
    )

    ent = subparsers.add_parser(
        "entitlements",
        help="Enumerate Esri license entitlements as a facet-compatible JSON fragment.",
    )
    ent_subs = ent.add_subparsers(dest="target_kind")

    ent_agol = ent_subs.add_parser(
        "agol",
        help="Enumerate AGOL / Enterprise Portal entitlements via Sharing API.",
    )
    _add_entitlement_common_flags(ent_agol)
    ent_agol.add_argument(
        "--target",
        required=True,
        help="Portal base URL, e.g. https://www.arcgis.com.",
    )
    ent_agol.add_argument(
        "--anonymous",
        action="store_true",
        help="Skip token-required endpoints and emit missing-permission diagnostics.",
    )

    ent_server = ent_subs.add_parser(
        "server",
        help="Enumerate ArcGIS Server entitlements via REST/admin endpoints.",
    )
    _add_entitlement_common_flags(ent_server)
    ent_server.add_argument(
        "--target",
        required=True,
        help="ArcGIS Server base URL, e.g. https://example.com/arcgis.",
    )
    ent_server.add_argument(
        "--no-service-extensions",
        action="store_true",
        help="Skip per-service SOE/SOI enumeration.",
    )
    ent_server.add_argument(
        "--service",
        action="append",
        default=[],
        type=_parse_service_ref,
        metavar="FOLDER/NAME.TYPE",
        help=(
            "Specific service to enumerate (repeatable). Folder is optional. "
            "Example: 'Hosted/Parcels.MapServer' or 'World.MapServer'."
        ),
    )

    return parser


def _add_entitlement_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--token", help="Optional token used for admin / org endpoints.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30).",
    )
    parser.add_argument("--verbose", action="store_true", help="Log at INFO level.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Log at DEBUG level and emit raw tracebacks on hard failures. "
            "Do not enable in customer-facing runs."
        ),
    )


def configure_logging(*, verbose: bool, debug: bool) -> None:
    level = logging.WARNING
    if verbose:
        level = logging.INFO
    if debug:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else _EXIT_USAGE

    if args.version:
        print(__version__)
        return 0

    try:
        if args.command == "scan":
            return _dispatch_scan(args)
        if args.command == "filegdb":
            return _run_filegdb_workspace(
                args.workspace,
                args.output,
                path_hash_salt=args.path_hash_salt,
                force_feature_count=args.force_feature_count,
            )
        if args.command == "report":
            return _dispatch_report(args)
        if args.command == "entitlements":
            return _dispatch_entitlements(args)

        parser.print_help()
        return 0
    except AssessmentError as exc:
        _print_assessment_error(exc, debug=getattr(args, "debug", False))
        return exc.exit_code
    except Exception:
        if getattr(args, "command", None) == "report":
            error = ReportRenderError("Unexpected renderer failure.")
            _print_assessment_error(error, debug=getattr(args, "debug", False))
            return error.exit_code
        return _emit_typed_failure("Unexpected assessment failure before producing an output.")


def _dispatch_scan(args: argparse.Namespace) -> int:
    backend = args.backend
    if backend == "agol":
        return _run_agol(args.target, args.output)
    if backend == "server":
        return _run_server(args.target, args.output)
    if backend == "filegdb":
        return _run_filegdb_descriptor(args.target, args.output)
    print("error: scan requires a backend (agol|server|filegdb).", file=sys.stderr)
    return _EXIT_USAGE


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
        return _EXIT_GENERIC
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
        return _EXIT_GENERIC
    _emit_diagnostics_to_stderr(footprint)
    return 0


def _run_filegdb_descriptor(target: str, output: Path) -> int:
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
        return _EXIT_GENERIC
    _emit_diagnostics_to_stderr(footprint)
    return 0


def _run_filegdb_workspace(
    workspace: str,
    output: str | Path,
    *,
    path_hash_salt: str | None,
    force_feature_count: bool,
) -> int:
    from .filegdb import FileGdbScanOptions, scan_filegdb_workspace

    options = FileGdbScanOptions(
        path_hash_salt=path_hash_salt,
        force_feature_count=force_feature_count,
    )
    try:
        footprint = scan_filegdb_workspace(workspace, options=options)
    except Exception:
        return _emit_typed_error(
            "FileGDB scan failed before a footprint could be written.",
            status=2,
        )

    if str(output) == "-":
        print(footprint_to_json(footprint), end="")
    else:
        try:
            write_footprint_json(footprint, Path(output))
        except OSError:
            return _emit_typed_error(
                "Could not write EsriFootprint.json output.",
                status=2,
            )

    _emit_diagnostics_to_stderr(footprint)
    has_error = any(
        diagnostic.get("severity") == "error"
        for diagnostic in footprint.get("diagnostics", [])
        if isinstance(diagnostic, dict)
    )
    return 1 if has_error else 0


def _dispatch_report(args: argparse.Namespace) -> int:
    _configure_report_logging(args)
    footprint = _read_footprint(args.input)
    validation_issues = validate_footprint_v01(footprint)
    validation_failures = [issue for issue in validation_issues if issue.is_failure]
    if args.strict and validation_failures:
        first = validation_failures[0]
        raise ReportSchemaValidationError(
            first.message,
            context={"path": args.input, "pointer": first.pointer},
        )

    warnings = tuple(issue.message for issue in validation_issues)
    markdown = render(footprint, options=RenderOptions(schema_warnings=warnings))
    _write_report(args.output, markdown)
    return 0


def _read_footprint(path_arg: str) -> dict[str, Any]:
    display_path = "stdin" if path_arg == "-" else "input file"
    try:
        if path_arg == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(path_arg).read_text(encoding="utf-8")
    except OSError:
        raise ReportInputError(
            f"Unable to read input footprint from {display_path}.",
            code="report.input.read",
            context={"path": display_path, "phase": "read"},
        ) from None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReportInputError(
            f"Input footprint is not valid JSON at line {exc.lineno}, column {exc.colno}.",
            code="report.input.parse",
            context={"path": display_path, "phase": "parse"},
        ) from None

    if not isinstance(parsed, dict):
        raise ReportInputError(
            "Input footprint JSON must be an object.",
            code="report.input.parse",
            context={"path": display_path, "phase": "parse"},
        )
    return parsed


def _write_report(path_arg: str, markdown: str) -> None:
    display_path = "stdout" if path_arg == "-" else "output file"
    try:
        if path_arg == "-":
            sys.stdout.write(markdown)
        else:
            Path(path_arg).write_text(markdown, encoding="utf-8")
    except OSError:
        raise ReportInputError(
            f"Unable to write readiness report to {display_path}.",
            code="report.input.write",
            context={"path": display_path, "phase": "write"},
        ) from None


def _configure_report_logging(args: argparse.Namespace) -> None:
    level = logging.WARNING
    if getattr(args, "debug", False):
        level = logging.DEBUG
    elif getattr(args, "verbose", False):
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _print_assessment_error(exc: AssessmentError, *, debug: bool) -> None:
    print(f"error: [{exc.code}] {exc.message}", file=sys.stderr)
    if debug:
        traceback.print_exc()


def _write_footprint_safely(footprint: dict[str, Any], output: Path) -> bool:
    try:
        write_footprint(footprint, output)
    except OSError:
        _emit_typed_failure("Could not write the EsriFootprint.json output.")
        return False
    return True


def _emit_diagnostics_to_stderr(footprint: dict[str, Any]) -> None:
    for diag in footprint.get("diagnostics", []) or []:
        if not isinstance(diag, dict):
            continue
        code = diag.get("code", "unknown")
        message = diag.get("message", "")
        scope = diag.get("scope")
        suffix = f" [scope={scope}]" if scope else ""
        print(f"{code}: {message}{suffix}", file=sys.stderr)


def _emit_typed_failure(message: str) -> int:
    return _emit_typed_error(message, status=_EXIT_GENERIC)


def _emit_typed_error(message: str, *, status: int) -> int:
    print(f"partial-coverage: {message}", file=sys.stderr)
    return status


def _dispatch_entitlements(args: argparse.Namespace) -> int:
    if args.target_kind not in {"agol", "server"}:
        build_parser().print_help()
        return _EXIT_USAGE

    configure_logging(verbose=args.verbose, debug=args.debug)

    try:
        output = _run_entitlements(args)
    except EntitlementsError as exc:
        return _render_typed_entitlements_error(exc, debug=args.debug)
    except Exception as exc:  # noqa: BLE001 - last-resort guard for prospect safety
        if args.debug:
            raise
        print(
            f"honua-esri-assess: unexpected failure ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return _EXIT_GENERIC

    print(
        json.dumps(
            _serialize_entitlements_output(output, args.target_kind),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_entitlements(args: argparse.Namespace) -> _EntitlementsOutput:
    token = getattr(args, "token", None)
    client = RequestsHttpClient(token=token, default_timeout=args.timeout)

    if args.target_kind == "agol":
        collector = PortalEntitlementsCollector(
            args.target, client, anonymous=args.anonymous
        )
        result = collector.collect()
        return _EntitlementsOutput(
            facet=LicensingFacet(portal=result.licensing, server=None),
            diagnostics=[d.to_dict() for d in result.diagnostics],
        )

    collector = ServerEntitlementsCollector(
        args.target,
        client,
        include_service_extensions=not args.no_service_extensions,
    )
    services = args.service or None
    result = collector.collect(services)
    return _EntitlementsOutput(
        facet=LicensingFacet(portal=None, server=result.licensing),
        diagnostics=[d.to_dict() for d in result.diagnostics],
    )


def _parse_service_ref(spec: str) -> ServiceRef:
    if "/" in spec:
        folder, tail = spec.split("/", 1)
    else:
        folder, tail = "", spec
    if "." not in tail:
        raise argparse.ArgumentTypeError(
            f"--service expects 'FOLDER/NAME.TYPE' or 'NAME.TYPE'; got {spec!r}."
        )
    name, kind = tail.rsplit(".", 1)
    return ServiceRef(folder=folder, name=name, type=kind)


def _serialize_entitlements_output(
    output: _EntitlementsOutput, target_kind: str
) -> dict[str, object]:
    return {
        "target": target_kind,
        "licensing": licensing_facet_to_dict(output.facet),
        "diagnostics": list(output.diagnostics),
    }


def _render_typed_entitlements_error(exc: EntitlementsError, *, debug: bool) -> int:
    if debug:
        raise exc
    category = _ERROR_CATEGORY.get(type(exc), "api error")
    print(f"honua-esri-assess: {category}: {exc}", file=sys.stderr)
    return _EXIT_ENTITLEMENTS_TYPED


_ERROR_CATEGORY: dict[type[EntitlementsError], str] = {
    EntitlementsAuthError: "authentication required",
    EntitlementsForbiddenError: "permission denied",
    EntitlementsNotFoundError: "endpoint not found",
    EntitlementsRateLimitedError: "rate limited",
    EntitlementsConnectionError: "could not reach host",
    EntitlementsApiError: "Esri endpoint error",
    EntitlementsSchemaError: "could not parse response",
}


__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
