"""ArcGIS Server REST scanner adapter."""

from __future__ import annotations

from honua_esri_assess import __version__
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.diagnostics import AssessmentError, Diagnostic, DiagnosticError
from honua_esri_assess.footprint.v0_1 import to_footprint_v0_1
from honua_esri_assess.server import (
    AnonymousCredential,
    RetryPolicy,
    ServerClient,
    ServerScanner,
    TokenCredential,
)
from honua_esri_assess.server.auth import Credential
from honua_esri_assess.server.models import ScanDiagnostic


def run(options: ScanOptions) -> ScanResult:
    credential: Credential = (
        TokenCredential(options.token) if options.token else AnonymousCredential()
    )
    try:
        client = ServerClient(
            options.target,
            credential=credential,
            timeout=options.timeout,
            retry=RetryPolicy(max_attempts=max(1, options.max_retries + 1)),
            user_agent=options.user_agent,
        )
        result = ServerScanner(deep=True).scan(client)
    except AssessmentError as exc:
        error = DiagnosticError(
            exc.message,
            code=exc.code,
            scope="server",
        )
        error.exit_code = exc.exit_code
        raise error from exc
    except ValueError as exc:
        raise DiagnosticError(
            "ArcGIS Server scan failed before producing an inventory.",
            code="scanner-error",
            scope="server",
        ) from exc
    footprint = to_footprint_v0_1(
        result,
        tool_version=__version__,
        target_url=options.target,
    )
    return ScanResult(
        footprint=footprint,
        diagnostics=tuple(
            _to_cli_diagnostic(diagnostic) for diagnostic in result.diagnostics
        ),
    )


def _to_cli_diagnostic(diagnostic: ScanDiagnostic) -> Diagnostic:
    return Diagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        message=diagnostic.message,
        scope=diagnostic.field or "arcgis-server",
    )
