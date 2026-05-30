"""ArcGIS Server REST scanner adapter."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from honua_esri_assess import __version__
from honua_esri_assess.access import (
    AccessExportError,
    AccessFacet,
    ServerAccessCollector,
    build_recommendation,
)
from honua_esri_assess.access.server import ServiceRef
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.diagnostics import (
    AssessmentError,
    Diagnostic,
    DiagnosticError,
)
from honua_esri_assess.entitlements.diagnostics import Diagnostic as AccessDiagnostic
from honua_esri_assess.entitlements.http import RequestsHttpClient
from honua_esri_assess.footprint.access import apply_access_facet
from honua_esri_assess.footprint.v0_1 import to_footprint_v0_1
from honua_esri_assess.server import (
    AnonymousCredential,
    RetryPolicy,
    ServerClient,
    ServerScanner,
    TokenCredential,
)
from honua_esri_assess.server.auth import Credential
from honua_esri_assess.server.models import ScanDiagnostic, ServiceRecord


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
    diagnostics: list[Diagnostic] = [
        _to_cli_diagnostic(diagnostic) for diagnostic in result.diagnostics
    ]
    if options.include_access and options.token:
        footprint, access_diags = _collect_server_access(
            footprint=footprint,
            target=options.target,
            services=list(result.services),
            token=options.token,
            user_agent=options.user_agent,
            timeout=options.timeout,
        )
        diagnostics.extend(access_diags)
    return ScanResult(
        footprint=footprint,
        diagnostics=tuple(diagnostics),
    )


def _collect_server_access(
    *,
    footprint: dict[str, Any],
    target: str,
    services: list[ServiceRecord],
    token: str,
    user_agent: str,
    timeout: float,
) -> tuple[dict[str, Any], list[Diagnostic]]:
    client = RequestsHttpClient(
        token=token,
        user_agent=user_agent,
        default_timeout=timeout,
    )
    base_url = _arcgis_base_from_target(target)
    collector = ServerAccessCollector(base_url, client)
    service_refs = [
        ServiceRef(
            folder=service.folder or "",
            name=service.name,
            type=service.service_type,
        )
        for service in services
    ]
    try:
        result = collector.collect(services=service_refs)
    except AccessExportError as exc:
        raise DiagnosticError(
            "Access export failed; the source endpoint refused the admin probe.",
            code="access-export-failed",
            scope="access",
        ) from exc

    recommendation = build_recommendation(server=result.access)
    server_access = replace(result.access, mapping_recommendation=recommendation)
    new_footprint = apply_access_facet(footprint, AccessFacet(server=server_access))
    cli_diags = [_to_cli_diagnostic(diag) for diag in result.diagnostics]
    return new_footprint, cli_diags


def _arcgis_base_from_target(target: str) -> str:
    """Return the ArcGIS Server root (``.../arcgis``) for the user target.

    Accepts either the REST services URL or the bare root; the access
    collector hits ``admin/...`` and ``rest/...`` relative to it.
    """

    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(target)
    path = parts.path.rstrip("/")
    lowered = path.lower()
    if lowered.endswith("/rest/services"):
        path = path[: -len("/rest/services")]
    elif lowered.endswith("/rest"):
        path = path[: -len("/rest")]
    if not path:
        path = "/arcgis"
    return urlunsplit((parts.scheme, parts.netloc, path + "/", "", ""))


def _to_cli_diagnostic(diagnostic: ScanDiagnostic | AccessDiagnostic) -> Diagnostic:
    if isinstance(diagnostic, ScanDiagnostic):
        return Diagnostic(
            code=diagnostic.code,
            severity=diagnostic.severity,
            message=diagnostic.message,
            scope=diagnostic.field or "arcgis-server",
        )
    return Diagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        message=diagnostic.message,
        scope=diagnostic.scope,
        hint=diagnostic.hint,
    )
