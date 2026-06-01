"""v0.2 dependency-edge emission, validation, and ordering consumption."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from honua_esri_assess.footprint.v0_1 import (
    RELATION_SERVICE_LAYER,
    RELATION_WEBMAP_SERVICE,
    to_footprint_v0_1,
)
from honua_esri_assess.portal.models import ItemRecord, OrgInfo, PortalScanResult
from honua_esri_assess.report.heuristics import dependency_edges, dependency_order
from honua_esri_assess.server.models import (
    LayerRecord,
    ServerInfo,
    ServerScanResult,
    ServiceRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
V02_SCHEMA = REPO_ROOT / "schemas" / "esri-footprint-v0.2.json"


def _v02_validator() -> Draft202012Validator:
    schema = json.loads(V02_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _item(item_id: str, item_type: str, *, dependencies: list[str] | None = None) -> ItemRecord:
    return ItemRecord(
        id=item_id,
        title=item_id,
        owner="owner",
        item_type=item_type,
        type_bucket="other",
        access="org",
        modified="2026-01-01T00:00:00Z",
        dependencies=dependencies or [],
    )


def _portal_result(items: list[ItemRecord]) -> PortalScanResult:
    return PortalScanResult(
        org=OrgInfo(
            id="org123",
            name="Fixture",
            portal_url="https://fixture.maps.arcgis.com",
            sharing_rest_url="https://fixture.maps.arcgis.com/sharing/rest",
        ),
        auth_mode="anonymous",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        items=items,
    )


def test_webmap_service_edges_emitted_and_validate() -> None:
    items = [
        _item("map1", "Web Map", dependencies=["svc1", "svc2", "unscanned"]),
        _item("svc1", "Feature Service"),
        _item("svc2", "Map Service"),
    ]
    fp = to_footprint_v0_1(_portal_result(items), tool_version="0.0.0")

    assert fp["schemaVersion"] == "v0.2"
    # Edge to "unscanned" is dropped because the target is not in the inventory.
    assert fp["dependencyEdges"] == [
        {"from": "map1", "to": "svc1", "relation": RELATION_WEBMAP_SERVICE},
        {"from": "map1", "to": "svc2", "relation": RELATION_WEBMAP_SERVICE},
    ]
    assert not list(_v02_validator().iter_errors(fp))


def test_portal_footprint_without_webmap_deps_omits_edges() -> None:
    fp = to_footprint_v0_1(
        _portal_result([_item("svc1", "Feature Service")]),
        tool_version="0.0.0",
    )
    assert "dependencyEdges" not in fp
    assert not list(_v02_validator().iter_errors(fp))


def test_service_layer_edges_emitted_and_validate() -> None:
    service = ServiceRecord(
        name="Watersheds",
        folder="Hydro",
        service_type="FeatureServer",
        kind="featureService",
        url="https://gis.example.com/arcgis/rest/services/Hydro/Watersheds/FeatureServer",
        layers=(
            LayerRecord(id=0, name="Basins"),
            LayerRecord(id=1, name="Streams"),
        ),
    )
    result = ServerScanResult(
        info=ServerInfo(url="https://gis.example.com/arcgis/rest/services"),
        auth_mode="anonymous",
        deep=True,
        folders=(),
        services=(service,),
        diagnostics=(),
    )
    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    base = "https://gis.example.com/arcgis/rest/services/Hydro/Watersheds/FeatureServer"

    assert fp["schemaVersion"] == "v0.2"
    assert fp["dependencyEdges"] == [
        {"from": base, "to": f"{base}#0", "relation": RELATION_SERVICE_LAYER},
        {"from": base, "to": f"{base}#1", "relation": RELATION_SERVICE_LAYER},
    ]
    assert not list(_v02_validator().iter_errors(fp))


def test_omitted_service_contributes_no_layer_edges() -> None:
    service = ServiceRecord(
        name="Throttled",
        folder=None,
        service_type="MapServer",
        kind="mapService",
        url="https://gis.example.com/arcgis/rest/services/Throttled/MapServer",
        layers=(LayerRecord(id=0, name="Layer"),),
    )
    from honua_esri_assess.server.models import ScanDiagnostic

    result = ServerScanResult(
        info=ServerInfo(url="https://gis.example.com/arcgis/rest/services"),
        auth_mode="anonymous",
        deep=True,
        folders=(),
        services=(service,),
        diagnostics=(
            ScanDiagnostic(
                code="server.service.rate-limited",
                severity="warning",
                message="rate limited",
                field="services/_root/Throttled/MapServer",
            ),
        ),
    )
    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    assert fp["inventory"] == []
    assert "dependencyEdges" not in fp


def test_dependency_order_places_dependencies_first() -> None:
    fp = {
        "dependencyEdges": [
            {"from": "map1", "to": "svc1", "relation": RELATION_WEBMAP_SERVICE},
            {"from": "svc1", "to": "svc1#0", "relation": RELATION_SERVICE_LAYER},
        ]
    }
    order = dependency_order(fp)
    assert order == ("svc1#0", "svc1", "map1")
    assert order.index("svc1#0") < order.index("svc1") < order.index("map1")


def test_dependency_edges_ignored_on_v01_artifact() -> None:
    assert dependency_edges({"schemaVersion": "v0.1"}) == ()
    assert dependency_order({"schemaVersion": "v0.1"}) == ()


def test_dependency_order_covers_cycles_without_dropping_nodes() -> None:
    fp = {
        "dependencyEdges": [
            {"from": "a", "to": "b", "relation": RELATION_WEBMAP_SERVICE},
            {"from": "b", "to": "a", "relation": RELATION_WEBMAP_SERVICE},
        ]
    }
    assert set(dependency_order(fp)) == {"a", "b"}


@pytest.mark.parametrize(
    "schema_version",
    ["v0.1", "v0.2"],
)
def test_v02_schema_accepts_both_in_band_versions(schema_version: str) -> None:
    sample = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "esri-footprint-sample.json").read_text(
            encoding="utf-8"
        )
    )
    sample["schemaVersion"] = schema_version
    assert not list(_v02_validator().iter_errors(sample))
