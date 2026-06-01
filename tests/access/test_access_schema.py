"""Schema + builder contract for the EsriAccessFootprint v0.2 artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from honua_esri_assess.diagnostics import Diagnostic, PortalSchemaError
from honua_esri_assess.footprint import access as access_module
from honua_esri_assess.footprint.access import (
    AccessFootprint,
    AccessGroup,
    AccessRole,
    AccessUser,
    ItemSharing,
    OrgSecurity,
    ServicePermission,
    build_access_footprint,
    resolve_effective_permissions,
    validate_access_footprint,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Both published access-footprint schema versions ship in the canonical and
# package-data locations and must stay byte-identical between the two.
ACCESS_SCHEMA_FILENAMES = (
    "esri-access-footprint-v0.1.json",
    "esri-access-footprint-v0.2.json",
)
CANONICAL = REPO_ROOT / "schemas" / "esri-access-footprint-v0.2.json"
PACKAGE = (
    REPO_ROOT
    / "src"
    / "honua_esri_assess"
    / "schemas"
    / "esri-access-footprint-v0.2.json"
)


def _full_footprint() -> AccessFootprint:
    return AccessFootprint(
        source_kind="arcgis-online",
        locator="demo.maps.arcgis.com/0123ABCDEF456789",
        users=[
            AccessUser(
                username="alice",
                role_id="org_admin",
                full_name="Alice Admin",
                group_ids=["g-ops"],
                provider="saml",
            )
        ],
        roles=[
            AccessRole(
                id="org_admin",
                name="Administrator",
                type="administrator",
                privileges=["portal:admin:manageRoles"],
            )
        ],
        groups=[
            AccessGroup(id="g-ops", title="Operations", access="org", member_count=12)
        ],
        service_permissions=[
            ServicePermission(
                service_url="https://host.local/server/rest/services/Parcels/FeatureServer",
                principal_type="role",
                principal="org_admin",
                access="allow",
            )
        ],
        item_sharing=[
            ItemSharing(item_id="item-1", owner="alice", access="org")
        ],
        org_security=OrgSecurity(
            allowed_providers=["arcgis", "saml"], multi_factor_auth_required=True
        ),
        diagnostics=[
            Diagnostic(
                code="missing-permission",
                message="Could not read custom role privileges.",
                scope="portal.roles",
            )
        ],
    )


@pytest.mark.parametrize("filename", ACCESS_SCHEMA_FILENAMES)
def test_packaged_schema_matches_canonical(filename: str) -> None:
    canonical = REPO_ROOT / "schemas" / filename
    packaged = REPO_ROOT / "src" / "honua_esri_assess" / "schemas" / filename
    assert packaged.exists(), f"package-data copy of {filename} is missing"
    assert json.loads(packaged.read_text(encoding="utf-8")) == json.loads(
        canonical.read_text(encoding="utf-8")
    )


def test_build_full_footprint_validates() -> None:
    artifact = build_access_footprint(_full_footprint())
    assert artifact["schemaVersion"] == "v0.2"
    assert validate_access_footprint(artifact) is True


def test_build_empty_footprint_validates() -> None:
    artifact = build_access_footprint(
        AccessFootprint(source_kind="arcgis-server", locator="https://host.local/arcgis/admin")
    )
    assert validate_access_footprint(artifact) is True
    assert artifact["users"] == []
    assert artifact["orgSecurity"] == {"allowedProviders": []}


def test_service_permission_url_is_redacted_and_schema_valid() -> None:
    artifact = build_access_footprint(
        AccessFootprint(
            source_kind="arcgis-server",
            locator="https://host.local/arcgis/admin",
            service_permissions=[
                ServicePermission(
                    service_url="https://u:p@host.local/server/rest/services/X/FeatureServer?token=secret",
                    principal_type="everyone",
                    principal="*",
                    access="allow",
                )
            ],
        )
    )
    url = artifact["servicePermissions"][0]["serviceUrl"]
    assert url == "https://host.local/server/rest/services/X/FeatureServer"
    assert validate_access_footprint(artifact) is True


def test_validate_rejects_unknown_top_level_key() -> None:
    artifact = build_access_footprint(_full_footprint())
    artifact["unexpected"] = True
    with pytest.raises(PortalSchemaError):
        validate_access_footprint(artifact)


def test_resolve_effective_permissions_deny_overrides_and_unions_operations() -> None:
    url = "https://host.local/server/rest/services/X/FeatureServer"
    resolved = resolve_effective_permissions(
        [
            ServicePermission(url, "role", "pub", "allow", operations=["Query", "Create"]),
            ServicePermission(url, "role", "pub", "deny", operations=["Delete"]),
            ServicePermission(url, "everyone", "*", "allow", operations=["Query"]),
        ]
    )

    by_principal = {p.principal: p for p in resolved}
    # Two ACEs for the same (service, principal) collapse; deny wins.
    assert by_principal["pub"].effect == "deny"
    assert by_principal["pub"].operations == ["Create", "Delete", "Query"]
    # The everyone principal is a distinct grant, preserved verbatim.
    assert by_principal["*"].principal_type == "everyone"
    assert by_principal["*"].effect == "allow"
    # Output order is deterministic (sorted by service/principalType/principal).
    assert [p.principal for p in resolved] == ["*", "pub"]


def test_resolve_effective_permissions_is_deterministic_across_input_order() -> None:
    url = "https://host.local/server/rest/services/X/FeatureServer"
    a = ServicePermission(url, "role", "pub", "allow", operations=["Query"])
    b = ServicePermission(url, "role", "view", "allow", operations=["Query"])
    forward = resolve_effective_permissions([a, b])
    reverse = resolve_effective_permissions([b, a])
    assert [p.principal for p in forward] == [p.principal for p in reverse]


def test_effective_permissions_auto_derived_in_artifact() -> None:
    url = "https://host.local/server/rest/services/X/FeatureServer"
    artifact = build_access_footprint(
        AccessFootprint(
            source_kind="arcgis-server",
            locator="https://host.local/arcgis/admin",
            service_permissions=[
                ServicePermission(url, "role", "pub", "allow", operations=["Query"]),
                ServicePermission(url, "role", "pub", "deny", operations=["Delete"]),
            ],
        )
    )
    assert len(artifact["effectivePermissions"]) == 1
    assert artifact["effectivePermissions"][0]["effect"] == "deny"
    assert artifact["effectivePermissions"][0]["operations"] == ["Delete", "Query"]
    assert validate_access_footprint(artifact) is True


def test_load_access_schema_is_v0_2() -> None:
    schema = access_module.load_access_schema()
    assert schema["properties"]["schemaVersion"]["enum"] == ["v0.1", "v0.2"]
