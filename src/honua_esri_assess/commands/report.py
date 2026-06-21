"""Readiness report command."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import typer

from honua_esri_assess import report as report_module
from honua_esri_assess.diagnostics import (
    ReportInputError,
    ReportRenderError,
    ReportSchemaValidationError,
    handle_unexpected_error,
    render_error,
)
from honua_esri_assess.output_io import (
    OutputExistsError,
    atomic_write_text,
    ensure_overwrite_allowed,
)
from honua_esri_assess.report.validation import validate_footprint_v01


def report_command(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            help="Path to EsriFootprint.json.",
        ),
    ],
    output: Annotated[
        str,
        typer.Option(
            "--output",
            help="Destination path for the Markdown report, or '-' for stdout.",
        ),
    ] = "-",
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Fail if the input does not validate against EsriFootprint v0.1.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite the output file if it already exists.",
        ),
    ] = False,
) -> None:
    try:
        footprint = _read_footprint(input_path)
        schema_warnings = _schema_warnings(footprint, strict=strict)
        markdown = report_module.render(
            footprint,
            options=report_module.RenderOptions(schema_warnings=schema_warnings),
        )
        _write_report(markdown, output, force=force)
    except (ReportInputError, ReportSchemaValidationError, ReportRenderError) as exc:
        typer.echo(render_error(exc), err=True)
        raise typer.Exit(exc.exit_code) from None
    except Exception as exc:
        handle_unexpected_error(exc)


def _read_footprint(input_path: Path) -> Mapping[str, object]:
    try:
        if str(input_path) == "-":
            raw = sys.stdin.read()
        else:
            raw = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportInputError(
            "Could not read EsriFootprint.json.",
            code="report.input.read",
            exit_code=2,
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReportInputError(
            "Could not parse EsriFootprint.json as JSON.",
            code="report.input.parse",
            exit_code=2,
        ) from exc
    if not isinstance(payload, Mapping):
        raise ReportInputError(
            "EsriFootprint.json must be a JSON object.",
            code="report.input.parse",
            exit_code=2,
        )
    return payload


def _schema_warnings(
    footprint: Mapping[str, object],
    *,
    strict: bool,
) -> tuple[str, ...]:
    issues = validate_footprint_v01(footprint)
    failures = tuple(issue.message for issue in issues if issue.is_failure)
    if strict and failures:
        raise ReportSchemaValidationError(failures[0])
    return failures


def _write_report(markdown: str, output: str, *, force: bool) -> None:
    if output == "-":
        typer.echo(markdown, nl=False)
        return
    output_path = Path(output)
    try:
        ensure_overwrite_allowed(output_path, force=force)
    except OutputExistsError as exc:
        raise ReportInputError(
            "Report output already exists; re-run with --force to overwrite it.",
            code="report.input.exists",
            exit_code=2,
        ) from exc
    try:
        atomic_write_text(output_path, markdown)
    except OSError as exc:
        raise ReportInputError(
            "Could not write readiness report.",
            code="report.input.write",
            exit_code=2,
        ) from exc
