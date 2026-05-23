"""Service-type and geometry-type taxonomy."""

import pytest

from honua_esri_assess.server.catalog import (
    SERVICE_TYPE_TO_KIND,
    UNKNOWN_KIND,
    classify_geometry,
    classify_service,
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
