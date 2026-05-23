"""Emitter for the published EsriFootprint.json v0.1 contract."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from honua_esri_assess.diagnostics import Diagnostic
from honua_esri_assess.footprint.licensing import (
    licensing_facet_to_dict,
    portal_licensing_to_dict,
    server_licensing_to_dict,
)
from honua_esri_assess.portal.models import ItemRecord, PortalScanResult

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


def to_footprint_v0_1(
    result: PortalScanResult,
    *,
    tool_version: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable EsriFootprint.json v0.1 object."""

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
            _diagnostic_to_dict(diagnostic) for diagnostic in result.diagnostics
        ],
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


def _diagnostic_to_dict(diagnostic: Diagnostic) -> dict[str, Any]:
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
