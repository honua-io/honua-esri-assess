"""``EsriFootprint.json`` emitter shape and safety guarantees (v0.2)."""

from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from honua_esri_assess.footprint.v0_1 import SCHEMA_VERSION, to_footprint_v0_1
from honua_esri_assess.server.models import (
    FolderRecord,
    LayerRecord,
    LockInDetail,
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

    assert fp["schemaVersion"] == SCHEMA_VERSION == "v0.2"
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
        "serviceKind": "featureService",
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
                field="services/_root/Throttled/MapServer",
            ),
        ),
    )

    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    assert fp["inventory"] == []
    assert fp["counts"]["items"]["server-service"] == 0
    assert fp["server"]["serviceCounts"] == {"MapServer": 1}
    assert fp["diagnostics"][0]["code"] == "rate-limited"


def test_terminal_service_omission_does_not_collapse_same_named_siblings() -> None:
    """A terminal diagnostic against one Parcels service must not drop the sibling."""

    planning = ServiceRecord(
        name="Parcels",
        folder="Planning",
        service_type="MapServer",
        kind="mapService",
        url="https://gis.example.com/arcgis/rest/services/Planning/Parcels/MapServer",
    )
    utilities = ServiceRecord(
        name="Parcels",
        folder="Utilities",
        service_type="MapServer",
        kind="mapService",
        url="https://gis.example.com/arcgis/rest/services/Utilities/Parcels/MapServer",
    )
    result = ServerScanResult(
        info=ServerInfo(url="https://gis.example.com/arcgis/rest/services"),
        auth_mode="anonymous",
        deep=True,
        folders=(
            FolderRecord(name="Planning", service_count=1),
            FolderRecord(name="Utilities", service_count=1),
        ),
        services=(planning, utilities),
        diagnostics=(
            ScanDiagnostic(
                code="server.service.rate-limited",
                severity="warning",
                message="deep scan of 'Parcels' failed in Planning",
                field="services/Planning/Parcels/MapServer",
            ),
        ),
    )

    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    folders_in_inventory = {item["folder"] for item in fp["inventory"]}
    assert folders_in_inventory == {"Utilities"}
    assert fp["counts"]["items"]["server-service"] == 1
    assert fp["server"]["serviceCounts"] == {"MapServer": 2}


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


def test_footprint_classifies_non_feature_map_services_with_capabilities() -> None:
    """Each non-feature/map service emits its serviceKind and OGC flags."""

    info = ServerInfo(url="https://gis.example.com/arcgis/rest/services")
    services = (
        ServiceRecord(
            name="NAIP2024",
            folder="Imagery",
            service_type="ImageServer",
            kind="imageService",
            url="https://gis.example.com/arcgis/rest/services/Imagery/NAIP2024/ImageServer",
            ogc_capabilities=("WCS", "WMS"),
        ),
        ServiceRecord(
            name="Locator",
            folder=None,
            service_type="GeocodeServer",
            kind="geocodeService",
            url="https://gis.example.com/arcgis/rest/services/Locator/GeocodeServer",
        ),
        ServiceRecord(
            name="Knowledge",
            folder=None,
            service_type="KnowledgeGraphServer",
            kind="other",
            url="https://gis.example.com/arcgis/rest/services/Knowledge/KnowledgeGraphServer",
        ),
    )
    result = ServerScanResult(
        info=info,
        auth_mode="anonymous",
        deep=False,
        folders=(),
        services=services,
        diagnostics=(),
    )
    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    by_url = {item["serviceUrl"]: item for item in fp["inventory"]}

    image = by_url["https://gis.example.com/arcgis/rest/services/Imagery/NAIP2024/ImageServer"]
    assert image["serviceType"] == "ImageServer"
    assert image["serviceKind"] == "imageService"
    assert image["ogcCapabilities"] == ["WCS", "WMS"]

    geocode = by_url["https://gis.example.com/arcgis/rest/services/Locator/GeocodeServer"]
    assert geocode["serviceKind"] == "geocodeService"
    # No advertised OGC interfaces -> the optional array is omitted.
    assert "ogcCapabilities" not in geocode

    # Unknown service types are recorded explicitly as "other", never dropped.
    unknown = by_url[
        "https://gis.example.com/arcgis/rest/services/Knowledge/KnowledgeGraphServer"
    ]
    assert unknown["serviceType"] == "KnowledgeGraphServer"
    assert unknown["serviceKind"] == "other"


def test_footprint_with_service_breadth_validates_against_schema() -> None:
    """The additive serviceKind/ogcCapabilities fields validate under v0.2."""

    from honua_esri_assess.footprint.schema import validate_footprint

    result = ServerScanResult(
        info=ServerInfo(url="https://gis.example.com/arcgis/rest/services"),
        auth_mode="anonymous",
        deep=False,
        folders=(),
        services=(
            ServiceRecord(
                name="Parcels",
                folder="Planning",
                service_type="MapServer",
                kind="mapService",
                url="https://gis.example.com/arcgis/rest/services/Planning/Parcels/MapServer",
                ogc_capabilities=("WFS", "WMS"),
            ),
            ServiceRecord(
                name="Surface",
                folder=None,
                service_type="GPServer",
                kind="geoprocessingService",
                url="https://gis.example.com/arcgis/rest/services/Surface/GPServer",
            ),
        ),
        diagnostics=(),
    )
    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    assert validate_footprint(fp) is True


