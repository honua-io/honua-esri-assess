"""Golden-file tests for the access → recommendation mapper."""

from __future__ import annotations

from honua_esri_assess.access import (
    GroupDefinition,
    ItemSharing,
    PortalAccess,
    RoleDefinition,
    ServerAccess,
    UserPrincipal,
    build_recommendation,
)


def _portal() -> PortalAccess:
    return PortalAccess(
        users=(
            UserPrincipal(username="alice", role_id="org_admin", status="active"),
            UserPrincipal(username="bob", role_id="custom_editor", status="active"),
        ),
        roles=(
            RoleDefinition(
                id="org_admin",
                name="Administrator",
                scope="admin",
                privileges=("portal:admin:*",),
            ),
            RoleDefinition(
                id="custom_editor",
                name="Custom Editor",
                scope="custom",
                privileges=(
                    "portal:user:viewItems",
                    "portal:user:updateItems",
                ),
            ),
            RoleDefinition(
                id="custom_mystery",
                name="Unknown",
                scope="custom",
                privileges=(),
            ),
        ),
        groups=(
            GroupDefinition(
                id="groupA", title="Field Crew", access="private", owner="alice"
            ),
        ),
        item_sharing=(
            ItemSharing(item_id="item1", owner="alice", access_level="org"),
            ItemSharing(item_id="item2", owner="bob", access_level="public"),
            ItemSharing(
                item_id="item3",
                owner="alice",
                access_level="shared",
                shared_with_group_ids=("groupA",),
            ),
        ),
    )


def test_build_recommendation_maps_builtin_roles_high_confidence() -> None:
    rec = build_recommendation(portal=_portal())

    admin_mapping = next(m for m in rec.honua_roles if m.esri_role_id == "org_admin")
    assert admin_mapping.honua_role == "admin"
    assert admin_mapping.builtin == "admin"
    assert admin_mapping.confidence == "high"

    editor_mapping = next(
        m for m in rec.honua_roles if m.esri_role_id == "custom_editor"
    )
    assert editor_mapping.honua_role == "custom:custom_editor"
    assert editor_mapping.builtin == "editor"
    assert editor_mapping.confidence == "medium"

    mystery_mapping = next(
        m for m in rec.honua_roles if m.esri_role_id == "custom_mystery"
    )
    assert mystery_mapping.confidence == "low"
    assert mystery_mapping.builtin is None


def test_build_recommendation_emits_oidc_claims_one_per_honua_role() -> None:
    rec = build_recommendation(portal=_portal())
    honua_role_names = {m.honua_role for m in rec.honua_roles}
    claim_roles = {c.honua_role for c in rec.oidc_role_claims}
    assert claim_roles == honua_role_names
    for claim in rec.oidc_role_claims:
        assert claim.claim_name == "roles"
        assert claim.claim_value == claim.honua_role


def test_build_recommendation_facade_policies_group_by_access_and_groups() -> None:
    rec = build_recommendation(portal=_portal())
    policies = {p.policy_id: p for p in rec.facade_access_policies}
    # Three sharing modes → three policies
    assert set(policies) == {
        "facade:org:no-groups",
        "facade:public:no-groups",
        "facade:shared:groupA",
    }
    org_policy = policies["facade:org:no-groups"]
    assert org_policy.item_ids == ("item1",)
    assert org_policy.confidence == "high"
    public_policy = policies["facade:public:no-groups"]
    assert public_policy.confidence == "medium"


def test_build_recommendation_round_trip_is_stable() -> None:
    rec1 = build_recommendation(portal=_portal())
    rec2 = build_recommendation(portal=_portal())
    assert rec1 == rec2


def test_build_recommendation_handles_server_only_inputs() -> None:
    server = ServerAccess(
        roles=(
            RoleDefinition(
                id="Administrator",
                name="Administrator",
                scope="admin",
                privileges=("admin",),
            ),
        ),
    )
    rec = build_recommendation(server=server)
    assert len(rec.honua_roles) == 1
    assert rec.honua_roles[0].honua_role == "admin"
    # No portal item sharing → no facade policies
    assert rec.facade_access_policies == ()


def test_build_recommendation_empty_inputs_returns_empty_recommendation() -> None:
    rec = build_recommendation()
    assert rec.honua_roles == ()
    assert rec.oidc_role_claims == ()
    assert rec.facade_access_policies == ()
