"""Migratability verdict command."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import typer

from honua_esri_assess import verdict as verdict_module
from honua_esri_assess.diagnostics import (
    ReportInputError,
    ReportRenderError,
    ReportSchemaValidationError,
    handle_unexpected_error,
    render_error,
)
from honua_esri_assess.report.validation import validate_footprint_v01


def verdict_command(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            help="Path to EsriFootprint.json, or '-' for stdin.",
        ),
    ],
    output: Annotated[
        str,
        typer.Option(
            "--output",
            help="Destination path for the Markdown verdict, or '-' for stdout.",
        ),
    ] = "-",
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Fail if the input does not validate against EsriFootprint v0.1.",
        ),
    ] = False,
) -> None:
    try:
        footprint = _read_footprint(input_path)
        _check_schema(footprint, strict=strict)
        markdown = verdict_module.render(footprint)
        _write_output(markdown, output)
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


def _check_schema(footprint: Mapping[str, object], *, strict: bool) -> None:
    if not strict:
        return
    issues = validate_footprint_v01(footprint)
    failures = tuple(issue.message for issue in issues if issue.is_failure)
    if failures:
        raise ReportSchemaValidationError(failures[0])


def _write_output(markdown: str, output: str) -> None:
    if output == "-":
        typer.echo(markdown, nl=False)
        return
    output_path = Path(output)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        raise ReportInputError(
            "Could not write migratability verdict.",
            code="report.input.write",
            exit_code=2,
        ) from exc
