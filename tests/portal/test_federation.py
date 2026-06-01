"""Tests for Portal federation topology + advanced server role discovery (#54)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import responses

from honua_esri_assess.footprint.schema import validate_footprint
from honua_esri_assess.footprint.v0_1 import to_footprint_v0_1
from honua_esri_assess.portal import PortalClient, TokenCredential
from honua_esri_assess.portal.models import (
    FederatedServer,
    FederationInfo,
    OrgInfo,
    PortalScanResult,
)
from honua_esri_assess.portal.scanner import PortalScanner

BASE = "https://demo.maps.arcgis.com/sharing/rest"


def _register_self(fixture_json: Callable[[str], dict[str, Any]]) -> None:
    responses.add(responses.GET, f"{BASE}/portals/self", json=fixture_json("portal_self.json"), status=200)
    responses.add(responses.GET, f"{BASE}/community/groups", json=fixture_json("groups_page_1.json"), status=200)
    responses.add(responses.GET, f"{BASE}/community/users", json=fixture_json("users_count.json"), status=200)
    responses.add(responses.GET, f"{BASE}/search", json=fixture_json("search_page_1.json"), status=200)
    responses.add(responses.GET, f"{BASE}/search", json=fixture_json("search_page_2.json"), status=200)


@responses.activate
def test_scanner_parses_federation_topology_and_advanced_roles(
    fixture_json: Callable[[str], dict[str, Any]],
) -> None:
    _register_self(fixture_json)
    responses.add(
        responses.GET,
        f"{BASE}/portals/self/servers",
        json=fixture_json("portal_self_servers.json"),
        status=200,
    )

    client = PortalClient("https://demo.maps.arcgis.com", TokenCredential("secret-token"))
    result = PortalScanner(client).scan()

    assert result.federation is not None
    servers = result.federation.servers
    assert len(servers) == 2

    hosting = next(s for s in servers if s.is_hosted)
    assert hosting.url == "https://hosting.demo.local/server"
    assert hosting.server_role == "HOSTING_SERVER"
    assert hosting.advanced_roles == ()

    federated = next(s for s in servers if not s.is_hosted)
    # Credential-bearing query string is stripped from the persisted URL.
    assert federated.url == "https://rt.demo.local/server"
    assert federated.server_role == "FEDERATED_SERVER"
    assert set(federated.advanced_roles) == {"geoevent", "geoanalytics", "notebook", "knowledge"}

    # Read-only and credential-safe.
    assert all(call.request.method == "GET" for call in responses.calls)


@responses.activate
def test_scanner_omits_federation_when_surface_forbidden(
    fixture_json: Callable[[str], dict[str, Any]],
) -> None:
    _register_self(fixture_json)
    responses.add(
        responses.GET,
        f"{BASE}/portals/self/servers",
        json={"error": {"code": 403, "message": "Forbidden"}},
        status=403,
    )

    client = PortalClient("https://demo.maps.arcgis.com", TokenCredential("secret-token"))
    result = PortalScanner(client).scan()

    assert result.federation is None
    assert any(d.code == "portal.federation.forbidden" for d in result.diagnostics)


@responses.activate
def test_scanner_omits_federation_when_no_servers(
    fixture_json: Callable[[str], dict[str, Any]],
) -> None:
    _register_self(fixture_json)
    responses.add(
        responses.GET,
        f"{BASE}/portals/self/servers",
        json={"servers": []},
        status=200,
    )

    client = PortalClient("https://demo.maps.arcgis.com", TokenCredential("secret-token"))
    result = PortalScanner(client).scan()

    assert result.federation is None


def _result_with_federation() -> PortalScanResult:
    return PortalScanResult(
        org=OrgInfo(
            id="org-123",
            name="Demo GIS",
            portal_url="https://demo.maps.arcgis.com",
            sharing_rest_url="https://demo.maps.arcgis.com/sharing/rest",
        ),
        auth_mode="token",
        federation=FederationInfo(
            servers=(
                FederatedServer(
                    url="https://hosting.demo.local/server",
                    server_role="HOSTING_SERVER",
                    is_hosted=True,
                ),
                FederatedServer(
                    url="https://rt.demo.local/server?token=secret-token",
                    server_role="FEDERATED_SERVER",
                    is_hosted=False,
                    functions=("GeoEvent", "GeoAnalytics"),
                    advanced_roles=("geoanalytics", "geoevent"),
                ),
            )
        ),
    )


def test_footprint_emits_federation_block_and_validates() -> None:
    footprint = to_footprint_v0_1(
        _result_with_federation(),
        tool_version="0.0.0",
        generated_at=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
    )

    validate_footprint(footprint)

    federation = footprint["portal"]["federation"]
    assert [s["url"] for s in federation["servers"]] == [
        "https://hosting.demo.local/server",
        "https://rt.demo.local/server",
    ]
    roles = {s["url"]: s.get("role") for s in federation["servers"]}
    assert roles["https://hosting.demo.local/server"] == "hosting"
    assert roles["https://rt.demo.local/server"] == "federated"
    assert federation["advancedRoles"] == ["geoanalytics", "geoevent"]


def test_footprint_federation_never_leaks_credentials() -> None:
    footprint = to_footprint_v0_1(
        _result_with_federation(),
        tool_version="0.0.0",
        generated_at=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
    )
    assert "secret-token" not in str(footprint)


def test_footprint_omits_federation_when_absent() -> None:
    result = PortalScanResult(
        org=OrgInfo(
            id="org-123",
            name="Demo GIS",
            portal_url="https://demo.maps.arcgis.com",
            sharing_rest_url="https://demo.maps.arcgis.com/sharing/rest",
        ),
        auth_mode="token",
        federation=None,
    )
    footprint = to_footprint_v0_1(result, tool_version="0.0.0")
    validate_footprint(footprint)
    assert "federation" not in footprint["portal"]
