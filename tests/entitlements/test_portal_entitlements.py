"""Fixture-driven tests for the AGOL / Enterprise Portal collector."""

from __future__ import annotations

from honua_esri_assess.entitlements.http import HttpResponse
from honua_esri_assess.entitlements.portal import PortalEntitlementsCollector

from .conftest import StubHttpClient, load_fixture, respond


def _portal_handlers_admin() -> dict[str, object]:
    return {
        "portals/self/subscriptionInfo": respond(200, load_fixture("portal_subscription_info.json")),
        "portals/self/userLicenseTypes": respond(200, load_fixture("portal_user_license_types.json")),
        "portals/self": respond(200, load_fixture("portal_self.json")),
        "/users": respond(200, load_fixture("portal_users.json")),
    }


def test_portal_collect_with_token_returns_user_types_and_extensions() -> None:
    client = StubHttpClient(handlers=_portal_handlers_admin())
    collector = PortalEntitlementsCollector("https://www.arcgis.com", client)

    result = collector.collect()

    licensing = result.licensing
    assert licensing.tier == "online"
    assert licensing.subscription_type == "Subscription"
    assert licensing.premium_credits_enabled is True
    assert "premiumContent" in licensing.allowed_add_ons
    assert "hub" in licensing.allowed_add_ons
    user_type_names = {ut.name for ut in licensing.user_types}
    assert {"creatorUT", "viewerUT", "fieldWorkerUT"} <= user_type_names
    creator = next(ut for ut in licensing.user_types if ut.name == "creatorUT")
    assert creator.total == 50
    assert creator.assigned == 32
    codes = {ext.code for ext in licensing.extensions_observed}
    assert "Spatial" in codes
    assert "BusinessAnalyst" in codes
    assert "premiumContent" not in codes
    assert "spatialAnalysis" not in codes
    assert "hub" not in codes
    assert not any(d.scope and "premiumContent" in d.scope for d in result.diagnostics)
    assert not any(d.scope and "spatialAnalysis" in d.scope for d in result.diagnostics)
    assert not any(d.scope and "hub" in d.scope for d in result.diagnostics)


def test_portal_subscription_endpoint_reports_only_explicit_extensions() -> None:
    self_payload = load_fixture("portal_self.json")
    self_payload["subscriptionInfo"].pop("extensions")
    subscription_payload = load_fixture("portal_subscription_info.json")
    subscription_payload["extensions"] = [{"code": "Spatial"}]
    client = StubHttpClient(
        handlers={
            "portals/self/subscriptionInfo": respond(200, subscription_payload),
            "portals/self/userLicenseTypes": respond(
                200, load_fixture("portal_user_license_types.json")
            ),
            "portals/self": respond(200, self_payload),
            "/users": respond(200, load_fixture("portal_users.json")),
        }
    )
    collector = PortalEntitlementsCollector("https://www.arcgis.com", client)

    result = collector.collect()

    assert result.licensing.allowed_add_ons == [
        "hub",
        "premiumContent",
        "spatialAnalysis",
    ]
    assert {ext.code for ext in result.licensing.extensions_observed} == {"Spatial"}


def test_portal_anonymous_skips_token_endpoints_and_emits_diagnostic() -> None:
    handlers = {
        "portals/self": respond(200, load_fixture("portal_self_anonymous.json")),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalEntitlementsCollector(
        "https://www.arcgis.com", client, anonymous=True
    )

    result = collector.collect()

    assert result.licensing.tier == "online"
    assert result.licensing.user_types == []
    scopes = {d.scope for d in result.diagnostics}
    codes = {d.code for d in result.diagnostics}
    assert "portal.subscriptionInfo" in scopes
    assert "missing-permission" in codes
    # Anonymous mode must not hit token-required endpoints.
    assert not any("subscriptionInfo" in url for url in client.seen)
    assert not any("userLicenseTypes" in url for url in client.seen)
    assert not any("/users" in url for url in client.seen)


def test_portal_token_with_forbidden_admin_endpoint_emits_missing_permission() -> None:
    handlers = {
        "portals/self": respond(200, load_fixture("portal_self.json")),
        "portals/self/subscriptionInfo": respond(403, load_fixture("error_403.json")),
        "portals/self/userLicenseTypes": respond(403, load_fixture("error_403.json")),
        "/users": respond(403, load_fixture("error_403.json")),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalEntitlementsCollector("https://www.arcgis.com", client)

    result = collector.collect()

    permission_diags = [d for d in result.diagnostics if d.code == "missing-permission"]
    scopes = {d.scope for d in permission_diags}
    assert "portal.subscriptionInfo" in scopes
    assert "portal.userLicenseTypes" in scopes
    assert "portal.users" in scopes
    assert result.licensing.subscription_type == "Subscription"
    # extensionsObserved still came from the public self payload.
    assert {ext.code for ext in result.licensing.extensions_observed} >= {"Spatial"}


def test_portal_unknown_extension_emits_partial_coverage_diagnostic() -> None:
    custom_self = load_fixture("portal_self.json")
    custom_self["subscriptionInfo"]["extensions"].append(
        {"code": "ContosoCustomExt", "name": "Contoso Custom Extension"}
    )
    handlers = {
        "portals/self": respond(200, custom_self),
        "portals/self/subscriptionInfo": respond(200, load_fixture("portal_subscription_info.json")),
        "portals/self/userLicenseTypes": respond(200, load_fixture("portal_user_license_types.json")),
        "/users": respond(200, load_fixture("portal_users.json")),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalEntitlementsCollector("https://www.arcgis.com", client)

    result = collector.collect()

    assert any(
        d.code == "partial-coverage"
        and d.scope == "portal.subscriptionInfo.extensions.ContosoCustomExt"
        for d in result.diagnostics
    )


def test_portal_invalid_token_envelope_is_soft_failure() -> None:
    handlers = {
        "portals/self": respond(200, load_fixture("portal_self.json")),
        "portals/self/subscriptionInfo": respond(200, load_fixture("error_498.json")),
        "portals/self/userLicenseTypes": respond(200, load_fixture("portal_user_license_types.json")),
        "/users": respond(200, load_fixture("portal_users.json")),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalEntitlementsCollector("https://www.arcgis.com", client)

    result = collector.collect()

    codes = {d.code for d in result.diagnostics}
    assert "missing-permission" in codes
    # userLicenseTypes still succeeded so we can still report user types.
    assert any(ut.name == "creatorUT" for ut in result.licensing.user_types)


def test_portal_no_subscription_block_in_self_payload_yields_safe_defaults() -> None:
    handlers = {
        "portals/self": respond(200, {"id": "x", "portalMode": "multitenant"}),
        "portals/self/subscriptionInfo": respond(200, {}),
        "portals/self/userLicenseTypes": respond(200, {}),
        "/users": respond(200, {"total": 4}),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalEntitlementsCollector("https://www.arcgis.com", client)

    result = collector.collect()

    assert result.licensing.tier == "online"
    assert result.licensing.subscription_type is None
    # /users endpoint provided an org-wide total fallback.
    assert any(ut.name == "all" and ut.total == 4 for ut in result.licensing.user_types)


def test_portal_empty_self_body_is_recorded_as_partial_coverage() -> None:
    handlers = {
        "portals/self": lambda url, params: HttpResponse(status_code=200, body=None),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalEntitlementsCollector(
        "https://www.arcgis.com", client, anonymous=True
    )

    result = collector.collect()
    assert any(
        d.code == "partial-coverage" and d.scope == "portal.self"
        for d in result.diagnostics
    )
