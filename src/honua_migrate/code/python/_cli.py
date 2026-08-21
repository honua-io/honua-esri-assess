"""Command-line entrypoint for the ArcPy -> Honua GP migration codemod.

Secondary module entry point (the canonical CLI is
``honua-migrate code python``)::

    python -m honua_migrate.code.python scan path/to/script.py
    python -m honua_migrate.code.python translate script.py --evidence out.json
    python -m honua_migrate.code.python run script.py --server https://example.test

The ``scan``, ``translate``, ``pyt``, ``atbx``, and ``gpservice`` commands work
offline (no ArcGIS or network). The ``run`` command executes the translatable
steps through ``HonuaClient.ogc_processes().execute(...)`` against ``--server``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from honua_esri_assess.output_io import (
    OutputExistsError,
    atomic_write_text,
    ensure_overwrite_allowed,
)
from honua_migrate.contract_validation import assert_artifact_safe
from honua_migrate.contracts import (
    EXIT_BAD_ARGUMENTS,
    EXIT_SAFETY_REFUSAL,
    EXIT_SUCCESS,
    EXIT_UNAVAILABLE,
    EXIT_VALIDATION_ERROR as EXIT_UNSUPPORTED_INPUT,
    MigrationError,
)

from .arcpy import (
    ArcPyProcessRunner,
    build_parity_evidence,
    scan_arcpy_file,
    translate_arcpy_report,
)
from .modelbuilder import (
    UnsupportedModelFormatError,
    build_atbx_parity_evidence,
    build_gp_service_parity_evidence,
    parse_atbx_toolbox,
    parse_gp_service_definition,
)
from .pyt import (
    UnsupportedToolboxError,
    build_pyt_parity_evidence,
    parse_binary_toolbox,
    parse_pyt_file,
)

# .atbx is now handled clean-room by the modelbuilder reader; only the
# proprietary binary .tbx remains an explicit stub in the ``pyt`` command.
_BINARY_TOOLBOX_SUFFIXES = {".tbx"}


def _preflight_outputs(
    *paths: Path | None,
    force: bool,
) -> int | None:
    requested = [path for path in paths if path is not None]
    if len(set(requested)) != len(requested):
        print("output paths must be distinct", file=sys.stderr)
        return EXIT_UNSUPPORTED_INPUT
    try:
        for path in requested:
            ensure_overwrite_allowed(path, force=force)
    except OutputExistsError:
        print("output already exists; use --force to replace it", file=sys.stderr)
        return EXIT_UNSUPPORTED_INPUT
    return None


def _emit(
    obj: object,
    *,
    out: Path | None,
    force: bool,
) -> int | None:
    try:
        assert_artifact_safe(obj)
    except MigrationError as exc:
        print("artifact validation failed", file=sys.stderr)
        return exc.exit_code
    text = json.dumps(obj, indent=2, sort_keys=False)
    if out is None:
        print(text)
        return None
    try:
        ensure_overwrite_allowed(out, force=force)
        atomic_write_text(out, text + "\n")
    except OutputExistsError:
        print("output already exists; use --force to replace it", file=sys.stderr)
        return EXIT_UNSUPPORTED_INPUT
    except OSError:
        print("could not write output", file=sys.stderr)
        return EXIT_UNSUPPORTED_INPUT
    return None


def _valid_server_url(value: str) -> bool:
    if not value or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        return False
    if "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.netloc)
        and hostname is not None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _cmd_scan(args: argparse.Namespace) -> int:
    failure = _preflight_outputs(args.output, force=args.force)
    if failure is not None:
        return failure
    report = scan_arcpy_file(args.path)
    failure = _emit(report.to_dict(), out=args.output, force=args.force)
    if failure is not None:
        return failure
    if report.syntax_error is not None:
        print(f"syntax error: {report.syntax_error}", file=sys.stderr)
        return EXIT_BAD_ARGUMENTS
    return EXIT_SUCCESS


def _cmd_translate(args: argparse.Namespace) -> int:
    failure = _preflight_outputs(
        args.output,
        args.evidence,
        force=args.force,
    )
    if failure is not None:
        return failure
    report = scan_arcpy_file(args.path)
    if report.syntax_error is not None:
        print(f"syntax error: {report.syntax_error}", file=sys.stderr)
        return EXIT_BAD_ARGUMENTS
    plan = translate_arcpy_report(report)
    evidence = build_parity_evidence(plan)
    if args.evidence is not None:
        failure = _emit(evidence, out=args.evidence, force=args.force)
        if failure is not None:
            return failure
    failure = _emit(plan.to_dict(), out=args.output, force=args.force)
    if failure is not None:
        return failure

    summary = evidence["summary"]
    print(
        f"coverage: {summary['translatableCalls']}/{summary['totalCalls']} translatable "
        f"({summary['coveragePercent']}%), {summary['manualReviewCalls']} manual-review, "
        f"{summary['unsupportedCalls']} unsupported",
        file=sys.stderr,
    )
    return EXIT_SUCCESS


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.dry_run and not args.acknowledge:
        print(
            "refusing remote execution without --yes/--acknowledge",
            file=sys.stderr,
        )
        return EXIT_SAFETY_REFUSAL
    failure = _preflight_outputs(args.output, force=args.force)
    if failure is not None:
        return failure
    if not _valid_server_url(args.server):
        print("invalid server URL", file=sys.stderr)
        return EXIT_UNSUPPORTED_INPUT

    report = scan_arcpy_file(args.path)
    plan = translate_arcpy_report(report)
    # Only execute the steps the reconciled server can job-execute. Supported
    # but non-job-executable tools (manual-review) are reported as skipped.
    runnable = tuple(t for t in plan.translations if t.call.translatable)
    skipped = [c.qualified_name for c in plan.manual_review_calls]
    if not runnable:
        print("no translatable ArcPy calls to execute", file=sys.stderr)
        failure = _emit(
            {"executions": [], "skipped": skipped},
            out=args.output,
            force=args.force,
        )
        if failure is not None:
            return failure
        return EXIT_SUCCESS

    if args.dry_run:
        failure = _emit(
            {
                "dryRun": True,
                "server": args.server,
                "executions": [t.to_dict() for t in runnable],
                "skipped": skipped,
            },
            out=args.output,
            force=args.force,
        )
        if failure is not None:
            return failure
        return EXIT_SUCCESS

    try:
        from honua_sdk import HonuaClient
    except ImportError:
        print(
            "run requires the public honua-sdk package. honua-sdk 0.x also owns "
            "the honua-migrate console script; use an isolated environment and "
            "invoke this distribution as python -m honua_migrate. See "
            "https://github.com/honua-io/honua-migrate/blob/trunk/docs/"
            "console-script-collision.md.",
            file=sys.stderr,
        )
        return EXIT_UNAVAILABLE

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
    failure = _emit(
        {"server": args.server, "executions": results, "skipped": skipped},
        out=args.output,
        force=args.force,
    )
    if failure is not None:
        return failure
    return EXIT_SUCCESS


def _cmd_pyt(args: argparse.Namespace) -> int:
    failure = _preflight_outputs(
        args.output,
        args.evidence,
        force=args.force,
    )
    if failure is not None:
        return failure
    suffix = Path(args.path).suffix.lower()
    if suffix in _BINARY_TOOLBOX_SUFFIXES:
        try:
            parse_binary_toolbox(args.path)
        except UnsupportedToolboxError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_UNSUPPORTED_INPUT

    toolbox = parse_pyt_file(args.path)
    if args.evidence is not None:
        failure = _emit(
            build_pyt_parity_evidence(toolbox),
            out=args.evidence,
            force=args.force,
        )
        if failure is not None:
            return failure
    failure = _emit(toolbox.to_dict(), out=args.output, force=args.force)
    if failure is not None:
        return failure
    if toolbox.syntax_error is not None:
        print(f"syntax error: {toolbox.syntax_error}", file=sys.stderr)
        return EXIT_BAD_ARGUMENTS
    return EXIT_SUCCESS


def _cmd_atbx(args: argparse.Namespace) -> int:
    failure = _preflight_outputs(
        args.output,
        args.evidence,
        force=args.force,
    )
    if failure is not None:
        return failure
    try:
        toolbox = parse_atbx_toolbox(args.path)
    except UnsupportedModelFormatError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_UNSUPPORTED_INPUT
    if args.evidence is not None:
        failure = _emit(
            build_atbx_parity_evidence(toolbox),
            out=args.evidence,
            force=args.force,
        )
        if failure is not None:
            return failure
    failure = _emit(toolbox.to_dict(), out=args.output, force=args.force)
    if failure is not None:
        return failure
    if toolbox.parse_error is not None:
        print(f"parse error: {toolbox.parse_error}", file=sys.stderr)
        return EXIT_BAD_ARGUMENTS
    return EXIT_SUCCESS


def _cmd_gpservice(args: argparse.Namespace) -> int:
    failure = _preflight_outputs(
        args.output,
        args.evidence,
        force=args.force,
    )
    if failure is not None:
        return failure
    text = Path(args.path).read_text(encoding="utf-8")
    try:
        service = parse_gp_service_definition(text, url=args.url)
    except (UnsupportedModelFormatError, json.JSONDecodeError) as exc:
        print(f"could not parse GP service definition: {exc}", file=sys.stderr)
        return EXIT_BAD_ARGUMENTS
    if args.evidence is not None:
        failure = _emit(
            build_gp_service_parity_evidence(service),
            out=args.evidence,
            force=args.force,
        )
        if failure is not None:
            return failure
    failure = _emit(service.to_dict(), out=args.output, force=args.force)
    if failure is not None:
        return failure
    return EXIT_SUCCESS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m honua_migrate.code.python",
        description=__doc__.splitlines()[0],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Classify ArcPy calls in a Python script (offline).")
    scan.add_argument("path", type=Path, help="Path to an arcpy .py script.")
    scan.add_argument("--output", type=Path, default=None, help="Write JSON report to this path (default: stdout).")
    scan.add_argument("--force", action="store_true", help="Replace existing output files.")
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
    translate.add_argument("--force", action="store_true", help="Replace existing output files.")
    translate.set_defaults(func=_cmd_translate)

    run = sub.add_parser("run", help="Execute translatable steps via ArcPyProcessRunner against --server.")
    run.add_argument("path", type=Path, help="Path to an arcpy .py script.")
    run.add_argument("--server", required=True, help="Honua server base URL.")
    run.add_argument("--output", type=Path, default=None, help="Write execution results JSON here (default: stdout).")
    run.add_argument("--dry-run", action="store_true", help="Emit payloads without contacting the server.")
    run.add_argument(
        "--yes",
        "--acknowledge",
        dest="acknowledge",
        action="store_true",
        help="Acknowledge that non-dry-run execution mutates the Honua target.",
    )
    run.add_argument("--force", action="store_true", help="Replace existing output files.")
    run.set_defaults(func=_cmd_run)

    pyt = sub.add_parser("pyt", help="Parse a .pyt Python toolbox and classify its tools' GP calls.")
    pyt.add_argument("path", type=Path, help="Path to a .pyt Python toolbox (or .tbx to see the binary-format stub).")
    pyt.add_argument("--output", type=Path, default=None, help="Write the toolbox JSON here (default: stdout).")
    pyt.add_argument("--evidence", type=Path, default=None, help="Write the aggregated parity-evidence JSON here.")
    pyt.add_argument("--force", action="store_true", help="Replace existing output files.")
    pyt.set_defaults(func=_cmd_pyt)

    atbx = sub.add_parser(
        "atbx",
        help="Parse a .atbx ModelBuilder toolbox clean-room and classify its models' GP steps.",
    )
    atbx.add_argument("path", type=Path, help="Path to a .atbx ModelBuilder toolbox.")
    atbx.add_argument("--output", type=Path, default=None, help="Write the toolbox JSON here (default: stdout).")
    atbx.add_argument("--evidence", type=Path, default=None, help="Write the aggregated parity-evidence JSON here.")
    atbx.add_argument("--force", action="store_true", help="Replace existing output files.")
    atbx.set_defaults(func=_cmd_atbx)

    gpservice = sub.add_parser(
        "gpservice",
        help="Parse an ArcGIS REST GPServer service-definition JSON and classify its tasks (offline).",
    )
    gpservice.add_argument("path", type=Path, help="Path to a GPServer service-definition JSON (.../GPServer?f=json).")
    gpservice.add_argument("--url", default=None, help="Original service URL to record in the report.")
    gpservice.add_argument("--output", type=Path, default=None, help="Write the service JSON here (default: stdout).")
    gpservice.add_argument(
        "--evidence", type=Path, default=None, help="Write the aggregated parity-evidence JSON here."
    )
    gpservice.add_argument("--force", action="store_true", help="Replace existing output files.")
    gpservice.set_defaults(func=_cmd_gpservice)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
