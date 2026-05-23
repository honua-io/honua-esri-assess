"""Unit tests for deterministic report heuristics."""

from __future__ import annotations

from honua_esri_assess.report.heuristics import (
    manual_review_items,
    recommended_order,
    score_complexity,
)


def _footprint(*, items: int = 0, layers: int = 0, inventory: list[dict] | None = None) -> dict:
    inventory = inventory or [
        {
            "kind": "portal-item",
            "id": f"item-{index}",
            "type": "Feature Service",
            "owner": "gis.admin",
            "title": f"Feature Service {index}",
            "sharing": "org",
            "modified": "2026-05-22T14:02:11Z",
        }
        for index in range(items)
    ]
    return {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.1.0"},
        "source": {
            "kind": "arcgis-online",
            "locator": "example.maps.arcgis.com/0123ABCDEF456789",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "inventory": inventory,
        "counts": {
            "items": {
                "portal-item": items or sum(1 for item in inventory if item["kind"] == "portal-item"),
                "server-service": sum(1 for item in inventory if item["kind"] == "server-service"),
                "filegdb-feature-class": sum(
                    1 for item in inventory if item["kind"] == "filegdb-feature-class"
                ),
            },
            "layers": layers,
            "featureClasses": sum(
                1 for item in inventory if item["kind"] == "filegdb-feature-class"
            ),
        },
        "diagnostics": [],
    }


def test_complexity_bucket_boundaries_use_highest_metric() -> None:
    assert score_complexity(_footprint(items=50, layers=200)).bucket == "Small"
    assert score_complexity(_footprint(items=51, layers=200)).bucket == "Medium"
    assert score_complexity(_footprint(items=500, layers=2_001)).bucket == "Large"
    assert score_complexity(_footprint(items=5_001, layers=200)).bucket == "Very Large"


def test_migration_order_places_data_before_maps_and_apps() -> None:
    footprint = _footprint(
        inventory=[
            {
                "kind": "portal-item",
                "id": "app",
                "type": "Dashboard",
                "owner": "gis.admin",
                "title": "Operations Dashboard",
                "sharing": "org",
                "modified": "2026-05-22T14:02:11Z",
            },
            {
                "kind": "portal-item",
                "id": "map",
                "type": "Web Map",
                "owner": "gis.admin",
                "title": "Operations Map",
                "sharing": "org",
                "modified": "2026-05-22T14:02:11Z",
            },
            {
                "kind": "server-service",
                "serviceUrl": "https://gis.example.com/arcgis/rest/services/Water/FeatureServer",
                "serviceType": "FeatureServer",
                "folder": "",
                "layerCount": 4,
            },
            {
                "kind": "filegdb-feature-class",
                "name": "Parcels",
                "geometryType": "esriGeometryPolygon",
                "sr": {"wkid": 4326},
            },
            {
                "kind": "portal-item",
                "id": "unknown",
                "type": "Other",
                "owner": "gis.admin",
                "title": "Unknown Content",
                "sharing": "private",
                "modified": "2026-05-22T14:02:11Z",
            },
        ]
    )

    group_titles = [group.title for group in recommended_order(footprint)]

    assert group_titles == [
        "FileGDB feature classes",
        "ArcGIS Server feature services",
        "AGOL web maps",
        "AGOL web apps, dashboards, and experiences",
        "Other or unknown item types",
    ]


def test_manual_review_reason_codes_cover_v01_flags() -> None:
    footprint = _footprint(
        inventory=[
            _portal_item("diag", "Feature Service", "Diagnostic Item"),
            _portal_item("complex", "Survey123 Form", "Survey"),
            _portal_item("unknown", "Other", "Unknown"),
            {
                "kind": "filegdb-feature-class",
                "name": "Missing SR",
                "geometryType": "esriGeometryPolygon",
                "sr": {},
            },
            {
                "kind": "filegdb-feature-class",
                "name": "Legacy SR",
                "geometryType": "esriGeometryPolygon",
                "sr": {"wkid": 26711},
            },
            {
                "kind": "server-service",
                "serviceUrl": "https://gis.example.com/arcgis/rest/services/Jobs/GPServer",
                "serviceType": "GPServer",
                "folder": "",
                "layerCount": 0,
            },
        ]
    )
    footprint["diagnostics"] = [
        {
            "code": "unresolved-reference",
            "severity": "warn",
            "message": "Diagnostic scoped to one item.",
            "scope": "diag",
        }
    ]

    reason_codes = {entry.reason_code for entry in manual_review_items(footprint)}

    assert reason_codes == {
        "flagged-by-diagnostic",
        "complex-item-type",
        "unknown-item-type",
        "missing-spatial-reference",
        "legacy-spatial-reference",
        "unsupported-service-type",
    }


def _portal_item(item_id: str, item_type: str, title: str) -> dict:
    return {
        "kind": "portal-item",
        "id": item_id,
        "type": item_type,
        "owner": "gis.admin",
        "title": title,
        "sharing": "org",
        "modified": "2026-05-22T14:02:11Z",
    }
