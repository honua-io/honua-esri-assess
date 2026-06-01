"""ArcGIS Server REST scanner adapter."""

from __future__ import annotations

from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from honua_esri_assess import __version__
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.diagnostics import AssessmentError, Diagnostic, DiagnosticError
from honua_esri_assess.entitlements.diagnostics import (
    Diagnostic as AdminDiagnostic,
)
from honua_esri_assess.entitlements.diagnostics import (
    EntitlementsRateLimitedError,
)
from honua_esri_assess.entitlements.http import HttpResponse
from honua_esri_assess.footprint.binding import BindingPlan, build_binding_plan
from honua_esri_assess.footprint.v0_1 import to_footprint_v0_1
from honua_esri_assess.scanners.admin_usage import AdminUsageCollector
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
        result = ServerScanner(deep=True, layer_detail=True).scan(client)
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

    binding_plan: BindingPlan | None = None
    admin_diagnostics: tuple[AdminDiagnostic, ...] = ()
    if options.admin_usage:
        binding_plan, admin_diagnostics = _collect_admin_usage(client, options)

    footprint = to_footprint_v0_1(
        result,
        tool_version=__version__,
        target_url=options.target,
        binding_plan=binding_plan,
    )
    return ScanResult(
        footprint=footprint,
        diagnostics=(
            *(_to_cli_diagnostic(diagnostic) for diagnostic in result.diagnostics),
            *(_admin_to_cli_diagnostic(diagnostic) for diagnostic in admin_diagnostics),
        ),
    )


class _AdminHttpClient:
    """``requests``-backed, GET-only adapter satisfying the HttpClient protocol.

    The Admin-API usage collector needs the raw HTTP status code (401/403/404/
    429) to decide how to degrade, so it cannot reuse ``ServerClient.get_json``
    (which unwraps the body and raises typed errors). This adapter reuses the
    scan's ``requests`` session, user-agent, and credential, applies ``f=json``,
    and returns a credential-free :class:`HttpResponse`. No write verb exists.
    """

    def __init__(self, *, client: ServerClient, credential: Credential) -> None:
        self._session = client._session
        self._credential = credential
        self._user_agent = client.user_agent
        self._default_timeout = client.timeout

    def get_json(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        *,
        timeout: float | None = None,
    ) -> HttpResponse:
        request_params: dict[str, str] = {"f": "json"}
        if params:
            request_params.update({k: str(v) for k, v in params.items()})
        request_params = self._credential.apply(request_params)
        effective = timeout if timeout is not None else self._default_timeout
        try:
            response = self._session.get(
                url,
                params=request_params,
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                timeout=effective,
            )
        except Exception as exc:  # requests.RequestException et al.
            raise ConnectionError(str(exc)) from exc
        body = None
        if response.content:
            try:
                body = response.json()
            except ValueError as exc:
                raise ValueError(
                    f"non-JSON response from Esri admin endpoint: {exc}"
                ) from exc
        return HttpResponse(status_code=response.status_code, body=body)


def _collect_admin_usage(
    client: ServerClient,
    options: ScanOptions,
) -> tuple[BindingPlan, tuple[AdminDiagnostic, ...]]:
    """Run the read-only Admin-API usage/data-store pull (token-gated, opt-in).

    Reaches ``/admin/usagereports`` and ``/admin/data/items`` with GET only.
    A missing admin scope, denied endpoint, or rate-limit degrades to typed
    diagnostics rather than aborting the scan, so the additive ``bindingPlan``
    facet is simply omitted when the data is unavailable.
    """

    credential: Credential = (
        TokenCredential(options.token) if options.token else AnonymousCredential()
    )
    http = _AdminHttpClient(client=client, credential=credential)
    collector = AdminUsageCollector(_admin_base(client.rest_root), http)
    try:
        admin_result = collector.collect()
    except EntitlementsRateLimitedError:
        return (
            build_binding_plan(usage={}, registrations=[]),
            (
                AdminDiagnostic(
                    code="rate-limited",
                    severity="warn",
                    message=(
                        "Admin-API usage pull was rate-limited; usage ranking "
                        "and binding-mode routing are omitted for this scan."
                    ),
                    scope="server.admin",
                ),
            ),
        )
    plan = build_binding_plan(
        usage=admin_result.service_usage,
        registrations=admin_result.registrations,
    )
    return plan, admin_result.diagnostics


def _admin_base(rest_root: str) -> str:
    """Derive the ``/arcgis/`` admin base from the canonical REST root.

    ``rest_root`` is ``https://host/arcgis/rest/services``; the Admin-API lives
    at ``https://host/arcgis/admin/...`` so the collector base is the
    ``/arcgis/`` prefix (the collector appends ``admin/...`` itself).
    """

    parts = urlsplit(rest_root)
    path = parts.path
    lowered = path.lower()
    suffix = "/rest/services"
    if lowered.endswith(suffix):
        path = path[: -len(suffix)]
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/") + "/", "", ""))


def _to_cli_diagnostic(diagnostic: ScanDiagnostic) -> Diagnostic:
    return Diagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        message=diagnostic.message,
        scope=diagnostic.field or "arcgis-server",
    )


def _admin_to_cli_diagnostic(diagnostic: AdminDiagnostic) -> Diagnostic:
    return Diagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        message=diagnostic.message,
        scope=diagnostic.scope,
        hint=diagnostic.hint,
    )
