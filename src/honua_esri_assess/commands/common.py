"""Shared CLI option types and scan execution helpers."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from honua_esri_assess import __version__
from honua_esri_assess.diagnostics import (
    Diagnostic,
    DiagnosticError,
    OutputWriteError,
    handle_unexpected_error,
    print_diagnostic,
    print_diagnostic_error,
)
from honua_esri_assess.footprint.access import (
    access_footprint_to_json,
    validate_access_footprint,
)
from honua_esri_assess.log_config import configure_logging
from honua_esri_assess.schema import validate_footprint

LOGGER = logging.getLogger(__name__)
DEFAULT_OUTPUT = Path("EsriFootprint.json")
DEFAULT_ACCESS_OUTPUT = Path("-")
STDOUT_SENTINEL = Path("-")
DEFAULT_USER_AGENT = f"honua-esri-assess/{__version__}"


class LogFormat(StrEnum):
    text = "text"
    json = "json"


class RbacKind(StrEnum):
    portal = "portal"
    server = "server"


class LogLevel(StrEnum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


@dataclass(frozen=True)
class ScanOptions:
    target: str
    output: Path
    token_env: str | None
    log_format: str
    log_level: str
    no_network_telemetry_confirm: bool
    user_agent: str
    max_retries: int
    timeout: float
    validate: bool
    token: str | None = field(default=None, repr=False)
    rbac_kind: str = "portal"


@dataclass(frozen=True)
class ScanResult:
    footprint: dict[str, Any]
    diagnostics: tuple[Diagnostic, ...] = ()


TargetOption = Annotated[
    str,
    typer.Option(
        "--target",
        help="Target URL, portal locator, or local FileGDB path to inspect.",
        metavar="TARGET",
    ),
]
OutputOption = Annotated[
    Path,
    typer.Option(
        "--output",
        help="Destination path for EsriFootprint.json.",
        dir_okay=True,
        file_okay=True,
        metavar="PATH",
    ),
]
TokenEnvOption = Annotated[
    str | None,
    typer.Option(
        "--token-env",
        help="Environment variable that contains an Esri access token.",
        metavar="VAR",
    ),
]
LogFormatOption = Annotated[
    LogFormat,
    typer.Option("--log-format", help="Local log format."),
]
LogLevelOption = Annotated[
    LogLevel,
    typer.Option("--log-level", help="Local log verbosity."),
]
NoNetworkTelemetryConfirmOption = Annotated[
    bool,
    typer.Option(
        "--no-network-telemetry-confirm",
        help="Acknowledge that this invocation does not enable network telemetry.",
    ),
]
UserAgentOption = Annotated[
    str,
    typer.Option("--user-agent", help="User-Agent header for read-only Esri calls."),
]
MaxRetriesOption = Annotated[
    int,
    typer.Option(
        "--max-retries",
        min=0,
        help="Maximum retries for read-only network calls.",
    ),
]


def _validate_timeout(value: float) -> float:
    if value <= 0:
        raise typer.BadParameter("timeout must be greater than 0 seconds")
    return value


TimeoutOption = Annotated[
    float,
    typer.Option(
        "--timeout",
        callback=_validate_timeout,
        help="Timeout in seconds for read-only network calls.",
    ),
]
ValidateOption = Annotated[
    bool,
    typer.Option(
        "--validate/--no-validate",
        help="Validate the generated EsriFootprint.json against the bundled schema.",
    ),
]
AccessOutputOption = Annotated[
    Path,
    typer.Option(
        "--output",
        help="Destination path for EsriAccessFootprint.json ('-' writes to stdout).",
        dir_okay=True,
        file_okay=True,
        metavar="PATH",
    ),
]
RbacKindOption = Annotated[
    RbacKind,
    typer.Option(
        "--kind",
        help="Whether the target is an ArcGIS Online/Enterprise Portal or an ArcGIS Server admin endpoint.",
    ),
]
AccessValidateOption = Annotated[
    bool,
    typer.Option(
        "--validate/--no-validate",
        help="Validate the generated EsriAccessFootprint.json against the bundled schema.",
    ),
]


def build_scan_options(
    *,
    target: str,
    output: Path,
    token_env: str | None,
    log_format: LogFormat,
    log_level: LogLevel,
    no_network_telemetry_confirm: bool,
    user_agent: str,
    max_retries: int,
    timeout: float,
    validate: bool,
    rbac_kind: str = "portal",
) -> ScanOptions:
    configure_logging(level=log_level.value, log_format=log_format.value)
    token = os.environ.get(token_env) if token_env else None
    if token_env:
        LOGGER.info("using token from environment variable %s", token_env)
    return ScanOptions(
        target=target,
        output=output,
        token_env=token_env,
        log_format=log_format.value,
        log_level=log_level.value,
        no_network_telemetry_confirm=no_network_telemetry_confirm,
        user_agent=user_agent,
        max_retries=max_retries,
        timeout=timeout,
        validate=validate,
        token=token,
        rbac_kind=rbac_kind,
    )


def persist_scan_result(options: ScanOptions, result: ScanResult) -> None:
    if options.validate:
        validate_footprint(result.footprint)
    try:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        with options.output.open("w", encoding="utf-8") as fh:
            json.dump(result.footprint, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        raise OutputWriteError(options.output) from exc

    inventory = result.footprint.get("inventory")
    item_count = len(inventory) if isinstance(inventory, list) else 0
    typer.echo(f"scanned {item_count} item(s)", err=True)
    for diagnostic in result.diagnostics:
        print_diagnostic(diagnostic)


def run_scan_command(
    *,
    handler_name: str,
    target: str,
    output: Path,
    token_env: str | None,
    log_format: LogFormat,
    log_level: LogLevel,
    no_network_telemetry_confirm: bool,
    user_agent: str,
    max_retries: int,
    timeout: float,
    validate: bool,
) -> None:
    from honua_esri_assess.commands.scan_handlers import get_handler

    options = build_scan_options(
        target=target,
        output=output,
        token_env=token_env,
        log_format=log_format,
        log_level=log_level,
        no_network_telemetry_confirm=no_network_telemetry_confirm,
        user_agent=user_agent,
        max_retries=max_retries,
        timeout=timeout,
        validate=validate,
    )
    try:
        result = get_handler(handler_name).run(options)
        persist_scan_result(options, result)
    except DiagnosticError as exc:
        print_diagnostic_error(exc)
        raise typer.Exit(exc.exit_code) from None
    except Exception as exc:
        handle_unexpected_error(exc)


def _assert_no_token_in_artifact(options: ScanOptions, serialized: str) -> None:
    """Fail loudly if a live token ever reaches the access-footprint artifact.

    Credentials are supplied only via ``--token-env`` and the artifact is meant
    to be prospect-safe. This is a CLI-level backstop on top of the scanner's
    own redaction so a token can never be written to disk or stdout.
    """

    if options.token and options.token in serialized:
        raise OutputWriteError(options.output)


def persist_access_scan_result(options: ScanOptions, result: ScanResult) -> None:
    if options.validate:
        validate_access_footprint(result.footprint)
    serialized = access_footprint_to_json(result.footprint)
    _assert_no_token_in_artifact(options, serialized)

    if str(options.output) == str(STDOUT_SENTINEL):
        sys.stdout.write(serialized)
    else:
        try:
            options.output.parent.mkdir(parents=True, exist_ok=True)
            options.output.write_text(serialized, encoding="utf-8")
        except OSError as exc:
            raise OutputWriteError(options.output) from exc
        typer.echo(f"wrote {options.output}", err=True)

    users = result.footprint.get("users")
    roles = result.footprint.get("roles")
    user_count = len(users) if isinstance(users, list) else 0
    role_count = len(roles) if isinstance(roles, list) else 0
    typer.echo(f"scanned {user_count} user(s), {role_count} role(s)", err=True)
    for diagnostic in result.diagnostics:
        print_diagnostic(diagnostic)


def run_rbac_scan_command(
    *,
    target: str,
    output: Path,
    token_env: str | None,
    kind: RbacKind,
    log_format: LogFormat,
    log_level: LogLevel,
    no_network_telemetry_confirm: bool,
    user_agent: str,
    max_retries: int,
    timeout: float,
    validate: bool,
) -> None:
    from honua_esri_assess.commands.scan_handlers import get_handler

    options = build_scan_options(
        target=target,
        output=output,
        token_env=token_env,
        log_format=log_format,
        log_level=log_level,
        no_network_telemetry_confirm=no_network_telemetry_confirm,
        user_agent=user_agent,
        max_retries=max_retries,
        timeout=timeout,
        validate=validate,
        rbac_kind=kind.value,
    )
    try:
        result = get_handler("rbac").run(options)
        persist_access_scan_result(options, result)
    except DiagnosticError as exc:
        print_diagnostic_error(exc)
        raise typer.Exit(exc.exit_code) from None
    except Exception as exc:
        handle_unexpected_error(exc)
