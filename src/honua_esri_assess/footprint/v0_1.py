"""Emitter for the published EsriFootprint.json v0.1 contract."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

from honua_esri_assess.diagnostics import Diagnostic
from honua_esri_assess.footprint.licensing import (
    licensing_facet_to_dict,
    portal_licensing_to_dict,
    server_licensing_to_dict,
)
from honua_esri_assess.portal.models import ItemRecord, PortalScanResult
from honua_esri_assess.server._safe import credential_free_url
from honua_esri_assess.server.models import (
    ScanDiagnostic,
    ServerScanResult,
    ServiceRecord,
)

SCHEMA_VERSION = "v0.1"
PRODUCER_NAME = "honua-esri-assess"

__all__ = [
    "SCHEMA_VERSION",
    "PRODUCER_NAME",
    "licensing_facet_to_dict",
    "portal_licensing_to_dict",
    "server_licensing_to_dict",
    "to_footprint_v0_1",
]

DIAGNOSTIC_CODE_MAP = {
    "portal.users.skipped": "partial-coverage",
    "portal.users.forbidden": "missing-permission",
    "portal.users.rate-limited": "rate-limited",
    "portal.users.failed": "partial-coverage",
    "portal.groups.forbidden": "missing-permission",
    "portal.groups.rate-limited": "rate-limited",
    "portal.groups.failed": "partial-coverage",
    "portal.items.forbidden": "missing-permission",
    "portal.items.rate-limited": "rate-limited",
    "portal.items.failed": "partial-coverage",
    "portal.item-probe.forbidden": "missing-permission",
    "portal.item-probe.rate-limited": "rate-limited",
    "portal.item-probe.failed": "unresolved-reference",
    "portal.org-id.missing": "partial-coverage",
}

SERVER_DIAGNOSTIC_CODE_MAP = {
    "server.auth": "missing-permission",
    "server.forbidden": "missing-permission",
    "server.info.partial": "partial-coverage",
    "server.folder.connection": "partial-coverage",
    "server.folder.forbidden": "missing-permission",
    "server.folder.error": "partial-coverage",
    "server.folder.nested": "partial-coverage",
    "server.folder.rate-limited": "rate-limited",
    "server.not-found": "partial-coverage",
    "server.rate-limited": "rate-limited",
    "server.service.deep-failed": "partial-coverage",
    "server.service.malformed": "unsupported-item-type",
    "server.service.missing-permission": "missing-permission",
    "server.service.rate-limited": "rate-limited",
    "server.service.unknown-type": "unsupported-item-type",
}


def to_footprint_v0_1(
    result: PortalScanResult | ServerScanResult,
    *,
    tool_version: str,
    generated_at: datetime | None = None,
    captured_at: datetime | None = None,
    target_url: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable EsriFootprint.json v0.1 object."""

    if isinstance(result, PortalScanResult):
        return _portal_to_footprint(
            result,
            tool_version=tool_version,
            generated_at=generated_at,
        )
    if isinstance(result, ServerScanResult):
        return _server_to_footprint(
            result,
            tool_version=tool_version,
            generated_at=generated_at,
            captured_at=captured_at,
            target_url=target_url,
        )
    raise TypeError(f"unsupported v0.1 footprint source: {type(result).__name__}")


