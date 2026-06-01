"""Catalog-walk behavior — shallow vs deep, partial failures, nested-folder guard."""

from __future__ import annotations

from pathlib import Path

import pytest
import responses

from honua_esri_assess.server.auth import AnonymousCredential, TokenCredential
from honua_esri_assess.server.client import RetryPolicy, ServerClient
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


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (403, "server.service.missing-permission"),
        (429, "server.service.rate-limited"),
    ],
)
@responses.activate
def test_deep_walk_classifies_terminal_service_failures(
    status: int,
    expected_code: str,
) -> None:
    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": ["Hydrology"], "services": []},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Hydrology",
        json={
            "folders": [],
            "services": [{"name": "Hydrology/Watersheds", "type": "FeatureServer"}],
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Hydrology/Watersheds/FeatureServer",
        body="",
        status=status,
    )

    client = ServerClient(
        "https://gis.example.com/arcgis",
        retry=RetryPolicy(max_attempts=1),
    )
    result = ServerScanner(deep=True).scan(client)

    assert len(result.services) == 1
    assert result.services[0].deep_scanned is False
    assert any(d.code == expected_code for d in result.diagnostics)


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


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (429, "server.folder.rate-limited"),
    ],
)
@responses.activate
def test_folder_rate_limit_does_not_abort_sibling_folders(
    status: int,
    expected_code: str,
) -> None:
    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": ["A", "B"], "services": []},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/A",
        body="",
        status=status,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/B",
        json={"folders": [], "services": [{"name": "B/Topo", "type": "MapServer"}]},
        status=200,
    )

    client = ServerClient(
        "https://gis.example.com/arcgis",
        retry=RetryPolicy(max_attempts=1),
    )
    result = ServerScanner().scan(client)

    # Folder B's services are still inventoried, despite folder A being throttled.
    by_folder = {(s.folder, s.name) for s in result.services}
    assert ("B", "Topo") in by_folder
    assert {f.name for f in result.folders} == {"A", "B"}
    diag_codes = {d.code for d in result.diagnostics}
    assert expected_code in diag_codes


@responses.activate
def test_folder_connection_error_emits_partial_coverage_diagnostic() -> None:
    import requests

    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": ["A", "B"], "services": []},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/A",
        body=requests.exceptions.ConnectionError("simulated network drop"),
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/B",
        json={"folders": [], "services": [{"name": "B/Topo", "type": "MapServer"}]},
        status=200,
    )

    client = ServerClient(
        "https://gis.example.com/arcgis",
        retry=RetryPolicy(max_attempts=1),
    )
    result = ServerScanner().scan(client)

    by_folder = {(s.folder, s.name) for s in result.services}
    assert ("B", "Topo") in by_folder
    assert any(d.code == "server.folder.connection" for d in result.diagnostics)


@responses.activate
def test_info_rate_limit_does_not_abort_scan() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/info",
        body="",
        status=429,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": [], "services": []},
        status=200,
    )

    client = ServerClient(
        "https://gis.example.com/arcgis",
        retry=RetryPolicy(max_attempts=1),
    )
    result = ServerScanner().scan(client)
    assert result.info.current_version is None
    assert any(d.code == "server.info.partial" for d in result.diagnostics)


