"""Catalog-walk behavior — shallow vs deep, partial failures, nested-folder guard."""

from __future__ import annotations

from pathlib import Path

import pytest
import responses

from honua_esri_assess.server.auth import AnonymousCredential, TokenCredential
from honua_esri_assess.server.client import ServerClient
from honua_esri_assess.server.scanner import ServerScanner

FIXTURES = Path(__file__).parent / "fixtures"


def _register_root(fixture: str = "services-root.json") -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        body=(FIXTURES / fixture).read_text(encoding="utf-8"),
        status=200,
        content_type="application/json",
    )


def _register_info() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/info",
        body=(FIXTURES / "rest-info.json").read_text(encoding="utf-8"),
        status=200,
        content_type="application/json",
    )


def _register_folder(name: str, fixture: str, *, status: int = 200) -> None:
    responses.add(
        responses.GET,
        f"https://gis.example.com/arcgis/rest/services/{name}",
        body=(FIXTURES / fixture).read_text(encoding="utf-8") if status == 200 else "",
        status=status,
        content_type="application/json",
    )


def _register_service(path: str, fixture: str, *, status: int = 200) -> None:
    responses.add(
        responses.GET,
        f"https://gis.example.com/arcgis/rest/services/{path}",
        body=(FIXTURES / fixture).read_text(encoding="utf-8") if status == 200 else "",
        status=status,
        content_type="application/json",
    )


@responses.activate
def test_shallow_walk_collects_folders_and_services() -> None:
    _register_info()
    _register_root()
    _register_folder("Hydrology", "folder-hydrology.json")
    _register_folder("Basemaps", "folder-basemaps.json")
    _register_folder("Imagery", "folder-imagery.json")
    _register_folder("Restricted", "folder-imagery.json", status=403)

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner().scan(client)

    assert result.info.current_version == "11.2"
    assert result.info.full_version == "11.2.0"
    assert {f.name for f in result.folders} == {"Hydrology", "Basemaps", "Imagery", "Restricted"}
    # root-level services + each folder's services
    by_folder = {(s.folder, s.name, s.service_type) for s in result.services}
    assert (None, "SampleWorldCities", "MapServer") in by_folder
    assert (None, "Geometry", "GeometryServer") in by_folder
    assert ("Hydrology", "Watersheds", "FeatureServer") in by_folder
    assert ("Basemaps", "Topo", "MapServer") in by_folder
    assert ("Imagery", "NAIP2024", "ImageServer") in by_folder
    # 403 folder did not abort
    assert any(d.code == "server.folder.forbidden" for d in result.diagnostics)
    # Unknown service type became 'other' with a diagnostic
    assert any(d.code == "server.service.unknown-type" for d in result.diagnostics)
    # Auth mode echoed in result
    assert result.auth_mode == "anonymous"
    # Shallow scan does not fetch service bodies
    assert all(not s.deep_scanned for s in result.services)


@responses.activate
def test_token_auth_propagates_to_every_request() -> None:
    _register_info()
    _register_root("services-root.json")
    _register_folder("Hydrology", "folder-hydrology.json")
    _register_folder("Basemaps", "folder-basemaps.json")
    _register_folder("Imagery", "folder-imagery.json")
    _register_folder("Restricted", "folder-imagery.json")

    client = ServerClient(
        "https://gis.example.com/arcgis",
        credential=TokenCredential("abc123"),
    )
    ServerScanner().scan(client)
    assert responses.calls
    for call in responses.calls:
        assert "token=abc123" in call.request.url


