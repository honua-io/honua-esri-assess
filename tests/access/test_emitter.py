"""Wire-shape + schema-validation tests for the access facet emitter."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from honua_esri_assess.access import (
    AccessFacet,
    GroupDefinition,
    ItemSharing,
    OrgSecurityPolicy,
    PortalAccess,
    RoleDefinition,
    ServerAccess,
    ServicePermission,
    UserPrincipal,
    build_recommendation,
)
from honua_esri_assess.footprint.access import (
    SCHEMA_VERSION_V0_2,
    access_facet_to_dict,
    apply_access_facet,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_V0_2 = json.loads(
    (REPO_ROOT / "schemas" / "esri-footprint-v0.2.json").read_text(encoding="utf-8")
)


def _v0_2_validator() -> Draft202012Validator:
    Draft202012Validator.check_schema(SCHEMA_V0_2)
    return Draft202012Validator(SCHEMA_V0_2, format_checker=FormatChecker())


def _portal_facet() -> PortalAccess:
    portal = PortalAccess(
        users=(
            UserPrincipal(
                username="alice",
                role_id="org_admin",
                status="active",
                last_login="2026-05-01T00:00:00Z",
                group_ids=("groupA",),
            ),
        ),
        roles=(
            RoleDefinition(
                id="org_admin",
                name="Administrator",
                scope="admin",
                privileges=("portal:admin:*",),
            ),
        ),
        groups=(
            GroupDefinition(
                id="groupA",
                title="Field Crew",
                access="private",
                owner="alice",
                capabilities=("updateitemcontrol",),
                member_count=12,
            ),
        ),
        item_sharing=(
            ItemSharing(item_id="abc123", owner="alice", access_level="org"),
        ),
        security_policy=OrgSecurityPolicy(
            mfa_required=True,
            sign_in_methods=("oidc",),
            password_min_length=12,
        ),
    )
    return portal._replace(
        mapping_recommendation=build_recommendation(portal=portal),
    ) if hasattr(portal, "_replace") else _with_recommendation(portal)


def _with_recommendation(portal: PortalAccess) -> PortalAccess:
    from dataclasses import replace

    return replace(portal, mapping_recommendation=build_recommendation(portal=portal))


def _server_facet() -> ServerAccess:
    from dataclasses import replace

    server = ServerAccess(
        users=(UserPrincipal(username="admin", status="active"),),
        roles=(
            RoleDefinition(
                id="Administrator",
                name="Administrator",
                scope="admin",
                privileges=("admin",),
            ),
        ),
        service_permissions=(
            ServicePermission(
                service_url="https://gis.example.com/arcgis/rest/services/Water/MapServer",
                principal="Administrator",
                principal_kind="role",
                capabilities=("Query", "Edit"),
            ),
        ),
        security_mode="BUILTIN",
        auth_tier="GIS_SERVER",
    )
    return replace(server, mapping_recommendation=build_recommendation(server=server))


def _baseline_portal_footprint() -> dict:
    return {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.2.0"},
        "source": {
            "kind": "arcgis-online",
            "locator": "example.maps.arcgis.com/0123ABCDEF",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "portal": {
            "orgId": "0123ABCDEF",
            "orgUrl": "https://example.maps.arcgis.com",
            "itemCounts": {"Feature Service": 1},
        },
        "inventory": [
            {
                "kind": "portal-item",
                "id": "abc123",
                "type": "Feature Service",
                "owner": "alice",
                "title": "Parcels",
                "sharing": "org",
                "modified": "2026-04-18T09:12:00Z",
                "dependencies": [],
            }
        ],
        "counts": {
            "items": {
                "portal-item": 1,
                "server-service": 0,
                "filegdb-feature-class": 0,
            },
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }


def _baseline_server_footprint() -> dict:
    return {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.2.0"},
        "source": {
            "kind": "arcgis-server",
            "locator": "https://gis.example.com/arcgis/rest/services",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "server": {
            "folders": [],
            "serviceCounts": {"MapServer": 1},
            "version": "11.2",
        },
        "inventory": [
            {
                "kind": "server-service",
                "serviceUrl": "https://gis.example.com/arcgis/rest/services/Water/MapServer",
                "serviceType": "MapServer",
                "folder": "",
                "layerCount": 0,
            }
        ],
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": 1,
                "filegdb-feature-class": 0,
            },
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }


def test_apply_access_facet_emits_v0_2_for_portal() -> None:
    facet = AccessFacet(portal=_portal_facet())
    out = apply_access_facet(_baseline_portal_footprint(), facet)
    assert out["schemaVersion"] == SCHEMA_VERSION_V0_2
    access = out["portal"]["access"]
    assert {u["username"] for u in access["users"]} == {"alice"}
    assert access["mappingRecommendation"]["honuaRoles"][0]["builtin"] == "admin"

    validator = _v0_2_validator()
    errors = sorted(validator.iter_errors(out), key=lambda e: list(e.path))
    assert errors == [], "\n".join(
        f"{list(err.path)}: {err.message}" for err in errors
    )


def test_apply_access_facet_emits_v0_2_for_server() -> None:
    facet = AccessFacet(server=_server_facet())
    out = apply_access_facet(_baseline_server_footprint(), facet)
    access = out["server"]["access"]
    assert access["securityMode"] == "BUILTIN"
    assert access["servicePermissions"][0]["serviceUrl"].endswith(
        "/Water/MapServer"
    )
    validator = _v0_2_validator()
    errors = sorted(validator.iter_errors(out), key=lambda e: list(e.path))
    assert errors == [], "\n".join(
        f"{list(err.path)}: {err.message}" for err in errors
    )


def test_apply_access_facet_with_empty_access_emits_empty_block() -> None:
    facet = AccessFacet(portal=PortalAccess())
    out = apply_access_facet(_baseline_portal_footprint(), facet)
    assert out["portal"]["access"] == {
        "users": [],
        "roles": [],
        "groups": [],
        "itemSharing": [],
    }
    _v0_2_validator().validate(out)


def test_access_facet_to_dict_strips_credential_bearing_urls() -> None:
    server = ServerAccess(
        service_permissions=(
            ServicePermission(
                service_url=(
                    "https://user:pass@gis.example.com/arcgis/rest/services/X/MapServer"
                    "?token=secret"
                ),
                principal="alice",
                principal_kind="user",
                capabilities=("Query",),
            ),
        ),
    )
    fragment = access_facet_to_dict(AccessFacet(server=server))
    url = fragment["server"]["access"]["servicePermissions"][0]["serviceUrl"]
    assert "@" not in url
    assert "?" not in url
    assert "token=" not in url


def test_schema_v0_2_is_packaged_alongside_canonical() -> None:
    packaged = REPO_ROOT / "src" / "honua_esri_assess" / "schemas" / "esri-footprint-v0.2.json"
    assert packaged.exists(), "v0.2 schema must be bundled into the wheel package"
    assert json.loads(packaged.read_text(encoding="utf-8")) == SCHEMA_V0_2