@responses.activate
def test_deep_failure_diagnostic_uses_full_service_identity() -> None:
    """A 403 against Planning/Parcels must not also omit Utilities/Parcels."""

    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": ["Planning", "Utilities"], "services": []},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Planning",
        json={
            "folders": [],
            "services": [{"name": "Planning/Parcels", "type": "MapServer"}],
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Utilities",
        json={
            "folders": [],
            "services": [{"name": "Utilities/Parcels", "type": "MapServer"}],
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Planning/Parcels/MapServer",
        body="",
        status=403,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Utilities/Parcels/MapServer",
        json={"layers": [{"id": 0, "name": "Parcels"}]},
        status=200,
    )

    client = ServerClient(
        "https://gis.example.com/arcgis",
        retry=RetryPolicy(max_attempts=1),
    )
    result = ServerScanner(deep=True).scan(client)

    planning_diag = next(
        d
        for d in result.diagnostics
        if d.code == "server.service.missing-permission"
    )
    # Folder, name, and type are all encoded in the identity field so the emitter
    # can filter only the affected service, not its same-named sibling.
    assert planning_diag.field == "services/Planning/Parcels/MapServer"


@responses.activate
def test_layer_detail_walk_attaches_schema_detail() -> None:
    _register_info()
    _register_root()
    _register_folder("Hydrology", "folder-hydrology.json")
    _register_folder("Basemaps", "folder-basemaps.json")
    _register_folder("Imagery", "folder-imagery.json")
    _register_folder("Restricted", "folder-imagery.json")
    _register_service("SampleWorldCities/MapServer", "mapserver-basemap.json")
    _register_service("Hydrology/Watersheds/FeatureServer", "featureserver-watersheds.json")
    _register_service("Hydrology/Watersheds/MapServer", "mapserver-basemap.json")
    _register_service("Basemaps/Topo/MapServer", "mapserver-basemap.json")
    _register_service("Imagery/NAIP2024/ImageServer", "imageserver-naip.json")
    # Per-layer detail resources for the watershed FeatureServer.
    _register_service(
        "Hydrology/Watersheds/FeatureServer/0",
        "featureserver-watersheds-layer-0.json",
    )
    _register_service(
        "Hydrology/Watersheds/FeatureServer/1",
        "featureserver-watersheds-layer-1.json",
    )
    _register_service(
        "Hydrology/Watersheds/FeatureServer/2",
        "featureserver-watersheds-table-2.json",
    )
    # The basemap MapServer fixture reports two layers (ids 0 and 1); register a
    # detail body for each so the layer-detail walk resolves them cleanly. The
    # same MapServer fixture backs SampleWorldCities, Topo, and Watersheds.
    for service_path in (
        "SampleWorldCities/MapServer",
        "Hydrology/Watersheds/MapServer",
        "Basemaps/Topo/MapServer",
    ):
        _register_service(f"{service_path}/0", "featureserver-watersheds-layer-1.json")
        _register_service(f"{service_path}/1", "featureserver-watersheds-layer-1.json")

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner(deep=True, layer_detail=True).scan(client)

    watersheds = next(
        s for s in result.services if s.folder == "Hydrology" and s.service_type == "FeatureServer"
    )
    layer0 = next(layer for layer in watersheds.layers if layer.id == 0)
    assert layer0.detail is not None
    assert layer0.detail.has_attachments is True
    assert layer0.detail.subtype_count == 2
    assert layer0.detail.editor_tracking is not None
    assert {f.name for f in layer0.detail.fields} >= {"OBJECTID", "STATUS", "AREA"}
    assert any(f.domain_type == "coded" for f in layer0.detail.fields)
    assert len(layer0.detail.relationships) == 1

    table = next(t for t in watersheds.tables if t.id == 2)
    assert table.detail is not None
    assert {f.name for f in table.detail.fields} == {"OBJECTID", "WATERSHED_ID"}


@responses.activate
def test_layer_detail_partial_failure_keeps_layer_and_diagnoses() -> None:
    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": ["Hydrology"], "services": []},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Hydrology",
        json={
            "folders": [],
            "services": [{"name": "Hydrology/Watersheds", "type": "FeatureServer"}],
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Hydrology/Watersheds/FeatureServer",
        json={"layers": [{"id": 0, "name": "Watersheds"}], "tables": []},
        status=200,
    )
    # Layer-detail probe is forbidden but must not abort the scan.
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Hydrology/Watersheds/FeatureServer/0",
        body="",
        status=403,
    )

    client = ServerClient(
        "https://gis.example.com/arcgis",
        retry=RetryPolicy(max_attempts=1),
    )
    result = ServerScanner(deep=True, layer_detail=True).scan(client)

    watersheds = result.services[0]
    assert watersheds.deep_scanned is True
    # The layer summary survives even though its detail probe failed.
    assert len(watersheds.layers) == 1
    assert watersheds.layers[0].detail is None
    assert any(
        d.code == "server.service.missing-permission"
        and d.field == "services/Hydrology/Watersheds/FeatureServer/0"
        for d in result.diagnostics
    )