def _layer_detail_result() -> ServerScanResult:
    from honua_esri_assess.server.models import (
        EditorTracking,
        FieldDetail,
        LayerDetail,
        RelationshipDetail,
    )

    detail = LayerDetail(
        fields=(
            FieldDetail(name="OBJECTID", type="esriFieldTypeOID", nullable=False),
            FieldDetail(
                name="STATUS",
                type="esriFieldTypeString",
                domain_type="coded",
                domain_name="StatusDomain",
            ),
            FieldDetail(
                name="created_user",
                type="esriFieldTypeString",
                editor_tracking=True,
            ),
        ),
        relationships=(
            RelationshipDetail(
                id=3,
                name="WatershedToOutlets",
                related_table_id=1,
                cardinality="esriRelCardinalityOneToMany",
                role="esriRelRoleOrigin",
            ),
        ),
        subtype_count=2,
        has_attachments=True,
        editor_tracking=EditorTracking(enabled=True, creator_field="created_user"),
        renderer_type="uniqueValue",
        has_labels=True,
        has_popups=True,
        definition_query="STATUS = 'active'",
        spatial_reference={"wkid": 4326, "latestWkid": 4326},
    )
    table_detail = LayerDetail(
        fields=(FieldDetail(name="OBJECTID", type="esriFieldTypeOID"),),
    )
    return ServerScanResult(
        info=ServerInfo(url="https://gis.example.com/arcgis/rest/services"),
        auth_mode="anonymous",
        deep=True,
        folders=(),
        services=(
            ServiceRecord(
                name="Watersheds",
                folder="Hydrology",
                service_type="FeatureServer",
                kind="featureService",
                url=(
                    "https://gis.example.com/arcgis/rest/services/"
                    "Hydrology/Watersheds/FeatureServer"
                ),
                layers=(
                    LayerRecord(
                        id=0,
                        name="Watersheds",
                        type="Feature Layer",
                        geometry_type="polygon",
                        detail=detail,
                    ),
                    LayerRecord(id=1, name="Outlets", detail=None),
                ),
                tables=(
                    LayerRecord(id=2, name="WatershedAttributes", detail=table_detail),
                ),
                deep_scanned=True,
            ),
        ),
        diagnostics=(),
    )


def test_emitter_includes_layer_detail_block() -> None:
    fp = to_footprint_v0_1(_layer_detail_result(), tool_version="0.0.0")
    service = fp["inventory"][0]

    # Only layers/tables with resolved detail appear; the bare layer is omitted.
    layers = {layer["id"]: layer for layer in service["layers"]}
    assert set(layers) == {0, 2}

    layer0 = layers[0]
    assert layer0["hasAttachments"] is True
    assert layer0["subtypeCount"] == 2
    assert layer0["rendererType"] == "uniqueValue"
    assert layer0["hasLabels"] is True
    assert layer0["hasPopups"] is True
    assert layer0["definitionQuery"] == "STATUS = 'active'"
    assert layer0["sr"] == {"wkid": 4326, "latestWkid": 4326}
    assert layer0["editorTracking"] == {"enabled": True, "creatorField": "created_user"}

    status_field = next(f for f in layer0["fields"] if f["name"] == "STATUS")
    assert status_field["domainType"] == "coded"
    assert status_field["domainName"] == "StatusDomain"
    tracking_field = next(f for f in layer0["fields"] if f["name"] == "created_user")
    assert tracking_field["editorTracking"] is True

    rel = layer0["relationships"][0]
    assert rel["name"] == "WatershedToOutlets"
    assert rel["relatedTableId"] == 1


def test_emitter_omits_layers_when_no_detail() -> None:
    result = _make_result(deep=True)
    fp = to_footprint_v0_1(result, tool_version="0.0.0")
    # _make_result layers carry no detail, so the additive block is absent.
    assert all("layers" not in item for item in fp["inventory"])


def test_layer_detail_footprint_validates_against_schema() -> None:
    from honua_esri_assess.footprint.schema import validate_footprint

    fp = to_footprint_v0_1(_layer_detail_result(), tool_version="0.0.0")
    assert validate_footprint(fp) is True


def _lock_in_result() -> ServerScanResult:
    info = ServerInfo(url="https://gis.example.com/arcgis/rest/services")
    services = (
        ServiceRecord(
            name="ElectricUN",
            folder="Electric",
            service_type="FeatureServer",
            kind="featureService",
            url="https://gis.example.com/arcgis/rest/services/Electric/ElectricUN/FeatureServer",
            capabilities=("Query", "UtilityNetwork"),
            layers=(LayerRecord(id=0, name="ElectricDevice"),),
            lock_ins=(
                LockInDetail(
                    kind="utility-network",
                    feature_class_count=9,
                    domain_network_count=2,
                    rule_count=14,
                ),
            ),
            deep_scanned=True,
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
        auth_mode="anonymous",
        deep=True,
        folders=(),
        services=services,
        diagnostics=(),
    )


def test_footprint_emits_additive_lock_in_block_with_extent() -> None:
    fp = to_footprint_v0_1(_lock_in_result(), tool_version="0.0.0")
    un = next(item for item in fp["inventory"] if "ElectricUN" in item["serviceUrl"])
    assert un["lockIns"] == [
        {
            "type": "utility-network",
            "featureClassCount": 9,
            "domainNetworkCount": 2,
            "ruleCount": 14,
        }
    ]
    # Plain services carry no lockIns key so v0.1 readers are unchanged.
    topo = next(item for item in fp["inventory"] if "Topo" in item["serviceUrl"])
    assert "lockIns" not in topo


def test_lock_in_footprint_validates_against_v02_schema() -> None:
    from honua_esri_assess.footprint.schema import validate_footprint

    fp = to_footprint_v0_1(_lock_in_result(), tool_version="0.0.0")
    assert validate_footprint(fp) is True
