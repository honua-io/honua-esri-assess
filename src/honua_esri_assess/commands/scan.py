"""`scan` command group."""

from __future__ import annotations

import typer

from honua_esri_assess.commands.common import (
    DEFAULT_ACCESS_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_USER_AGENT,
    AdminUsageOption,
    AccessOutputOption,
    AccessValidateOption,
    LogFormat,
    LogFormatOption,
    LogLevel,
    LogLevelOption,
    MaxRetriesOption,
    NoNetworkTelemetryConfirmOption,
    OutputOption,
    RbacKind,
    RbacKindOption,
    TargetOption,
    TimeoutOption,
    TokenEnvOption,
    UserAgentOption,
    ValidateOption,
    run_rbac_scan_command,
    run_scan_command,
)

scan_app = typer.Typer(
    help="Read-only scanners that produce EsriFootprint.json.",
    no_args_is_help=True,
)


@scan_app.command("agol", help="Run the ArcGIS Online Portal scanner.")
def scan_agol(
    target: TargetOption,
    output: OutputOption = DEFAULT_OUTPUT,
    token_env: TokenEnvOption = None,
    log_format: LogFormatOption = LogFormat.text,
    log_level: LogLevelOption = LogLevel.info,
    no_network_telemetry_confirm: NoNetworkTelemetryConfirmOption = False,
    user_agent: UserAgentOption = DEFAULT_USER_AGENT,
    max_retries: MaxRetriesOption = 3,
    timeout: TimeoutOption = 30.0,
    validate: ValidateOption = False,
) -> None:
    run_scan_command(
        handler_name="agol",
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


@scan_app.command("server", help="Run the ArcGIS Server REST scanner.")
def scan_server(
    target: TargetOption,
    output: OutputOption = DEFAULT_OUTPUT,
    token_env: TokenEnvOption = None,
    log_format: LogFormatOption = LogFormat.text,
    log_level: LogLevelOption = LogLevel.info,
    no_network_telemetry_confirm: NoNetworkTelemetryConfirmOption = False,
    user_agent: UserAgentOption = DEFAULT_USER_AGENT,
    max_retries: MaxRetriesOption = 3,
    timeout: TimeoutOption = 30.0,
    validate: ValidateOption = False,
    admin_usage: AdminUsageOption = False,
) -> None:
    run_scan_command(
        handler_name="server",
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
        admin_usage=admin_usage,
    )


@scan_app.command("filegdb", help="Run the FileGDB inventory descriptor scanner.")
def scan_filegdb(
    target: TargetOption,
    output: OutputOption = DEFAULT_OUTPUT,
    token_env: TokenEnvOption = None,
    log_format: LogFormatOption = LogFormat.text,
    log_level: LogLevelOption = LogLevel.info,
    no_network_telemetry_confirm: NoNetworkTelemetryConfirmOption = False,
    user_agent: UserAgentOption = DEFAULT_USER_AGENT,
    max_retries: MaxRetriesOption = 3,
    timeout: TimeoutOption = 30.0,
    validate: ValidateOption = False,
) -> None:
    run_scan_command(
        handler_name="filegdb",
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


@scan_app.command(
    "filegdb-workspace",
    help=(
        "Run the read-only pyogrio/GDAL FileGDB workspace scanner against a "
        "local .gdb directory (requires the 'filegdb' extra)."
    ),
)
def scan_filegdb_workspace(
    target: TargetOption,
    output: OutputOption = DEFAULT_OUTPUT,
    token_env: TokenEnvOption = None,
    log_format: LogFormatOption = LogFormat.text,
    log_level: LogLevelOption = LogLevel.info,
    no_network_telemetry_confirm: NoNetworkTelemetryConfirmOption = False,
    user_agent: UserAgentOption = DEFAULT_USER_AGENT,
    max_retries: MaxRetriesOption = 3,
    timeout: TimeoutOption = 30.0,
    validate: ValidateOption = False,
) -> None:
    run_scan_command(
        handler_name="filegdb-workspace",
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


@scan_app.command(
    "rbac",
    help=(
        "Run the read-only RBAC scanner against a Portal or ArcGIS Server admin "
        "target and write EsriAccessFootprint.json (defaults to stdout)."
    ),
)
def scan_rbac(
    target: TargetOption,
    output: AccessOutputOption = DEFAULT_ACCESS_OUTPUT,
    token_env: TokenEnvOption = None,
    kind: RbacKindOption = RbacKind.portal,
    log_format: LogFormatOption = LogFormat.text,
    log_level: LogLevelOption = LogLevel.info,
    no_network_telemetry_confirm: NoNetworkTelemetryConfirmOption = False,
    user_agent: UserAgentOption = DEFAULT_USER_AGENT,
    max_retries: MaxRetriesOption = 3,
    timeout: TimeoutOption = 30.0,
    validate: AccessValidateOption = False,
) -> None:
    run_rbac_scan_command(
        target=target,
        output=output,
        token_env=token_env,
        kind=kind,
        log_format=log_format,
        log_level=log_level,
        no_network_telemetry_confirm=no_network_telemetry_confirm,
        user_agent=user_agent,
        max_retries=max_retries,
        timeout=timeout,
        validate=validate,
    )