@responses.activate
def test_deep_walk_collects_layers_and_capabilities() -> None:
    _register_info()
    _register_root()
    _register_folder("Hydrology", "folder-hydrology.json")
    _register_folder("Basemaps", "folder-basemaps.json")
    _register_folder("Imagery", "folder-imagery.json")
    _register_folder("Restricted", "folder-imagery.json")
    # Root-level MapServer (SampleWorldCities) deep body
    _register_service("SampleWorldCities/MapServer", "mapserver-basemap.json")
    # Hydrology services
    _register_service("Hydrology/Watersheds/FeatureServer", "featureserver-watersheds.json")
    _register_service("Hydrology/Watersheds/MapServer", "mapserver-basemap.json")
    # ZorpServer is unknown, so the deep scanner skips it; no fixture needed
    # Basemaps services
    _register_service("Basemaps/Topo/MapServer", "mapserver-basemap.json")
    # VectorTileServer isn't in DEEP_PROBE_TYPES
    # Imagery services
    _register_service("Imagery/NAIP2024/ImageServer", "imageserver-naip.json")

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner(deep=True).scan(client)

    watersheds = next(
        s for s in result.services if s.folder == "Hydrology" and s.service_type == "FeatureServer"
    )
    assert watersheds.deep_scanned is True
    assert watersheds.capabilities == ("Query", "Sync", "Extract")
    assert len(watersheds.layers) == 2
    layer_geoms = {layer.geometry_type for layer in watersheds.layers}
    assert layer_geoms == {"polygon", "point"}
    assert len(watersheds.tables) == 1

    naip = next(s for s in result.services if s.name == "NAIP2024")
    assert naip.service_data_type == "esriImageServiceDataTypeRGB"

    topo = next(s for s in result.services if s.folder == "Basemaps" and s.name == "Topo")
    assert topo.single_fused_map_cache is True


@responses.activate
def test_deep_walk_partial_failure_keeps_other_services() -> None:
    _register_info()
    _register_root()
    _register_folder("Hydrology", "folder-hydrology.json")
    _register_folder("Basemaps", "folder-basemaps.json")
    _register_folder("Imagery", "folder-imagery.json")
    _register_folder("Restricted", "folder-imagery.json")
    _register_service("SampleWorldCities/MapServer", "mapserver-basemap.json")
    _register_service(
        "Hydrology/Watersheds/FeatureServer",
        "featureserver-watersheds.json",
        status=500,
    )
    _register_service("Hydrology/Watersheds/MapServer", "mapserver-basemap.json")
    _register_service("Basemaps/Topo/MapServer", "mapserver-basemap.json")
    _register_service("Imagery/NAIP2024/ImageServer", "imageserver-naip.json")

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner(deep=True).scan(client)

    failed = [d for d in result.diagnostics if d.code == "server.service.deep-failed"]
    assert failed, "expected per-service deep-failed diagnostic"
    # The service record still exists, just without deep data
    failed_service = next(
        s for s in result.services if s.folder == "Hydrology" and s.service_type == "FeatureServer"
    )
    assert failed_service.deep_scanned is False


@responses.activate
def test_folder_filter_restricts_walk_to_one_folder() -> None:
    _register_info()
    _register_root()
    _register_folder("Hydrology", "folder-hydrology.json")

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner(folder="Hydrology").scan(client)

    folder_names = {f.name for f in result.folders}
    assert folder_names == {"Hydrology"}
    # Only hydrology services (+ root-level) are walked
    assert all(
        s.folder is None or s.folder == "Hydrology"
        for s in result.services
    )


@responses.activate
def test_nested_folder_guard_emits_diagnostic() -> None:
    _register_info()
    # Root reports only one folder
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={
            "currentVersion": 11.2,
            "folders": ["Hydrology"],
            "services": [],
        },
        status=200,
    )
    _register_folder("Hydrology", "folder-nested.json")

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner().scan(client)
    nested = [d for d in result.diagnostics if d.code == "server.folder.nested"]
    assert nested, "expected nested-folder defense-in-depth diagnostic"


@responses.activate
def test_anonymous_partial_info_failure_does_not_abort() -> None:
    # /rest/info forbids anonymous access (some servers do this)
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/info",
        body="",
        status=403,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": [], "services": []},
        status=200,
    )

    client = ServerClient("https://gis.example.com/arcgis", credential=AnonymousCredential())
    result = ServerScanner().scan(client)
    assert result.info.current_version is None
    assert any(d.code == "server.info.partial" for d in result.diagnostics)
