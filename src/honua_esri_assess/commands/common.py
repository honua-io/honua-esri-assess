"""Shared CLI option types and scan execution helpers."""

from __future__ import annotations

import json
import logging
import os
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
from honua_esri_assess.log_config import configure_logging
from honua_esri_assess.schema import validate_footprint

LOGGER = logging.getLogger(__name__)
DEFAULT_OUTPUT = Path("EsriFootprint.json")
DEFAULT_USER_AGENT = f"honua-esri-assess/{__version__}"


class LogFormat(StrEnum):
    text = "text"
    json = "json"


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
    include_access: bool = False
    access_group_cap: int = 200
    token: str | None = field(default=None, repr=False)


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
IncludeAccessOption = Annotated[
    bool,
    typer.Option(
        "--include-access/--no-include-access",
        help=(
            "Enable the authorized access export (identity/RBAC, per-service "
            "permissions). Requires --token-env and emits EsriFootprint schema "
            "v0.2; off by default."
        ),
    ),
]


def _validate_access_group_cap(value: int) -> int:
    if value < 0:
        raise typer.BadParameter("--access-group-cap must be >= 0")
    return value


AccessGroupCapOption = Annotated[
    int,
    typer.Option(
        "--access-group-cap",
        min=0,
        callback=_validate_access_group_cap,
        help=(
            "Per-group member-probe cap when --include-access is set. "
            "Groups exceeding the cap emit a partial-coverage diagnostic."
        ),
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
    include_access: bool = False,
    access_group_cap: int = 200,
) -> ScanOptions:
    configure_logging(level=log_level.value, log_format=log_format.value)
    token = os.environ.get(token_env) if token_env else None
    if token_env:
        LOGGER.info("using token from environment variable %s", token_env)
    if include_access and not token:
        raise DiagnosticError(
            "--include-access requires --token-env pointing to an admin-tier token.",
            code="access-token-required",
            scope="access",
        )
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
        include_access=include_access,
        access_group_cap=access_group_cap,
        token=token,
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
    include_access: bool = False,
    access_group_cap: int = 200,
) -> None:
    from honua_esri_assess.commands.scan_handlers import get_handler

    try:
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
            include_access=include_access,
            access_group_cap=access_group_cap,
        )
    except DiagnosticError as exc:
        print_diagnostic_error(exc)
        raise typer.Exit(exc.exit_code) from None
    try:
        result = get_handler(handler_name).run(options)
        persist_scan_result(options, result)
    except DiagnosticError as exc:
        print_diagnostic_error(exc)
        raise typer.Exit(exc.exit_code) from None
    except Exception as exc:
        handle_unexpected_error(exc)
