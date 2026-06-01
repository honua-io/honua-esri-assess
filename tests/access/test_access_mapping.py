"""RBAC export round-trips to a Honua RBAC + facade access-policy mapping."""

from __future__ import annotations

from honua_esri_assess.footprint.access import (
    AccessFootprint,
    AccessRole,
    ItemSharing,
    ServicePermission,
)
from honua_esri_assess.footprint.access_mapping import map_to_honua_rbac
from honua_esri_assess.scanners.admin_rbac import scan_portal_rbac

from .conftest import StubHttpClient, respond_fixture


def _footprint() -> AccessFootprint:
    return AccessFootprint(
        source_kind="arcgis-online",
        locator="demo.maps.arcgis.com/org",
        roles=[
            AccessRole(
                id="org_admin",
                name="Administrator",
                type="administrator",
                privileges=["portal:admin:manageRoles", "portal:user:createItem"],
            ),
            AccessRole(
                id="custom-editor",
                name="Field Editor",
                type="custom",
                privileges=[
                    "portal:publisher:publishFeatures",
                    "portal:user:doSomethingUndocumented",
                ],
            ),
        ],
        service_permissions=[
            ServicePermission(
                service_url="https://host.local/server/rest/services/X/FeatureServer",
                principal_type="role",
                principal="custom-editor",
                access="allow",
            )
        ],
        item_sharing=[ItemSharing(item_id="item-1", owner="alice", access="public")],
    )


def test_maps_roles_to_honua_roles_with_permission_verbs() -> None:
    mapping = map_to_honua_rbac(_footprint())

    by_source = {r["sourceRoleId"]: r for r in mapping["honuaRoles"]}
    assert by_source["org_admin"]["honuaRoleId"] == "honua.admin"
    assert "rbac:manage" in by_source["org_admin"]["permissions"]
    # Custom roles get a stable, namespaced honua id.
    assert by_source["custom-editor"]["honuaRoleId"] == "honua.custom.custom-editor"
    # Unknown privileges are surfaced, not silently dropped.
    assert by_source["custom-editor"]["unmappedPrivileges"] == [
        "portal:user:doSomethingUndocumented"
    ]
    assert "service:publish" in by_source["custom-editor"]["permissions"]


def test_oidc_role_claims_target_honua_roles() -> None:
    mapping = map_to_honua_rbac(_footprint())
    claims = {c["value"]: c for c in mapping["oidcRoleClaims"]}
    assert claims["Administrator"]["claim"] == "roles"
    assert claims["Administrator"]["honuaRoleId"] == "honua.admin"


def test_facade_policies_resolve_role_principal_to_honua_id() -> None:
    mapping = map_to_honua_rbac(_footprint())
    policies = mapping["accessPolicies"]

    svc = next(p for p in policies if p["resourceType"] == "service")
    assert svc["principal"] == "honua.custom.custom-editor"
    assert svc["effect"] == "allow"

    item = next(p for p in policies if p["resourceType"] == "item")
    assert item["principalType"] == "everyone"
    assert item["principal"] == "*"


def test_round_trip_from_scanned_footprint() -> None:
    client = StubHttpClient(
        handlers={
            "portals/self/users": respond_fixture("portal_users.json"),
            "portals/self/roles": respond_fixture("portal_roles.json"),
            "portals/self": respond_fixture("portal_self.json"),
            "community/groups": respond_fixture("portal_groups.json"),
        }
    )
    footprint = scan_portal_rbac("https://demo.maps.arcgis.com/sharing/rest", client)
    mapping = map_to_honua_rbac(footprint)

    honua_role_ids = {r["honuaRoleId"] for r in mapping["honuaRoles"]}
    assert "honua.admin" in honua_role_ids
    assert mapping["oidcRoleClaims"]