@responses.activate
def test_layer_detail_requires_deep() -> None:
    """layer_detail without deep is a no-op (no per-layer routes fetched)."""

    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": [], "services": [{"name": "Topo", "type": "FeatureServer"}]},
        status=200,
    )

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner(deep=False, layer_detail=True).scan(client)
    # No deep probe, so no service body and no layer-detail fetch occurred.
    assert all(not s.deep_scanned for s in result.services)


@responses.activate
def test_shallow_walk_classifies_service_breadth_and_ogc() -> None:
    """Shallow catalog walk classifies every service type and reads OGC flags.

    Capability classification keys off the catalog ``type`` and the per-entry
    ``supportedExtensions`` field, so no deep probe is needed to record the
    coarse kind or the advertised OGC interfaces.
    """

    _register_info()
    _register_root("services-root-breadth.json")

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner().scan(client)

    by_name = {s.name: s for s in result.services}
    # Non-feature/map types are each classified into their migration bucket.
    assert by_name["NAIP2024"].kind == "imageService"
    assert by_name["Locator"].kind == "geocodeService"
    assert by_name["ElevationProfile"].kind == "geoprocessingService"
    assert by_name["CityScene"].kind == "sceneService"
    assert by_name["Basemap"].kind == "vectorTileService"
    assert by_name["VehiclePings"].kind == "streamService"
    assert by_name["Routing"].kind == "networkAnalysisService"

    # Unknown/unsupported types are recorded explicitly, never dropped.
    assert by_name["Knowledge"].kind == "other"
    assert any(d.code == "server.service.unknown-type" for d in result.diagnostics)

    # OGC interfaces advertised on the catalog entry are captured shallow.
    assert by_name["Parcels"].ogc_capabilities == ("WFS", "WMS")
    assert by_name["NAIP2024"].ogc_capabilities == ("WCS", "WMS")
    # Services without OGC extensions carry an empty tuple.
    assert by_name["Locator"].ogc_capabilities == ()


@responses.activate
def test_deep_walk_captures_gpserver_task_names() -> None:
    """A deep GPServer probe records its ``tasks`` array as migration handoff seed.

    Task names are de-duplicated and sorted for determinism; only the names
    already present on the service body are read (no task is crawled).
    """

    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={
            "folders": [],
            "services": [{"name": "ElevationProfile", "type": "GPServer"}],
        },
        status=200,
    )
    _register_service("ElevationProfile/GPServer", "gpserver-elevation.json")

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner(deep=True).scan(client)

    gp = {s.name: s for s in result.services}["ElevationProfile"]
    assert gp.kind == "geoprocessingService"
    assert gp.deep_scanned is True
    # Duplicates collapsed, sorted; no task resource was fetched beyond the body.
    assert gp.gp_tasks == ("ExtractProfile", "Viewshed")


@responses.activate
def test_shallow_gpserver_has_no_tasks() -> None:
    """Without a deep probe, GP task names stay empty (no extra fetch)."""

    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={
            "folders": [],
            "services": [{"name": "ElevationProfile", "type": "GPServer"}],
        },
        status=200,
    )

    client = ServerClient("https://gis.example.com/arcgis")
    result = ServerScanner().scan(client)

    gp = {s.name: s for s in result.services}["ElevationProfile"]
    assert gp.kind == "geoprocessingService"
    assert gp.gp_tasks == ()
