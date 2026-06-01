"""Service-type and geometry-type taxonomy."""

import pytest

from honua_esri_assess.server.catalog import (
    SERVICE_TYPE_TO_KIND,
    UNKNOWN_KIND,
    classify_geometry,
    classify_ogc_capabilities,
    classify_service,
    is_known_service_type,
)


@pytest.mark.parametrize(
    ("raw", "bucket"),
    [
        ("MapServer", "mapService"),
        ("FeatureServer", "featureService"),
        ("ImageServer", "imageService"),
        ("VectorTileServer", "vectorTileService"),
        ("GPServer", "geoprocessingService"),
        ("GeocodeServer", "geocodeService"),
        ("NAServer", "networkAnalysisService"),
        ("GeometryServer", "geometryService"),
        ("SceneServer", "sceneService"),
        ("StreamServer", "streamService"),
    ],
)
def test_known_service_types_map_to_buckets(raw: str, bucket: str) -> None:
    assert classify_service(raw) == bucket


def test_unknown_service_type_maps_to_other() -> None:
    assert classify_service("ZorpServer") == UNKNOWN_KIND


def test_every_table_entry_resolves_to_a_known_bucket() -> None:
    assert UNKNOWN_KIND not in SERVICE_TYPE_TO_KIND.values()


@pytest.mark.parametrize(
    ("raw", "bucket"),
    [
        ("esriGeometryPoint", "point"),
        ("esriGeometryPolyline", "polyline"),
        ("esriGeometryPolygon", "polygon"),
        ("esriGeometryMultipoint", "multipoint"),
    ],
)
def test_geometry_types_resolve(raw: str, bucket: str) -> None:
    assert classify_geometry(raw) == bucket


def test_geometry_type_unknown_returns_input_string() -> None:
    assert classify_geometry("esriGeometryMystery") == "esriGeometryMystery"


def test_geometry_type_none_passthrough() -> None:
    assert classify_geometry(None) is None


@pytest.mark.parametrize(
    "raw_type",
    ["MapServer", "FeatureServer", "ImageServer", "GeocodeServer", "SceneServer"],
)
def test_is_known_service_type_true_for_table_entries(raw_type: str) -> None:
    assert is_known_service_type(raw_type) is True


def test_is_known_service_type_false_for_unknown() -> None:
    assert is_known_service_type("ZorpServer") is False


@pytest.mark.parametrize(
    ("supported_extensions", "expected"),
    [
        ("WMSServer", ("WMS",)),
        ("WFSServer,WMSServer", ("WFS", "WMS")),
        ("WCSServer", ("WCS",)),
        ("WMSServer,WFSServer,WCSServer", ("WCS", "WFS", "WMS")),
        # SOEs and unknown extensions are ignored, not surfaced as flags.
        ("KmlServer,FeatureServer,LRServer", ()),
        # Whitespace tolerated; duplicates collapse deterministically.
        (" WMSServer , WMSServer ", ("WMS",)),
        ("", ()),
        (None, ()),
    ],
)
def test_classify_ogc_capabilities(
    supported_extensions: str | None,
    expected: tuple[str, ...],
) -> None:
    assert classify_ogc_capabilities(supported_extensions) == expected
