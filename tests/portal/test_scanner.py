from __future__ import annotations

from typing import Any, Callable

import responses

from honua_esri_assess.portal import (
    AnonymousCredential,
    PortalClient,
    PortalScanner,
    RetryPolicy,
    TokenCredential,
)


@responses.activate
def test_token_scan_paginates_items_and_deep_scans_service(
    happy_path_responses: Callable[..., None],
) -> None:
    happy_path_responses(responses, include_users=True, include_service=True)

    client = PortalClient(
        "https://demo.maps.arcgis.com",
        TokenCredential("secret-token"),
        sleep=lambda _: None,
    )
    result = PortalScanner(client, deep=True).scan()

    assert result.auth_mode == "token"
    assert result.org.id == "org-123"
    assert result.org.user_count == 42
    assert result.org.group_count == 1
    assert len(result.items) == 3
    assert [item.id for item in result.items] == [
        "item-feature-1",
        "item-map-1",
        "item-dashboard-1",
    ]
    assert result.items[0].type_bucket == "featureService"
    assert result.items[0].layer_count == 2
    assert len(result.services) == 1
    assert len(result.services[0].layers) == 2
    assert all(call.request.method == "GET" for call in responses.calls)
    assert any("token=secret-token" in call.request.url for call in responses.calls)


@responses.activate
def test_anonymous_scan_enumerates_public_items_without_user_search(
    happy_path_responses: Callable[..., None],
) -> None:
    happy_path_responses(responses, include_users=False, include_service=False)

    client = PortalClient("https://demo.maps.arcgis.com", AnonymousCredential())
    result = PortalScanner(client).scan()

    assert result.auth_mode == "anonymous"
    assert len(result.items) == 3
    assert result.org.user_count is None
    assert any(diagnostic.code == "portal.users.skipped" for diagnostic in result.diagnostics)
    assert all("community/users" not in call.request.url for call in responses.calls)
    assert all("token=" not in call.request.url for call in responses.calls)


@responses.activate
def test_group_forbidden_surfaces_warning_and_continues(
    fixture_json: Callable[[str], dict[str, Any]],
) -> None:
    base = "https://demo.maps.arcgis.com/sharing/rest"
    responses.add(responses.GET, f"{base}/portals/self", json=fixture_json("portal_self.json"), status=200)
    responses.add(
        responses.GET,
        f"{base}/community/groups",
        json={"error": {"code": 403, "message": "Forbidden"}},
        status=403,
    )
    responses.add(responses.GET, f"{base}/community/users", json=fixture_json("users_count.json"), status=200)
    responses.add(responses.GET, f"{base}/search", json=fixture_json("search_page_1.json"), status=200)
    responses.add(responses.GET, f"{base}/search", json=fixture_json("search_page_2.json"), status=200)

    client = PortalClient("https://demo.maps.arcgis.com", TokenCredential("secret-token"))
    result = PortalScanner(client).scan()

    assert len(result.items) == 3
    assert result.groups == []
    assert any(diagnostic.code == "portal.groups.forbidden" for diagnostic in result.diagnostics)


@responses.activate
def test_item_search_rate_limit_returns_accumulated_partial_inventory(
    fixture_json: Callable[[str], dict[str, Any]],
) -> None:
    base = "https://demo.maps.arcgis.com/sharing/rest"
    responses.add(responses.GET, f"{base}/portals/self", json=fixture_json("portal_self.json"), status=200)
    responses.add(responses.GET, f"{base}/community/groups", json=fixture_json("groups_page_1.json"), status=200)
    responses.add(responses.GET, f"{base}/search", json=fixture_json("search_page_1.json"), status=200)
    for _ in range(3):
        responses.add(
            responses.GET,
            f"{base}/search",
            json=fixture_json("rate_limited.json"),
            status=429,
        )

    client = PortalClient(
        "https://demo.maps.arcgis.com",
        AnonymousCredential(),
        retry_policy=RetryPolicy(attempts=3, backoff_seconds=0),
        sleep=lambda _: None,
    )
    result = PortalScanner(client).scan()

    assert [item.id for item in result.items] == ["item-feature-1", "item-map-1"]
    assert any(diagnostic.code == "portal.items.rate-limited" for diagnostic in result.diagnostics)


@responses.activate
def test_deep_scan_skips_non_arcgis_service_url_without_token_leak(
    fixture_json: Callable[[str], dict[str, Any]],
) -> None:
    base = "https://demo.maps.arcgis.com/sharing/rest"
    responses.add(responses.GET, f"{base}/portals/self", json=fixture_json("portal_self.json"), status=200)
    responses.add(responses.GET, f"{base}/community/groups", json=fixture_json("groups_page_1.json"), status=200)
    responses.add(responses.GET, f"{base}/community/users", json=fixture_json("users_count.json"), status=200)
    responses.add(
        responses.GET,
        f"{base}/search",
        json={
            "total": 1,
            "start": 1,
            "num": 1,
            "nextStart": -1,
            "results": [
                {
                    "id": "external-service",
                    "title": "External Service",
                    "owner": "publisher",
                    "type": "Feature Service",
                    "access": "org",
                    "url": "https://external.example.com/arcgis/rest/services/Parcels/FeatureServer",
                    "modified": 1714521600000,
                }
            ],
        },
        status=200,
    )

    client = PortalClient("https://demo.maps.arcgis.com", TokenCredential("secret-token"))
    result = PortalScanner(client, deep=True).scan()

    assert result.services == []
    assert any(diagnostic.context.get("itemId") == "external-service" for diagnostic in result.diagnostics)
    assert all("external.example.com" not in call.request.url for call in responses.calls)
