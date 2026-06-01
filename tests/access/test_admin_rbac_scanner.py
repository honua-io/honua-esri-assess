"""Fixture-backed coverage for the read-only RBAC scanner."""

from __future__ import annotations

from honua_esri_assess.footprint.access import build_access_footprint, validate_access_footprint
from honua_esri_assess.scanners.admin_rbac import scan_portal_rbac, scan_server_rbac

from .conftest import StubHttpClient, respond, respond_fixture


def _portal_client() -> StubHttpClient:
    return StubHttpClient(
        handlers={
            "portals/self/users": respond_fixture("portal_users.json"),
            "portals/self/roles": respond_fixture("portal_roles.json"),
            "portals/self": respond_fixture("portal_self.json"),
            "community/groups": respond_fixture("portal_groups.json"),
        }
    )


def test_scan_portal_rbac_models_identity_and_validates() -> None:
    footprint = scan_portal_rbac("https://demo.maps.arcgis.com/sharing/rest", _portal_client())

    usernames = {u.username for u in footprint.users}
    assert usernames == {"alice", "bob"}
    bob = next(u for u in footprint.users if u.username == "bob")
    assert bob.disabled is True

    role_ids = {r.id for r in footprint.roles}
    # Built-in roles plus the custom one from the fixture.
    assert {"org_admin", "org_publisher", "org_user", "org_viewer", "custom-editor"} <= role_ids

    assert footprint.org_security.allowed_providers == ["arcgis", "saml", "oidc"]
    assert footprint.org_security.multi_factor_auth_required is True

    group_ids = {g.id for g in footprint.groups}
    assert group_ids == {"g-ops"}

    artifact = build_access_footprint(footprint)
    assert validate_access_footprint(artifact) is True


def _server_client() -> StubHttpClient:
    return StubHttpClient(
        handlers={
            "security/roles/getRoles": respond_fixture("server_roles.json"),
            "security/users/getUsers": respond_fixture("server_users.json"),
            "services/Parcels.MapServer/permissions": respond_fixture(
                "server_perms_parcels.json"
            ),
            "services/Hosted/Wells.FeatureServer/permissions": respond_fixture(
                "server_perms_wells.json"
            ),
            "services/Utilities/PrintingTools.GPServer/permissions": respond_fixture(
                "server_perms_printing.json"
            ),
            "services/Hosted": respond_fixture("server_services_hosted.json"),
            "services/Utilities": respond_fixture("server_services_utilities.json"),
            "services": respond_fixture("server_services_root.json"),
        }
    )


def test_scan_server_rbac_reads_admin_security_endpoints() -> None:
    client = _server_client()

    footprint = scan_server_rbac("https://host.local/arcgis/admin", client)

    assert footprint.source_kind == "arcgis-server"
    assert {r.name for r in footprint.roles} == {"publishers", "viewers"}
    assert footprint.users[0].username == "svc_publish"
    assert footprint.users[0].provider == "enterprise"
    assert validate_access_footprint(build_access_footprint(footprint)) is True


def test_scan_server_rbac_crawls_aces_across_catalog() -> None:
    client = _server_client()
    footprint = scan_server_rbac("https://host.local/arcgis/admin", client)

    # Services from the root folder and both sub-folders were crawled.
    crawled_urls = {p.service_url for p in footprint.service_permissions}
    assert crawled_urls == {
        "https://host.local/arcgis/admin/services/Parcels.MapServer",
        "https://host.local/arcgis/admin/services/Hosted/Wells.FeatureServer",
        "https://host.local/arcgis/admin/services/Utilities/PrintingTools.GPServer",
    }

    parcels = [
        p
        for p in footprint.service_permissions
        if p.service_url.endswith("Parcels.MapServer")
    ]
    by_principal = {p.principal: p for p in parcels}
    assert by_principal["publishers"].access == "allow"
    assert by_principal["publishers"].operations == ["Query", "Create", "Update", "Delete"]
    assert by_principal["viewers"].operations == ["Query"]
    # The reserved esriEveryone principal becomes the schema 'everyone' type.
    everyone = by_principal["*"]
    assert everyone.principal_type == "everyone"
    assert everyone.access == "deny"


