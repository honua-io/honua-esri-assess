"""ArcGIS Server entitlement collector.

Reads documented admin endpoints (``/arcgis/admin/info``,
``/arcgis/admin/system/licenses``) plus per-service extension lists. Admin
endpoints are guarded behind an admin token; when the caller's token does
not satisfy that scope, the collector falls back to whatever the public
``/arcgis/rest/info`` endpoint exposes and emits ``missing-permission``
diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import quote, urljoin
import logging

from .diagnostics import (
    Diagnostic,
    EntitlementsApiError,
    EntitlementsAuthError,
    EntitlementsConnectionError,
    EntitlementsForbiddenError,
    EntitlementsNotFoundError,
    EntitlementsRateLimitedError,
    EntitlementsSchemaError,
)
from .extensions import resolve_extension
from .http import HttpClient, HttpResponse, safe_url
from .models import (
    ExtensionEntitlement,
    ExtensionStatus,
    ServerLicensing,
    ServiceExtensionRecord,
)


_LOG = logging.getLogger(__name__)


_LICENSED_STATUSES: dict[str, ExtensionStatus] = {
    "good": "licensed",
    "valid": "licensed",
    "licensed": "licensed",
    "ok": "licensed",
    "evaluation": "evaluation",
    "trial": "evaluation",
    "expired": "expired",
    "invalid": "expired",
}


@dataclass(frozen=True)
class ServerEntitlementsResult:
    licensing: ServerLicensing
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ServiceRef:
    """A pointer into ArcGIS Server's service inventory.

    The collector accepts these directly so it can plug into E5's listing
    without re-enumerating folders. ``folder`` is the empty string for the
    root folder.
    """

    folder: str
    name: str
    type: str


class ServerEntitlementsCollector:
    """Enumerate ArcGIS Server licensing and per-service extensions."""

    def __init__(
        self,
        base_url: str,
        client: HttpClient,
        *,
        include_service_extensions: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._client = client
        self._include_service_extensions = include_service_extensions

    def collect(
        self, services: Iterable[ServiceRef] | None = None
    ) -> ServerEntitlementsResult:
        diagnostics: list[Diagnostic] = []
        rest_info = self._get(
            "rest/info",
            scope="server.rest/info",
            diagnostics=diagnostics,
            soft_auth_failure=True,
        )
        product_name, current_version = _read_rest_info(rest_info)

        admin_info = self._get(
            "admin/info",
            scope="server.admin/info",
            diagnostics=diagnostics,
            soft_auth_failure=True,
        )
        edition: str | None = None
        if isinstance(admin_info, dict):
            edition = admin_info.get("edition") or admin_info.get("serverEdition")
            current_version = current_version or admin_info.get("currentVersion")
            product_name = product_name or admin_info.get("productName")

        licenses_payload = self._get(
            "admin/system/licenses",
            scope="server.admin/system/licenses",
            diagnostics=diagnostics,
            soft_auth_failure=True,
        )
        extensions = _read_admin_licenses(licenses_payload, diagnostics)

        service_extensions: list[ServiceExtensionRecord] = []
        if self._include_service_extensions:
            if services is None:
                service_refs = self._list_services(diagnostics)
            else:
                service_refs = list(services)
            for ref in service_refs:
                record = self._collect_service_extensions(ref, diagnostics)
                if record is not None:
                    service_extensions.append(record)

        licensing = ServerLicensing(
            product_name=product_name,
            current_version=current_version,
            edition=edition,
            extensions=extensions,
            service_extensions=service_extensions,
        )
        return ServerEntitlementsResult(licensing=licensing, diagnostics=tuple(diagnostics))

    def _list_services(self, diagnostics: list[Diagnostic]) -> list[ServiceRef]:
        root_payload = self._get(
            "admin/services",
            scope="server.admin/services",
            diagnostics=diagnostics,
            soft_auth_failure=True,
        )
        if not isinstance(root_payload, dict):
            return []

        refs = list(_service_refs_from_listing(root_payload, folder=""))
        folders = root_payload.get("folders")
        if isinstance(folders, list):
            for raw_folder in folders:
                if not raw_folder:
                    continue
                folder = str(raw_folder)
                folder_payload = self._get(
                    f"admin/services/{quote(folder, safe='')}",
                    scope=f"server.admin/services/{folder}",
                    diagnostics=diagnostics,
                    soft_auth_failure=True,
                )
                refs.extend(_service_refs_from_listing(folder_payload, folder=folder))
        return refs

    def _collect_service_extensions(
        self, ref: ServiceRef, diagnostics: list[Diagnostic]
    ) -> ServiceExtensionRecord | None:
        path = _service_admin_path(ref)
        try:
            payload = self._get(
                path,
                scope=f"server.{path}",
                diagnostics=diagnostics,
                soft_auth_failure=True,
            )
        except EntitlementsApiError:
            diagnostics.append(
                Diagnostic(
                    code="unresolved-reference",
                    severity="warn",
                    message="Service extension lookup failed; skipping this service.",
                    scope=f"server.{path}",
                )
            )
            return None
        if not isinstance(payload, dict):
            return None
        soes = _names_from_extension_list(payload.get("extensions"))
        sois = _names_from_extension_list(payload.get("interceptors"))
        service_path = "rest/services/"
        if ref.folder:
            service_path += f"{quote(ref.folder, safe='')}/"
        service_path += f"{quote(ref.name, safe='')}/{quote(ref.type, safe='')}"
        service_url = urljoin(self._base_url, service_path)
        return ServiceExtensionRecord(
            service_url=safe_url(service_url),
            soes=soes,
            sois=sois,
        )

    def _get(
        self,
        path: str,
        *,
        scope: str,
        diagnostics: list[Diagnostic],
        soft_auth_failure: bool,
    ) -> Any:
        url = urljoin(self._base_url, path)
        try:
            response = self._client.get_json(url)
        except ConnectionError as exc:
            raise EntitlementsConnectionError(
                f"could not reach Server endpoint {safe_url(url)}: {exc}"
            ) from exc
        except ValueError as exc:
            raise EntitlementsSchemaError(
                f"unparseable response from Server endpoint {safe_url(url)}: {exc}"
            ) from exc
        return _interpret_response(
            response,
            url=url,
            scope=scope,
            diagnostics=diagnostics,
            soft_auth_failure=soft_auth_failure,
        )


def _read_rest_info(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    return payload.get("productName"), payload.get("currentVersion")


def _service_refs_from_listing(payload: Any, *, folder: str) -> Iterable[ServiceRef]:
    if not isinstance(payload, dict):
        return []
    services = payload.get("services")
    if not isinstance(services, list):
        return []
    refs: list[ServiceRef] = []
    for entry in services:
        if not isinstance(entry, dict):
            continue
        name = entry.get("serviceName") or entry.get("name")
        service_type = entry.get("type")
        if not name or not service_type:
            continue
        refs.append(ServiceRef(folder=folder, name=str(name), type=str(service_type)))
    return refs


def _service_admin_path(ref: ServiceRef) -> str:
    parts = ["admin", "services"]
    if ref.folder:
        parts.append(quote(ref.folder, safe=""))
    parts.append(f"{quote(ref.name, safe='')}.{quote(ref.type, safe='')}")
    return "/".join(parts)


def _read_admin_licenses(
    payload: Any, diagnostics: list[Diagnostic]
) -> list[ExtensionEntitlement]:
    if payload is None:
        return []
    if not isinstance(payload, dict):
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                severity="warn",
                message="Server admin/system/licenses returned an unexpected shape.",
                scope="server.admin/system/licenses",
            )
        )
        return []
    extensions: list[ExtensionEntitlement] = []
    raw_entries: list[Any] = []
    # The 11.x shape carries entries under ``extensions``; older builds use
    # ``licenseLevel`` and ``products[]``. Tolerate both.
    if isinstance(payload.get("extensions"), list):
        raw_entries.extend(payload["extensions"])
    if isinstance(payload.get("products"), list):
        raw_entries.extend(payload["products"])
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        code = entry.get("name") or entry.get("code") or entry.get("id")
        if not code:
            continue
        resolved = resolve_extension(str(code))
        status = _map_status(entry.get("status") or entry.get("state"))
        extensions.append(
            ExtensionEntitlement(
                code=resolved.code,
                name=resolved.name,
                status=status,
                source="server-admin-licenses",
            )
        )
        if not resolved.known:
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message=(
                        "ArcGIS Server reported an extension code that is not in the "
                        "static catalog; recorded verbatim."
                    ),
                    scope=f"server.admin/system/licenses.extensions.{resolved.code}",
                )
            )
    return extensions


def _map_status(value: Any) -> ExtensionStatus:
    if not isinstance(value, str):
        return "unknown"
    return _LICENSED_STATUSES.get(value.strip().lower(), "unknown")


def _names_from_extension_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            continue
        name = entry.get("typeName") or entry.get("name")
        if name:
            names.append(str(name))
    return sorted(set(names))


def _interpret_response(
    response: HttpResponse,
    *,
    url: str,
    scope: str,
    diagnostics: list[Diagnostic],
    soft_auth_failure: bool,
) -> Any:
    status = response.status_code
    body = response.body
    if status == 200 and isinstance(body, dict):
        error_obj = body.get("error")
        if isinstance(error_obj, dict):
            code = int(error_obj.get("code") or 0)
            if code in {401, 498, 499} and soft_auth_failure:
                diagnostics.append(
                    Diagnostic(
                        code="missing-permission",
                        severity="warn",
                        message=(
                            "ArcGIS Server denied admin access; continuing with public "
                            "REST data only."
                        ),
                        scope=scope,
                    )
                )
                return None
            if code == 403 and soft_auth_failure:
                diagnostics.append(
                    Diagnostic(
                        code="missing-permission",
                        severity="warn",
                        message="ArcGIS Server returned forbidden; skipping endpoint.",
                        scope=scope,
                    )
                )
                return None
            if code == 429:
                raise EntitlementsRateLimitedError(
                    f"ArcGIS Server endpoint {safe_url(url)} rate-limited the scan."
                )
            if code in {401, 498, 499}:
                raise EntitlementsAuthError(
                    f"ArcGIS Server endpoint {safe_url(url)} requires authentication."
                )
            if code == 403:
                raise EntitlementsForbiddenError(
                    f"ArcGIS Server endpoint {safe_url(url)} denied access."
                )
            if code == 404:
                raise EntitlementsNotFoundError(
                    f"ArcGIS Server endpoint {safe_url(url)} was not found."
                )
            raise EntitlementsApiError(
                f"ArcGIS Server endpoint {safe_url(url)} returned error envelope code={code}."
            )
        return body
    if status in {401, 403} and soft_auth_failure:
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                severity="warn",
                message=(
                    "ArcGIS Server endpoint requires admin scope; the scan is "
                    "continuing with public information only."
                ),
                scope=scope,
            )
        )
        return None
    if status == 404 and soft_auth_failure:
        diagnostics.append(
            Diagnostic(
                code="unresolved-reference",
                severity="warn",
                message="ArcGIS Server endpoint not found; skipping.",
                scope=scope,
            )
        )
        return None
    if status == 429:
        raise EntitlementsRateLimitedError(
            f"ArcGIS Server endpoint {safe_url(url)} rate-limited the scan."
        )
    if status == 401:
        raise EntitlementsAuthError(
            f"ArcGIS Server endpoint {safe_url(url)} requires authentication."
        )
    if status == 403:
        raise EntitlementsForbiddenError(
            f"ArcGIS Server endpoint {safe_url(url)} denied access."
        )
    if status == 404:
        raise EntitlementsNotFoundError(
            f"ArcGIS Server endpoint {safe_url(url)} was not found."
        )
    if 200 <= status < 300:
        return body
    raise EntitlementsApiError(
        f"ArcGIS Server endpoint {safe_url(url)} returned HTTP {status}."
    )
