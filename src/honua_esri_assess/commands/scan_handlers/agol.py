"""ArcGIS Online Portal scanner adapter."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from honua_esri_assess import __version__
from honua_esri_assess.access import (
    AccessExportError,
    AccessFacet,
    ItemSharing,
    PortalAccessCollector,
    build_recommendation,
)
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
from honua_esri_assess.portal import (
    AnonymousCredential,
    PortalClient,
    PortalScanner,
    RetryPolicy,
    TokenCredential,
)
from honua_esri_assess.portal.auth import Credential


def run(options: ScanOptions) -> ScanResult:
    credential: Credential = (
        TokenCredential(options.token) if options.token else AnonymousCredential()
    )
    try:
        client = PortalClient(
            options.target,
            credential=credential,
            timeout=options.timeout,
            retry_policy=RetryPolicy(attempts=max(1, options.max_retries + 1)),
            user_agent=options.user_agent,
        )
        result = PortalScanner(client, deep=False).scan()
    except AssessmentError as exc:
        error = DiagnosticError(
            exc.message,
            code=exc.code,
            scope="agol",
        )
        error.exit_code = exc.exit_code
        raise error from exc

    footprint = to_footprint_v0_1(result, tool_version=__version__)
    diagnostics: list[Diagnostic] = list(result.diagnostics)

    if options.include_access and options.token:
        footprint, access_diags = _collect_portal_access(
            footprint=footprint,
            target=client.portal_url,
            token=options.token,
            user_agent=options.user_agent,
            timeout=options.timeout,
            group_cap=options.access_group_cap,
            max_attempts=max(1, options.max_retries + 1),
        )
        diagnostics.extend(access_diags)

    return ScanResult(
        footprint=footprint,
        diagnostics=tuple(diagnostics),
    )


def _collect_portal_access(
    *,
    footprint: dict[str, Any],
    target: str,
    token: str,
    user_agent: str,
    timeout: float,
    group_cap: int,
    max_attempts: int,
) -> tuple[dict[str, Any], list[Diagnostic]]:
    client = RequestsHttpClient(
        token=token,
        user_agent=user_agent,
        default_timeout=timeout,
        max_attempts=max_attempts,
    )
    collector = PortalAccessCollector(target, client, group_cap=group_cap)
    item_sharing = _item_sharing_from_inventory(footprint.get("inventory", []))
    try:
        result = collector.collect(item_sharing=item_sharing)
    except AccessExportError as exc:
        raise DiagnosticError(
            "Access export failed; the source endpoint refused the admin probe.",
            code="access-export-failed",
            scope="access",
        ) from exc

    recommendation = build_recommendation(portal=result.access)
    portal_access = replace(result.access, mapping_recommendation=recommendation)
    new_footprint = apply_access_facet(footprint, AccessFacet(portal=portal_access))
    _embed_access_diagnostics(new_footprint, result.diagnostics)
    diagnostics = [_to_cli_diagnostic(diag) for diag in result.diagnostics]
    return new_footprint, diagnostics


def _embed_access_diagnostics(
    footprint: dict[str, Any],
    access_diagnostics: tuple[AccessDiagnostic, ...],
) -> None:
    if not access_diagnostics:
        return
    existing = footprint.get("diagnostics")
    if not isinstance(existing, list):
        existing = []
    existing.extend(diag.to_dict() for diag in access_diagnostics)
    footprint["diagnostics"] = existing


def _item_sharing_from_inventory(
    inventory: list[Any],
) -> list[ItemSharing]:
    out: list[ItemSharing] = []
    for record in inventory:
        if not isinstance(record, dict):
            continue
        if record.get("kind") != "portal-item":
            continue
        item_id = record.get("id")
        owner = record.get("owner")
        sharing = record.get("sharing")
        if not isinstance(item_id, str) or not isinstance(owner, str):
            continue
        if sharing not in {"private", "org", "public", "shared"}:
            continue
        out.append(
            ItemSharing(
                item_id=item_id,
                owner=owner,
                access_level=sharing,  # type: ignore[arg-type]
                shared_with_group_ids=(),
            )
        )
    return out


def _to_cli_diagnostic(diag: AccessDiagnostic) -> Diagnostic:
    return Diagnostic(
        code=diag.code,
        severity=diag.severity,
        message=diag.message,
        scope=diag.scope,
        hint=diag.hint,
    )
