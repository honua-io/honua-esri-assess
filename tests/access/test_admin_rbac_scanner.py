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


def test_scan_server_rbac_reads_admin_security_endpoints() -> None:
    client = StubHttpClient(
        handlers={
            "security/roles/getRoles": respond_fixture("server_roles.json"),
            "security/users/getUsers": respond_fixture("server_users.json"),
        }
    )

    footprint = scan_server_rbac("https://host.local/arcgis/admin", client)

    assert footprint.source_kind == "arcgis-server"
    assert {r.name for r in footprint.roles} == {"publishers", "viewers"}
    assert footprint.users[0].username == "svc_publish"
    assert footprint.users[0].provider == "enterprise"
    assert validate_access_footprint(build_access_footprint(footprint)) is True


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
