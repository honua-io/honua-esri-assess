"""EsriFootprint v0.1 builder and licensing facet utilities."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from .. import __version__
from ..diagnostics import Diagnostic
from ..redaction import sanitize_handoff_url
from .v0_1 import (
    licensing_facet_to_dict,
    portal_licensing_to_dict,
    server_licensing_to_dict,
)

SCHEMA_VERSION = "v0.1"
TOOL_NAME = "honua-esri-assess"
ITEM_KINDS = ("portal-item", "server-service", "filegdb-feature-class")


def build_footprint(
    *,
    source_kind: str,
    target: str,
    inventory: Iterable[dict[str, Any]],
    diagnostics: Iterable[Diagnostic],
    portal: dict[str, Any] | None = None,
    server: dict[str, Any] | None = None,
    filegdb: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    items = list(inventory)
    now = generated_at or datetime.now(timezone.utc)
    captured = captured_at or now
    source = _source_block(
        source_kind, target, portal=portal, filegdb=filegdb, captured_at=captured
    )
    footprint: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {"name": TOOL_NAME, "version": __version__},
        "source": source,
        "inventory": items,
        "counts": _counts(items),
        "diagnostics": [d.to_dict() for d in diagnostics],
    }
    if source_kind == "arcgis-online":
        footprint["portal"] = portal or _default_portal(target)
    elif source_kind == "arcgis-server":
        footprint["server"] = server or {"folders": [], "serviceCounts": {}}
    elif source_kind == "filegdb":
        footprint["filegdb"] = filegdb or _default_filegdb(target)
    return footprint


def write_footprint(footprint: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(footprint, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def path_hash(value: str | Path) -> str:
    material = f"honua-esri-assess:v0.1:{Path(value)}"
    return "sha256:" + sha256(material.encode("utf-8")).hexdigest()


def _source_block(
    source_kind: str,
    target: str,
    *,
    portal: dict[str, Any] | None,
    filegdb: dict[str, Any] | None,
    captured_at: datetime,
) -> dict[str, Any]:
    if source_kind == "arcgis-online":
        facet = portal or _default_portal(target)
        org_url = str(facet.get("orgUrl") or _origin_url(target))
        org_id = str(facet.get("orgId") or "unknown")
        host = urlsplit(org_url).netloc or "unknown.local"
        locator = f"{host}/{org_id}"
    elif source_kind == "arcgis-server":
        locator = sanitize_handoff_url(target)
    elif source_kind == "filegdb":
        facet = filegdb or _default_filegdb(target)
        locator = str(facet.get("pathHash") or path_hash(target))
    else:
        raise ValueError(f"Unsupported source kind {source_kind!r}")

    return {
        "kind": source_kind,
        "locator": locator,
        "capturedAt": captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _default_portal(target: str) -> dict[str, Any]:
    return {"orgId": "unknown", "orgUrl": _origin_url(target), "itemCounts": {}}


def _default_filegdb(target: str) -> dict[str, Any]:
    return {"pathHash": path_hash(target), "featureClassCount": 0}


def _origin_url(target: str) -> str:
    parsed = urlsplit(sanitize_handoff_url(target))
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://unknown.local"


def _counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    item_counts = {kind: 0 for kind in ITEM_KINDS}
    for item in items:
        kind = item.get("kind")
        if kind in item_counts:
            item_counts[kind] += 1

    return {
        "items": item_counts,
        "layers": sum(
            int(item.get("layerCount", 0) or 0)
            for item in items
            if item.get("kind") == "server-service"
        ),
        "featureClasses": item_counts["filegdb-feature-class"],
    }


__all__ = [
    "ITEM_KINDS",
    "SCHEMA_VERSION",
    "TOOL_NAME",
    "build_footprint",
    "licensing_facet_to_dict",
    "path_hash",
    "portal_licensing_to_dict",
    "server_licensing_to_dict",
    "write_footprint",
]
