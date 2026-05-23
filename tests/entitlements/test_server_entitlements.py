"""Fixture-driven tests for the ArcGIS Server collector."""

from __future__ import annotations

import pytest

from honua_esri_assess.entitlements.diagnostics import (
    EntitlementsConnectionError,
    EntitlementsRateLimitedError,
)
from honua_esri_assess.entitlements.server import (
    ServerEntitlementsCollector,
    ServiceRef,
)

from .conftest import StubHttpClient, load_fixture, respond


def _server_handlers_admin() -> dict[str, object]:
    return {
        "rest/info": respond(200, load_fixture("server_rest_info.json")),
        "admin/info": respond(200, load_fixture("server_admin_info.json")),
        "admin/system/licenses": respond(200, load_fixture("server_admin_licenses.json")),
        "admin/services/Hosted": respond(
            200, load_fixture("server_admin_services_hosted.json")
        ),
        "admin/services": respond(200, load_fixture("server_admin_services_root.json")),
        "admin/services/World.MapServer": respond(
            200, load_fixture("server_service_extensions.json")
        ),
        "admin/services/Hosted/Parcels.MapServer": respond(
            200, load_fixture("server_service_extensions.json")
        ),
    }


def test_server_admin_path_returns_full_extension_list() -> None:
    client = StubHttpClient(handlers=_server_handlers_admin())
    collector = ServerEntitlementsCollector("https://example.com/arcgis", client)

    result = collector.collect(
        [ServiceRef(folder="Hosted", name="Parcels", type="MapServer")]
    )

    licensing = result.licensing
    assert licensing.product_name == "ArcGIS Server"
    assert licensing.current_version == "11.3"
    assert licensing.edition == "Advanced"

    codes = {ext.code for ext in licensing.extensions}
    assert {"Spatial", "Network", "ImageServer", "DataReviewer"} <= codes
    assert "ContosoCustomExt" in codes
    statuses = {ext.code: ext.status for ext in licensing.extensions}
    assert statuses["Spatial"] == "licensed"
    assert statuses["ImageServer"] == "evaluation"
    assert statuses["DataReviewer"] == "expired"

    # Service extensions include only enabled SOEs and SOIs.
    assert len(licensing.service_extensions) == 1
    rec = licensing.service_extensions[0]
    assert rec.soes == ["FeatureServer", "WMSServer"]
    assert rec.sois == ["AuthSOI"]
    assert "token" not in rec.service_url.lower()


def test_server_non_admin_falls_back_to_rest_info_and_emits_diagnostic() -> None:
    handlers = {
        "rest/info": respond(200, load_fixture("server_rest_info.json")),
        "admin/info": respond(401, {"error": {"code": 401, "message": "Token required."}}),
        "admin/system/licenses": respond(
            401, {"error": {"code": 401, "message": "Token required."}}
        ),
        "admin/services": respond(
            401, {"error": {"code": 401, "message": "Token required."}}
        ),
    }
    client = StubHttpClient(handlers=handlers)
    collector = ServerEntitlementsCollector("https://example.com/arcgis", client)

    result = collector.collect()

    assert result.licensing.product_name == "ArcGIS Server"
    assert result.licensing.current_version == "11.3"
    assert result.licensing.edition is None
    assert result.licensing.extensions == []
    permission_scopes = {
        d.scope for d in result.diagnostics if d.code == "missing-permission"
    }
    assert "server.admin/info" in permission_scopes
    assert "server.admin/system/licenses" in permission_scopes
    assert "server.admin/services" in permission_scopes


def test_server_unknown_extension_emits_partial_coverage_diagnostic() -> None:
    client = StubHttpClient(handlers=_server_handlers_admin())
    collector = ServerEntitlementsCollector("https://example.com/arcgis", client)

    result = collector.collect()

    custom = [
        d
        for d in result.diagnostics
        if d.code == "partial-coverage"
        and d.scope == "server.admin/system/licenses.extensions.ContosoCustomExt"
    ]
    assert custom, "unknown extension should produce partial-coverage diagnostic"


def test_server_discovers_services_when_no_service_refs_provided() -> None:
    client = StubHttpClient(handlers=_server_handlers_admin())
    collector = ServerEntitlementsCollector("https://example.com/arcgis", client)

    result = collector.collect()

    assert len(result.licensing.service_extensions) == 2
    service_urls = {record.service_url for record in result.licensing.service_extensions}
    assert "https://example.com/arcgis/rest/services/World/MapServer" in service_urls
    assert (
        "https://example.com/arcgis/rest/services/Hosted/Parcels/MapServer"
        in service_urls
    )
    assert any(url.endswith("admin/services") for url in client.seen)
    assert any(url.endswith("admin/services/Hosted") for url in client.seen)


def test_server_skip_service_extensions_when_disabled() -> None:
    client = StubHttpClient(handlers=_server_handlers_admin())
    collector = ServerEntitlementsCollector(
        "https://example.com/arcgis", client, include_service_extensions=False
    )

    result = collector.collect(
        [ServiceRef(folder="Hosted", name="Parcels", type="MapServer")]
    )

    assert result.licensing.service_extensions == []
    assert not any("admin/services" in url for url in client.seen)


def test_server_root_folder_service_uses_no_folder_segment() -> None:
    handlers = _server_handlers_admin()
    handlers["admin/services/World.MapServer"] = respond(
        200, load_fixture("server_service_extensions.json")
    )
    client = StubHttpClient(handlers=handlers)
    collector = ServerEntitlementsCollector("https://example.com/arcgis", client)

    result = collector.collect([ServiceRef(folder="", name="World", type="MapServer")])

    assert len(result.licensing.service_extensions) == 1
    assert any("admin/services/World.MapServer" in url for url in client.seen)


def test_server_connection_failure_raises_typed_error() -> None:
    client = StubHttpClient(
        handlers={},
        raise_on={"rest/info": ConnectionError("DNS lookup failed")},
    )
    collector = ServerEntitlementsCollector("https://example.com/arcgis", client)

    with pytest.raises(EntitlementsConnectionError):
        collector.collect()


def test_server_rate_limit_raises_typed_error() -> None:
    handlers = {
        "rest/info": respond(429, {"error": {"code": 429, "message": "Too many requests"}}),
    }
    client = StubHttpClient(handlers=handlers)
    collector = ServerEntitlementsCollector("https://example.com/arcgis", client)

    with pytest.raises(EntitlementsRateLimitedError):
        collector.collect()
