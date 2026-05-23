"""``EsriFootprint.json`` v0.1 emitter — shape and producer guarantees."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from honua_esri_assess.footprint.v0_1 import SCHEMA_VERSION, to_footprint_v0_1
from honua_esri_assess.server.models import (
    FolderRecord,
    LayerRecord,
    ScanDiagnostic,
    ServerInfo,
    ServerScanResult,
    ServiceRecord,
)


def _make_result(*, deep: bool = False) -> ServerScanResult:
    info = ServerInfo(
        url="https://gis.example.com/arcgis/rest/services",
        current_version="11.2",
        full_version="11.2.0",
        auth_info={"isTokenBasedSecurity": True},
        software_authorization={"edition": "Standard"},
    )
    services = (
        ServiceRecord(
            name="Watersheds",
            folder="Hydrology",
            service_type="FeatureServer",
            kind="featureService",
            url="https://gis.example.com/arcgis/rest/services/Hydrology/Watersheds/FeatureServer",
            description="Watershed feature service",
            capabilities=("Query", "Sync"),
            layers=(
                LayerRecord(id=0, name="Watersheds", type="Feature Layer", geometry_type="polygon"),
            ),
            deep_scanned=deep,
        ),
        ServiceRecord(
            name="Topo",
            folder="Basemaps",
            service_type="MapServer",
            kind="mapService",
            url="https://gis.example.com/arcgis/rest/services/Basemaps/Topo/MapServer",
        ),
    )
    return ServerScanResult(
        info=info,
        auth_mode="token",
        deep=deep,
        folders=(
            FolderRecord(name="Hydrology", service_count=1),
            FolderRecord(name="Basemaps", service_count=1),
        ),
        services=services,
        diagnostics=(
            ScanDiagnostic(
                code="server.service.unknown-type",
                severity="info",
                message="unrecognized service type 'ZorpServer' mapped to 'other'",
                field="services/Zorp",
            ),
        ),
    )


def test_footprint_has_required_header_fields() -> None:
    result = _make_result()
    fp = to_footprint_v0_1(
        result,
        tool_version="0.1.0-test",
        generated_at=datetime(2026, 1, 1, 12, 30, 0, tzinfo=UTC),
        target_url="https://gis.example.com/arcgis",
    )
    assert fp["schemaVersion"] == SCHEMA_VERSION
    assert fp["tool"] == {"name": "honua-esri-assess", "version": "0.0.0"}
    assert fp["generatedAt"] == "2026-01-01T12:30:00Z"
    assert fp["source"]["kind"] == "arcgis-server"
    assert fp["source"]["locator"] == "https://gis.example.com/arcgis"
    assert "producer" not in fp


def test_footprint_aggregates_service_counts_by_bucket() -> None:
    fp = to_footprint_v0_1(_make_result(), tool_version="0.0.0")
    assert fp["server"]["serviceCounts"] == {"FeatureServer": 1, "MapServer": 1}
    assert fp["counts"]["items"]["server-service"] == 2


def test_footprint_inventory_includes_layers_when_deep() -> None:
    fp = to_footprint_v0_1(_make_result(deep=True), tool_version="0.0.0")
    inventory = fp["inventory"]
    deep_record = next(item for item in inventory if "Watersheds" in item["serviceUrl"])
    assert deep_record["kind"] == "server-service"
    assert deep_record["layerCount"] == 1


def test_footprint_diagnostics_preserve_codes_and_severities() -> None:
    fp = to_footprint_v0_1(_make_result(), tool_version="0.0.0")
    diags = fp["diagnostics"]
    assert diags == [
        {
            "code": "unsupported-item-type",
            "severity": "info",
            "message": "unrecognized service type 'ZorpServer' mapped to 'other'",
            "scope": "services/Zorp",
        }
    ]


def test_footprint_contains_no_credential_text() -> None:
    info = ServerInfo(url="https://gis.example.com/arcgis/rest/services?token=abc")
    result = ServerScanResult(
        info=info,
        auth_mode="token",
        deep=False,
        folders=(),
        services=(),
        diagnostics=(),
    )
    fp = to_footprint_v0_1(result, tool_version="0.0.0", target_url="https://gis.example.com/arcgis")
    import json

    payload = json.dumps(fp)
    assert "token=abc" not in payload


def test_emitted_footprint_is_pure_json() -> None:
    import json

    fp = to_footprint_v0_1(_make_result(deep=True), tool_version="0.0.0")
    # Round-trips without error using stdlib json (no custom encoders required).
    encoded = json.dumps(fp, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["schemaVersion"] == SCHEMA_VERSION


def test_emitter_omits_optional_fields_when_absent() -> None:
    info = ServerInfo(url="https://gis.example.com/arcgis/rest/services")
    sparse = ServiceRecord(
        name="Empty",
        folder=None,
        service_type="MapServer",
        kind="mapService",
        url="https://gis.example.com/arcgis/rest/services/Empty/MapServer",
    )
    result = ServerScanResult(
        info=info,
        auth_mode="anonymous",
        deep=False,
        folders=(),
        services=(sparse,),
        diagnostics=(),
    )
    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    record = fp["inventory"][0]
    assert "layers" not in record
    assert "tables" not in record
    assert "description" not in record
    assert "capabilities" not in record
    assert record["layerCount"] == 0


@pytest.mark.parametrize(
    "auth_info, expected",
    [({"isTokenBasedSecurity": True}, True), ({"isTokenBasedSecurity": "false"}, False), ({}, None)],
)
def test_emitter_coerces_auth_info_bool(auth_info: dict, expected: bool | None) -> None:
    info = ServerInfo(url="https://gis.example.com/arcgis/rest/services", auth_info=auth_info)
    result = ServerScanResult(
        info=info,
        auth_mode="anonymous",
        deep=False,
        folders=(),
        services=(),
        diagnostics=(),
    )
    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    assert "tokenBasedSecurity" not in fp["source"]
