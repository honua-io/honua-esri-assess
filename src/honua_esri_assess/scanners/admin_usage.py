"""Read-only Admin-API collector for usage reports and data-store routing.

Pulls two documented ArcGIS Server Admin-API endpoints and reduces them to
credential-free, planning-ready facets:

* ``/admin/usagereports`` → per-service observed request volume, used to rank
  services for migration sequencing (see
  :func:`honua_esri_assess.footprint.binding.rank_services_by_usage`).
* ``/admin/data/items`` (data-store registrations) → the declared storage
  ``type`` for each registration, used to recommend a binding mode
  (federate / connect-in-place / materialize) per dataset.

Hard constraints honored here:

* Read-only — only ``get_json`` (HTTP ``GET``) is ever issued; the shared
  :class:`~honua_esri_assess.entitlements.http.HttpClient` protocol exposes no
  write helper.
* Storage type is read from the registration's declared ``type`` /
  ``provider`` fields *only*. Connection strings, hosts, usernames, and
  passwords found in a registration's ``info``/``connectionString`` are never
  parsed and never retained — we keep only a coarse ``connectionKind`` token.
  ArcSDE/GDB internals are never inspected.
* Soft failures (missing admin scope, forbidden, partial payloads) become
  typed :class:`~honua_esri_assess.entitlements.diagnostics.Diagnostic`
  records rather than aborting the scan.

The collector depends only on the :class:`HttpClient` protocol, so the same
fixture stubs used by the entitlements collectors drive these tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from ..entitlements.diagnostics import (
    Diagnostic,
    EntitlementsRateLimitedError,
)
from ..entitlements.http import HttpClient, HttpResponse, safe_url
from ..footprint.binding import (
    DatastoreRegistration,
    connection_kind_for_type,
)


@dataclass(frozen=True)
class AdminUsageResult:
    """Credential-free Admin-API facts for usage ranking and binding routing.

    ``service_usage`` maps a service identifier (``folder/Name.Type`` style,
    as the Admin-API reports it) to its observed request count.
    ``registrations`` is the list of data-store registrations reduced to
    declared type + coarse connection kind.
    """

    service_usage: dict[str, int] = field(default_factory=dict)
    registrations: list[DatastoreRegistration] = field(default_factory=list)
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)


class AdminUsageCollector:
    """Enumerate Admin-API usage reports and data-store registrations."""

    def __init__(self, base_url: str, client: HttpClient) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._client = client

    def collect(self) -> AdminUsageResult:
        diagnostics: list[Diagnostic] = []
        usage = self._collect_usage(diagnostics)
        registrations = self._collect_registrations(diagnostics)
        return AdminUsageResult(
            service_usage=usage,
            registrations=registrations,
            diagnostics=tuple(diagnostics),
        )

    # --- usage reports --------------------------------------------------

    def _collect_usage(self, diagnostics: list[Diagnostic]) -> dict[str, int]:
        payload = self._get(
            "admin/usagereports",
            scope="server.admin/usagereports",
            diagnostics=diagnostics,
        )
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message="Admin usagereports returned an unexpected shape.",
                    scope="server.admin/usagereports",
                )
            )
            return {}
        return _read_usage_reports(payload, diagnostics)

    # --- data-store registrations --------------------------------------

    def _collect_registrations(
        self, diagnostics: list[Diagnostic]
    ) -> list[DatastoreRegistration]:
        payload = self._get(
            "admin/data/items",
            scope="server.admin/data/items",
            diagnostics=diagnostics,
        )
        if payload is None:
            return []
        if not isinstance(payload, dict):
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message="Admin data/items returned an unexpected shape.",
                    scope="server.admin/data/items",
                )
            )
            return []
        return _read_data_items(payload, diagnostics)

    # --- HTTP -----------------------------------------------------------

    def _get(
        self,
        path: str,
        *,
        scope: str,
        diagnostics: list[Diagnostic],
    ) -> Any:
        url = urljoin(self._base_url, path)
        try:
            response = self._client.get_json(url)
        except ConnectionError:
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message=f"Could not reach {safe_url(url)}; skipping endpoint.",
                    scope=scope,
                )
            )
            return None
        except ValueError:
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message=f"Unparseable response from {safe_url(url)}.",
                    scope=scope,
                )
            )
            return None
        return _interpret(response, scope=scope, diagnostics=diagnostics)


def _coerce_error_code(value: Any) -> int:
    """Best-effort parse of an Esri error ``code`` into an int.

    Esri error bodies usually carry a numeric ``code``, but some Enterprise
    variants return a non-numeric or absent value. Parsing must never raise: a
    bad shape degrades to ``0`` (the generic "unknown error" path) rather than
    aborting the scan with an uncaught ``ValueError``.
    """

    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _interpret(
    response: HttpResponse,
    *,
    scope: str,
    diagnostics: list[Diagnostic],
) -> Any:
    status = response.status_code
    body = response.body
    if status == 200 and isinstance(body, dict):
        error_obj = body.get("error")
        if isinstance(error_obj, dict):
            code = _coerce_error_code(error_obj.get("code"))
            return _handle_error_code(code, scope=scope, diagnostics=diagnostics)
        return body
    if status in {401, 403}:
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                severity="warn",
                message=(
                    "Admin endpoint requires admin scope; usage/binding facets "
                    "are skipped and the scan continues."
                ),
                scope=scope,
                hint="Re-run with an ArcGIS Server admin token to enable usage "
                "ranking and binding-mode routing.",
            )
        )
        return None
    if status == 404:
        diagnostics.append(
            Diagnostic(
                code="unresolved-reference",
                severity="warn",
                message="Admin endpoint not found on this server; skipping.",
                scope=scope,
            )
        )
        return None
    if status == 429:
        raise EntitlementsRateLimitedError(
            f"Admin endpoint {scope} rate-limited the scan."
        )
    if 200 <= status < 300:
        return body
    diagnostics.append(
        Diagnostic(
            code="partial-coverage",
            severity="warn",
            message=f"Admin endpoint returned HTTP {status}; skipping.",
            scope=scope,
        )
    )
    return None


def _handle_error_code(
    code: int,
    *,
    scope: str,
    diagnostics: list[Diagnostic],
) -> Any:
    if code in {401, 403, 498, 499}:
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                severity="warn",
                message=(
                    "Admin endpoint denied access; usage/binding facets are "
                    "skipped and the scan continues."
                ),
                scope=scope,
                hint="Re-run with an ArcGIS Server admin token to enable usage "
                "ranking and binding-mode routing.",
            )
        )
        return None
    if code == 429:
        raise EntitlementsRateLimitedError(
            f"Admin endpoint {scope} rate-limited the scan."
        )
    diagnostics.append(
        Diagnostic(
            code="partial-coverage",
            severity="warn",
            message=f"Admin endpoint returned error envelope code={code}.",
            scope=scope,
        )
    )
    return None


def _read_usage_reports(
    payload: dict[str, Any], diagnostics: list[Diagnostic]
) -> dict[str, int]:
    """Reduce a ``/admin/usagereports`` payload to per-service request totals.

    The Admin-API returns one or more report objects, each carrying a
    ``report-data`` matrix of sampled values keyed by a resource URI such as
    ``services/Folder/Name.MapServer``. We sum each resource's samples into a
    single request total per service.
    """

    reports = payload.get("reports")
    if not isinstance(reports, list):
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                severity="warn",
                message="Admin usagereports payload had no reports array.",
                scope="server.admin/usagereports",
            )
        )
        return {}
    totals: dict[str, int] = {}
    for report in reports:
        if not isinstance(report, dict):
            continue
        queries = report.get("queries")
        if not isinstance(queries, list):
            continue
        for query in queries:
            if not isinstance(query, dict):
                continue
            resource_uris = query.get("resourceURIs")
            report_data = query.get("report-data")
            _accumulate_query(resource_uris, report_data, totals)
    return totals


def _accumulate_query(
    resource_uris: Any,
    report_data: Any,
    totals: dict[str, int],
) -> None:
    if not isinstance(resource_uris, list) or not isinstance(report_data, list):
        return
    # report-data is a list (one per metric grouping) of per-resource sample
    # series aligned positionally with resource_uris.
    for grouping in report_data:
        if not isinstance(grouping, list):
            continue
        for index, series in enumerate(grouping):
            if index >= len(resource_uris):
                break
            service = _service_from_resource_uri(resource_uris[index])
            if service is None:
                continue
            totals[service] = totals.get(service, 0) + _sum_samples(series)


def _sum_samples(series: Any) -> int:
    if not isinstance(series, list):
        return 0
    total = 0.0
    for sample in series:
        if isinstance(sample, bool):
            continue
        if isinstance(sample, (int, float)):
            total += float(sample)
    return int(total)


def _service_from_resource_uri(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    trimmed = value.strip().strip("/")
    if trimmed.lower().startswith("services/"):
        trimmed = trimmed[len("services/") :]
    return trimmed or None


def _read_data_items(
    payload: dict[str, Any], diagnostics: list[Diagnostic]
) -> list[DatastoreRegistration]:
    """Reduce a ``/admin/data/items`` payload to redacted registrations.

    Only the declared type/provider and the item path identifier are read.
    The ``info`` block (which may carry a connection string, DB host, or
    credentials) is intentionally never read.
    """

    items = payload.get("items")
    if not isinstance(items, list):
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                severity="warn",
                message="Admin data/items payload had no items array.",
                scope="server.admin/data/items",
            )
        )
        return []
    registrations: list[DatastoreRegistration] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        registration = _registration_from_item(item)
        if registration is not None:
            registrations.append(registration)
    return registrations


def _registration_from_item(item: dict[str, Any]) -> DatastoreRegistration | None:
    item_id = item.get("path") or item.get("id")
    declared_type = item.get("type")
    # Some registrations carry the discriminating storage type one level down
    # in info.type / info.dataStoreConnectionType WITHOUT a connection string;
    # read only that token, never the connection itself.
    info = item.get("info")
    info_type = info.get("type") if isinstance(info, dict) else None
    storage_type = declared_type or info_type
    if not item_id or not storage_type:
        return None
    return DatastoreRegistration(
        item_id=str(item_id),
        type=str(storage_type),
        connection_kind=connection_kind_for_type(str(storage_type)),
    )


__all__ = [
    "AdminUsageCollector",
    "AdminUsageResult",
]