def _portal_to_footprint(
    result: PortalScanResult,
    *,
    tool_version: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    emitted_at = _utc(generated_at or datetime.now(timezone.utc))
    captured_at = _utc(result.captured_at)
    item_counts = Counter(item.item_type or "Unknown" for item in result.items)
    sharing_summary = Counter(_sharing_value(item.access) for item in result.items)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _format_rfc3339(emitted_at),
        "tool": {"name": PRODUCER_NAME, "version": tool_version},
        "source": {
            "kind": "arcgis-online",
            "locator": _portal_locator(result.org.portal_url, result.org.id),
            "capturedAt": _format_rfc3339(captured_at),
        },
        "portal": {
            "orgId": result.org.id or "unknown",
            "orgUrl": result.org.portal_url,
            "itemCounts": dict(sorted(item_counts.items())),
            "sharingSummary": {
                "private": sharing_summary.get("private", 0),
                "org": sharing_summary.get("org", 0),
                "public": sharing_summary.get("public", 0),
                "shared": sharing_summary.get("shared", 0),
            },
        },
        "inventory": [_portal_item_to_dict(item) for item in result.items],
        "counts": {
            "items": {
                "portal-item": len(result.items),
                "server-service": 0,
                "filegdb-feature-class": 0,
            },
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [
            _portal_diagnostic_to_dict(diagnostic)
            for diagnostic in result.diagnostics
        ],
    }


def _server_to_footprint(
    result: ServerScanResult,
    *,
    tool_version: str,
    generated_at: datetime | None = None,
    captured_at: datetime | None = None,
    target_url: str | None = None,
) -> dict[str, Any]:
    generated_stamp = _utc(generated_at or datetime.now(timezone.utc))
    captured_stamp = _utc(captured_at or generated_stamp)
    service_counts = Counter(service.service_type for service in result.services)
    omitted = _services_omitted_from_inventory(result.diagnostics)
    inventory = [
        _server_service_to_dict(service)
        for service in result.services
        if _service_identity(service) not in omitted
    ]
    diagnostics = [
        _server_diagnostic_to_dict(diagnostic)
        for diagnostic in result.diagnostics
    ]

    server: dict[str, Any] = {
        "folders": [folder.name for folder in result.folders],
        "serviceCounts": {
            service_type: service_counts[service_type]
            for service_type in sorted(service_counts)
        },
    }
    version = result.info.current_version or result.info.full_version
    if version:
        server["version"] = version

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _format_rfc3339(generated_stamp),
        "tool": {"name": PRODUCER_NAME, "version": tool_version},
        "source": {
            "kind": "arcgis-server",
            "locator": _server_locator(result.info.url or target_url or ""),
            "capturedAt": _format_rfc3339(captured_stamp),
        },
        "server": server,
        "inventory": inventory,
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": len(inventory),
                "filegdb-feature-class": 0,
            },
            "layers": sum(item["layerCount"] for item in inventory),
            "featureClasses": 0,
        },
        "diagnostics": diagnostics,
    }


def _portal_item_to_dict(item: ItemRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "portal-item",
        "id": item.id,
        "type": item.item_type or "Unknown",
        "owner": item.owner or "unknown",
        "title": item.title or item.id,
        "sharing": _sharing_value(item.access),
        "modified": item.modified or "1970-01-01T00:00:00Z",
        "dependencies": [],
    }
    extent = _extent_from_item(item)
    if extent:
        payload["extent"] = extent
    return payload


def _portal_diagnostic_to_dict(diagnostic: Diagnostic) -> dict[str, Any]:
    code = DIAGNOSTIC_CODE_MAP.get(diagnostic.code, "partial-coverage")
    payload: dict[str, Any] = {
        "code": code,
        "severity": _severity(diagnostic.severity),
        "message": diagnostic.message,
        "scope": _diagnostic_scope(diagnostic),
    }
    if code == "missing-permission":
        payload["hint"] = (
            "Re-run with an ArcGIS Online token that can read the missing "
            "organization resources."
        )
    return payload


_ROOT_FOLDER_SENTINEL = "_root"


def _service_identity(service: ServiceRecord) -> tuple[str, str, str]:
    return (service.folder or _ROOT_FOLDER_SENTINEL, service.name, service.service_type)


def _services_omitted_from_inventory(
    diagnostics: tuple[ScanDiagnostic, ...],
) -> set[tuple[str, str, str]]:
    terminal_codes = {
        "server.auth",
        "server.forbidden",
        "server.rate-limited",
        "server.service.missing-permission",
        "server.service.rate-limited",
    }
    omitted: set[tuple[str, str, str]] = set()
    prefix = "services/"
    for diag in diagnostics:
        if diag.code not in terminal_codes or not diag.field:
            continue
        if not diag.field.startswith(prefix):
            continue
        parts = diag.field[len(prefix) :].split("/")
        if len(parts) >= 3:
            folder, name, service_type = parts[0], parts[1], parts[2]
            omitted.add((folder or _ROOT_FOLDER_SENTINEL, name, service_type))
    return omitted