def test_scan_server_rbac_resolves_effective_permissions() -> None:
    client = _server_client()
    footprint = scan_server_rbac("https://host.local/arcgis/admin", client)

    wells_url = "https://host.local/arcgis/admin/services/Hosted/Wells.FeatureServer"
    wells = [
        p for p in footprint.effective_permissions if p.service_url == wells_url
    ]
    # Two ACEs for publishers (allow + deny) collapse to a single deny grant
    # (deny overrides allow) whose operations are the sorted union.
    assert len(wells) == 1
    assert wells[0].principal == "publishers"
    assert wells[0].effect == "deny"
    assert wells[0].operations == ["Create", "Delete", "Query"]

    artifact = build_access_footprint(footprint)
    assert validate_access_footprint(artifact) is True
    # The artifact ships both the raw ACEs and the resolved collapse.
    assert artifact["effectivePermissions"]
    assert all("effect" in e for e in artifact["effectivePermissions"])


def test_denied_endpoint_becomes_missing_permission_diagnostic() -> None:
    client = StubHttpClient(
        handlers={
            "portals/self/users": respond(403, {"error": {"code": 403}}),
            "portals/self/roles": respond(200, {"roles": []}),
            "portals/self": respond_fixture("portal_self.json"),
            "community/groups": respond(200, {"results": []}),
        }
    )

    footprint = scan_portal_rbac("https://demo.maps.arcgis.com/sharing/rest", client)

    assert footprint.users == []
    codes = {d.code for d in footprint.diagnostics}
    assert "missing-permission" in codes
    # A denied users endpoint still produces a schema-valid (partial) artifact.
    assert validate_access_footprint(build_access_footprint(footprint)) is True


def test_ace_crawl_soft_failures_degrade_to_diagnostics() -> None:
    # The Wells permissions endpoint is denied (403), the Utilities folder
    # listing 404s, and the PrintingTools permissions endpoint is rate limited.
    # None of these abort the crawl; each becomes a typed diagnostic and the
    # reachable services still land in the artifact.
    client = StubHttpClient(
        handlers={
            "security/roles/getRoles": respond_fixture("server_roles.json"),
            "security/users/getUsers": respond_fixture("server_users.json"),
            "services/Parcels.MapServer/permissions": respond_fixture(
                "server_perms_parcels.json"
            ),
            "services/Hosted/Wells.FeatureServer/permissions": respond(
                403, {"error": {"code": 403}}
            ),
            "services/Utilities": respond(404, {"error": {"code": 404}}),
            "services/Hosted": respond_fixture("server_services_hosted.json"),
            "services": respond_fixture("server_services_root.json"),
        }
    )

    footprint = scan_server_rbac("https://host.local/arcgis/admin", client)

    crawled = {p.service_url for p in footprint.service_permissions}
    # Parcels (reachable) is present; Wells/PrintingTools (soft-failed) are absent.
    assert any(u.endswith("Parcels.MapServer") for u in crawled)
    assert not any(u.endswith("Wells.FeatureServer") for u in crawled)
    assert not any(u.endswith("PrintingTools.GPServer") for u in crawled)

    codes = {d.code for d in footprint.diagnostics}
    assert "missing-permission" in codes  # the denied Wells permissions read
    assert "partial-coverage" in codes  # the 404 Utilities folder listing
    # The partial export still validates.
    assert validate_access_footprint(build_access_footprint(footprint)) is True


def test_scanner_issues_only_documented_get_paths() -> None:
    client = _portal_client()
    scan_portal_rbac("https://demo.maps.arcgis.com/sharing/rest", client)

    # The stub's get_json is the only request entry point (GET-only by design);
    # assert we touched only the documented read-only endpoints.
    assert client.seen, "scanner issued no requests"
    for url in client.seen:
        assert any(
            tail in url
            for tail in (
                "portals/self",
                "portals/self/users",
                "portals/self/roles",
                "community/groups",
            )
        ), url
