"""Honua capability crosswalk command.

Crosswalks an ``EsriFootprint.json``'s detected assess-registry capabilities
(``honua_esri_assess.verdict.registry``) to Honua capability keys via a
versioned crosswalk document, and emits:

- ``honua-caps.json`` (default output path): schemaVersion, generatedAt, the
  source footprint reference, per-capability entries (Honua key, matched
  inventory count, tier), unmapped entries (assess key, count, reason),
  diagnostics, a serving-unit estimate, and a shareable catalog URL.
- A Markdown summary, styled like the readiness report / verdict output
  (``--output``, default stdout).
- The shareable catalog URL, always printed to stdout.

DRAFT CROSSWALK NOTICE: the bundled crosswalk
(``src/honua_esri_assess/data/honua-crosswalk.fixture.json``) is a draft
placeholder pending the canonical ``capability-keys.v1.json`` artifact from
honua-server (honua-io/honua-server#2893). Pass ``--crosswalk`` to override
it with a local file (air-gapped path) or, once published, a URL.

Air-gapped posture: by default this command makes no network call at all --
the bundled fixture is read from the installed package. A URL is fetched
*only* when the operator explicitly passes one to ``--crosswalk``; this is
the one deliberate, opt-in exception to the tool's no-network posture, and it
never happens unless requested.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from honua_esri_assess.caps.crosswalk import (
    CrosswalkError,
    load_bundled_crosswalk,
    parse_crosswalk_text,
)
from honua_esri_assess.caps.mapper import evaluate as evaluate_caps
from honua_esri_assess.caps.renderer import render_markdown, to_json_dict
from honua_esri_assess.diagnostics import (
    ReportCrosswalkError,
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

_STDOUT = "-"
DEFAULT_JSON_OUTPUT = "honua-caps.json"


def caps_command(
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
            help="Destination path for the Markdown crosswalk summary, or '-' for stdout.",
        ),
    ] = "-",
    json_output: Annotated[
        str,
        typer.Option(
            "--json",
            help="Destination path for honua-caps.json, or '-' for stdout.",
        ),
    ] = DEFAULT_JSON_OUTPUT,
    crosswalk_source: Annotated[
        str | None,
        typer.Option(
            "--crosswalk",
            help=(
                "Path or URL to an esri-assess-registry -> Honua capability-key "
                "crosswalk document. Defaults to the bundled draft fixture. A "
                "URL is fetched only when passed here explicitly -- never by "
                "default (air-gapped posture)."
            ),
        ),
    ] = None,
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
            help="Overwrite honua-caps.json / the Markdown output if they already exist.",
        ),
    ] = False,
) -> None:
    try:
        footprint = _read_footprint(input_path)
        _check_schema(footprint, strict=strict)
        crosswalk = _load_crosswalk(crosswalk_source)
        result = evaluate_caps(footprint, crosswalk)
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = to_json_dict(footprint, crosswalk, result, generated_at=generated_at)
        markdown = render_markdown(payload)
        _write_json(payload, json_output, force=force)
        _write_markdown(markdown, output, force=force)
        # The Markdown already surfaces the URL under "Shareable Catalog URL"
        # when it goes to stdout; avoid printing it twice in that case.
        if output != _STDOUT:
            typer.echo(payload["url"])
    except (
        ReportInputError,
        ReportSchemaValidationError,
        ReportRenderError,
        ReportCrosswalkError,
    ) as exc:
        typer.echo(render_error(exc), err=True)
        raise typer.Exit(exc.exit_code) from None
    except Exception as exc:
        handle_unexpected_error(exc)


def _read_footprint(input_path: Path) -> Mapping[str, object]:
    try:
        if str(input_path) == _STDOUT:
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


def _load_crosswalk(source: str | None):
    if source is None:
        try:
            return load_bundled_crosswalk()
        except CrosswalkError as exc:
            raise ReportCrosswalkError(str(exc)) from exc

    text = _read_crosswalk_text(source)
    try:
        return parse_crosswalk_text(text)
    except CrosswalkError as exc:
        raise ReportCrosswalkError(str(exc)) from exc


def _read_crosswalk_text(source: str) -> str:
    if source.startswith("http://") or source.startswith("https://"):
        return _fetch_crosswalk_url(source)
    try:
        return Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportInputError(
            "Could not read the crosswalk document.",
            code="report.input.read",
            exit_code=2,
        ) from exc


def _fetch_crosswalk_url(url: str) -> str:
    """Fetch a crosswalk document over HTTP(S).

    This is the one explicit, user-opt-in exception to this tool's no-network
    posture: it only runs when the operator passes ``--crosswalk <url>``
    themselves, is never invoked by default (the bundled fixture is used
    instead), and issues a single anonymous ``GET`` with no query string,
    credential, or token attached.
    """

    import requests

    try:
        response = requests.get(url, timeout=10.0)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ReportInputError(
            "Could not fetch the crosswalk document from the given URL.",
            code="report.input.read",
            exit_code=2,
        ) from exc
    return response.text


def _write_json(payload: dict[str, object], destination: str, *, force: bool) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if destination == _STDOUT:
        typer.echo(serialized, nl=False)
        return
    output_path = Path(destination)
    try:
        ensure_overwrite_allowed(output_path, force=force)
    except OutputExistsError as exc:
        raise ReportInputError(
            "honua-caps.json already exists; re-run with --force to overwrite it.",
            code="report.input.exists",
            exit_code=2,
        ) from exc
    try:
        atomic_write_text(output_path, serialized)
    except OSError as exc:
        raise ReportInputError(
            "Could not write honua-caps.json.",
            code="report.input.write",
            exit_code=2,
        ) from exc


def _write_markdown(markdown: str, destination: str, *, force: bool) -> None:
    if destination == _STDOUT:
        typer.echo(markdown, nl=False)
        return
    output_path = Path(destination)
    try:
        ensure_overwrite_allowed(output_path, force=force)
    except OutputExistsError as exc:
        raise ReportInputError(
            "Crosswalk summary output already exists; re-run with --force to "
            "overwrite it.",
            code="report.input.exists",
            exit_code=2,
        ) from exc
    try:
        atomic_write_text(output_path, markdown)
    except OSError as exc:
        raise ReportInputError(
            "Could not write the crosswalk summary.",
            code="report.input.write",
            exit_code=2,
        ) from exc