def _server_service_to_dict(service: ServiceRecord) -> dict[str, Any]:
    return {
        "kind": "server-service",
        "serviceUrl": credential_free_url(service.url),
        "serviceType": service.service_type,
        "folder": service.folder or "",
        "layerCount": len(service.layers),
    }


def _server_diagnostic_to_dict(diagnostic: ScanDiagnostic) -> dict[str, Any]:
    return {
        "code": SERVER_DIAGNOSTIC_CODE_MAP.get(diagnostic.code, "partial-coverage"),
        "severity": _severity(diagnostic.severity),
        "message": diagnostic.message,
        "scope": diagnostic.field or "arcgis-server",
    }


def _services_omitted_from_inventory(
    diagnostics: tuple[ScanDiagnostic, ...],
) -> set[tuple[str, str, str] | str]:
    terminal_codes = {
        "server.auth",
        "server.forbidden",
        "server.rate-limited",
        "server.service.missing-permission",
        "server.service.rate-limited",
    }
    omitted: set[tuple[str, str, str] | str] = set()
    prefix = "services/"
    for diagnostic in diagnostics:
        if diagnostic.code not in terminal_codes or not diagnostic.field:
            continue
        if not diagnostic.field.startswith(prefix):
            continue
        parts = diagnostic.field[len(prefix) :].split("/")
        if len(parts) >= 3:
            folder, name, service_type = parts[0], parts[1], parts[2]
            omitted.add((folder or "_root", name, service_type))
        elif parts and parts[0]:
            omitted.add(parts[0])
    return omitted


def _service_identity(service: ServiceRecord) -> tuple[str, str, str]:
    return (service.folder or "_root", service.name, service.service_type)


def _server_locator(value: str) -> str:
    safe = credential_free_url(value)
    parts = urlsplit(safe)
    if not parts.scheme or not parts.netloc:
        return safe
    path = parts.path.rstrip("/")
    lowered = path.lower()
    if lowered.endswith("/rest/services"):
        canonical_path = path
    elif lowered.endswith("/rest"):
        canonical_path = f"{path}/services"
    elif lowered.endswith("/arcgis") or lowered == "":
        canonical_path = f"{path or '/arcgis'}/rest/services"
    else:
        canonical_path = path
    return urlunsplit((parts.scheme, parts.netloc, canonical_path, "", ""))


def _portal_locator(portal_url: str, org_id: str | None) -> str:
    host = urlparse(portal_url).netloc
    return f"{host}/{org_id or 'unknown'}"


def _sharing_value(access: str | None) -> str:
    if access in {"private", "org", "public", "shared"}:
        return access
    return "private"


def _severity(value: str) -> str:
    if value == "warning":
        return "warn"
    if value in {"info", "warn", "error"}:
        return value
    return "warn"


def _diagnostic_scope(diagnostic: Diagnostic) -> str:
    item_id = diagnostic.context.get("itemId") if diagnostic.context else None
    if item_id:
        return str(item_id)
    return "arcgis-online"


def _extent_from_item(item: ItemRecord) -> dict[str, Any] | None:
    extent = getattr(item, "extent", None)
    if not isinstance(extent, list):
        return None
    bbox: list[float] | None = None
    if len(extent) == 4 and all(isinstance(value, (int, float)) for value in extent):
        bbox = [float(value) for value in extent]
    elif (
        len(extent) == 2
        and all(isinstance(pair, list) and len(pair) == 2 for pair in extent)
        and all(isinstance(value, (int, float)) for pair in extent for value in pair)
    ):
        bbox = [
            float(extent[0][0]),
            float(extent[0][1]),
            float(extent[1][0]),
            float(extent[1][1]),
        ]
    if bbox is None:
        return None
    return {"bbox": bbox, "crs": {"wkid": 4326}}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_rfc3339(value: datetime) -> str:
    value = _utc(value).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")
