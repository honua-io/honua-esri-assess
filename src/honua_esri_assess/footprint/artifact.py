"""EsriFootprint v0.1 builder and artifact utilities."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from honua_esri_assess import __version__
from honua_esri_assess.diagnostics import Diagnostic
from honua_esri_assess.redaction import sanitize_handoff_url

SCHEMA_VERSION = "v0.2"
TOOL_NAME = "honua-esri-assess"
ITEM_KINDS = ("portal-item", "server-service", "filegdb-feature-class")


def installed_tool_version() -> str:
    """Return the installed package version, falling back in editable checkouts."""

    try:
        return version(TOOL_NAME)
    except PackageNotFoundError:
        return __version__


def utc_timestamp() -> str:
    """Return an RFC3339 UTC timestamp accepted by the v0.1 schema."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


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
        source_kind,
        target,
        portal=portal,
        filegdb=filegdb,
        captured_at=captured,
    )
    footprint: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {"name": TOOL_NAME, "version": installed_tool_version()},
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
    else:
        raise ValueError(f"Unsupported source kind {source_kind!r}")
    return footprint


def footprint_to_json(footprint: Mapping[str, Any]) -> str:
    """Serialize a footprint with stable, human-readable formatting."""

    return json.dumps(footprint, indent=2, sort_keys=True) + "\n"


def write_footprint(footprint: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(footprint_to_json(footprint), encoding="utf-8")


def write_footprint_json(footprint: Mapping[str, Any], output_path: Path) -> None:
    """Write an EsriFootprint.json artifact."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(footprint_to_json(footprint), encoding="utf-8")


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
    "footprint_to_json",
    "installed_tool_version",
    "path_hash",
    "utc_timestamp",
    "write_footprint",
    "write_footprint_json",
]
