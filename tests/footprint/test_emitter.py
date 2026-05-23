"""``EsriFootprint.json`` v0.1 emitter shape and safety guarantees."""

from __future__ import annotations

from datetime import UTC, datetime
import json

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
    fp = to_footprint_v0_1(
        _make_result(),
        tool_version="0.1.0-test",
        generated_at=datetime(2026, 1, 1, 12, 30, 0, tzinfo=UTC),
        captured_at=datetime(2026, 1, 1, 12, 29, 58, tzinfo=UTC),
        target_url="https://target-user:target-pass@gis.example.com/arcgis?token=target-token",
    )

    assert fp["schemaVersion"] == SCHEMA_VERSION == "v0.1"
    assert fp["tool"] == {"name": "honua-esri-assess", "version": "0.1.0-test"}
    assert fp["generatedAt"] == "2026-01-01T12:30:00Z"
    assert fp["source"] == {
        "kind": "arcgis-server",
        "locator": "https://gis.example.com/arcgis/rest/services",
        "capturedAt": "2026-01-01T12:29:58Z",
    }
    assert "producer" not in fp


def test_footprint_aggregates_service_counts_by_raw_type() -> None:
    fp = to_footprint_v0_1(_make_result(), tool_version="0.0.0")
    assert fp["server"] == {
        "folders": ["Hydrology", "Basemaps"],
        "serviceCounts": {"FeatureServer": 1, "MapServer": 1},
        "version": "11.2",
    }
    assert fp["counts"] == {
        "items": {
            "portal-item": 0,
            "server-service": 2,
            "filegdb-feature-class": 0,
        },
        "layers": 1,
        "featureClasses": 0,
    }


def test_footprint_inventory_includes_layer_count_when_deep() -> None:
    fp = to_footprint_v0_1(_make_result(deep=True), tool_version="0.0.0")
    deep_record = next(item for item in fp["inventory"] if "Watersheds" in item["serviceUrl"])
    assert deep_record == {
        "kind": "server-service",
        "serviceUrl": "https://gis.example.com/arcgis/rest/services/Hydrology/Watersheds/FeatureServer",
        "serviceType": "FeatureServer",
        "folder": "Hydrology",
        "layerCount": 1,
    }


def test_footprint_diagnostics_preserve_v01_vocabulary() -> None:
    fp = to_footprint_v0_1(_make_result(), tool_version="0.0.0")
    assert fp["diagnostics"] == [
        {
            "code": "unsupported-item-type",
            "severity": "info",
            "message": "unrecognized service type 'ZorpServer' mapped to 'other'",
            "scope": "services/Zorp",
        }
    ]


def test_terminal_service_diagnostics_omit_unreadable_inventory_record() -> None:
    result = ServerScanResult(
        info=ServerInfo(url="https://gis.example.com/arcgis/rest/services"),
        auth_mode="anonymous",
        deep=True,
        folders=(),
        services=(
            ServiceRecord(
                name="Throttled",
                folder=None,
                service_type="MapServer",
                kind="mapService",
                url="https://gis.example.com/arcgis/rest/services/Throttled/MapServer",
            ),
        ),
        diagnostics=(
            ScanDiagnostic(
                code="server.service.rate-limited",
                severity="warning",
                message="deep scan of 'Throttled' failed: Rate limit exceeded.",
                field="services/Throttled",
            ),
        ),
    )

    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    assert fp["inventory"] == []
    assert fp["counts"]["items"]["server-service"] == 0
    assert fp["server"]["serviceCounts"] == {"MapServer": 1}
    assert fp["diagnostics"][0]["code"] == "rate-limited"


def test_footprint_contains_no_credential_text() -> None:
    info = ServerInfo(url="https://fallback-user:fallback-pass@gis.example.com/arcgis/rest/services")
    service = ServiceRecord(
        name="Sensitive",
        folder=None,
        service_type="MapServer",
        kind="mapService",
        url="https://svc-user:svc-pass@gis.example.com/arcgis/rest/services/Sensitive/MapServer?token=abc",
    )
    result = ServerScanResult(
        info=info,
        auth_mode="token",
        deep=False,
        folders=(),
        services=(service,),
        diagnostics=(),
    )
    fp = to_footprint_v0_1(
        result,
        tool_version="0.0.0",
        target_url="https://target-user:target-pass@gis.example.com/arcgis?token=target-token",
    )

    payload = json.dumps(fp)
    for secret in (
        "target-token",
        "target-user",
        "target-pass",
        "fallback-user",
        "fallback-pass",
        "svc-user",
        "svc-pass",
        "token=abc",
    ):
        assert secret not in payload
    assert fp["source"]["locator"] == "https://gis.example.com/arcgis/rest/services"
    assert fp["inventory"][0]["serviceUrl"] == (
        "https://gis.example.com/arcgis/rest/services/Sensitive/MapServer"
    )


def test_emitted_footprint_is_pure_json() -> None:
    encoded = json.dumps(to_footprint_v0_1(_make_result(deep=True), tool_version="0.0.0"))
    decoded = json.loads(encoded)
    assert decoded["schemaVersion"] == SCHEMA_VERSION


def test_emitter_omits_optional_fields_when_absent() -> None:
    result = ServerScanResult(
        info=ServerInfo(url="https://gis.example.com/arcgis/rest/services"),
        auth_mode="anonymous",
        deep=False,
        folders=(),
        services=(
            ServiceRecord(
                name="Empty",
                folder=None,
                service_type="MapServer",
                kind="mapService",
                url="https://gis.example.com/arcgis/rest/services/Empty/MapServer",
            ),
        ),
        diagnostics=(),
    )
    record = to_footprint_v0_1(result, tool_version="0.0.0")["inventory"][0]
    assert record["folder"] == ""
    assert record["layerCount"] == 0
    assert "layers" not in record
    assert "tables" not in record
    assert "description" not in record
    assert "capabilities" not in record


@pytest.mark.parametrize(
    "auth_info",
    [{"isTokenBasedSecurity": True}, {"isTokenBasedSecurity": "false"}, {}],
)
def test_emitter_does_not_emit_auth_info_outside_v01_contract(auth_info: dict) -> None:
    result = ServerScanResult(
        info=ServerInfo(url="https://gis.example.com/arcgis/rest/services", auth_info=auth_info),
        auth_mode="anonymous",
        deep=False,
        folders=(),
        services=(),
        diagnostics=(),
    )
    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    assert "tokenBasedSecurity" not in fp["source"]
