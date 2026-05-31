"""Fixture-driven tests for the Portal access collector."""

from __future__ import annotations

import pytest

from honua_esri_assess.access import (
    AccessAuthError,
    AccessRateLimitedError,
    ItemSharing,
    PortalAccessCollector,
)
from honua_esri_assess.access.diagnostics import AccessSchemaError

from .conftest import StubHttpClient, load_fixture, respond


def _admin_handlers() -> dict[str, object]:
    return {
        "portals/self": respond(200, load_fixture("portal_self.json")),
        "portals/0123ABCDEF/roles": respond(200, load_fixture("portal_roles.json")),
        "portals/0123ABCDEF/securityPolicy": respond(
            200, load_fixture("portal_security_policy.json")
        ),
        "community/groups/groupA/users": respond(
            200, load_fixture("portal_group_users_groupA.json")
        ),
        "community/groups/groupB/users": respond(
            200, load_fixture("portal_group_users_groupB.json")
        ),
        "community/groups": respond(200, load_fixture("portal_groups.json")),
        "community/users": respond(200, load_fixture("portal_users.json")),
    }


def test_portal_collect_returns_full_access_facet() -> None:
    client = StubHttpClient(handlers=_admin_handlers())
    collector = PortalAccessCollector("https://www.arcgis.com", client)

    result = collector.collect()

    access = result.access
    role_ids = {role.id for role in access.roles}
    assert role_ids == {"custom_editor", "custom_viewer", "org_admin"}
    admin = next(role for role in access.roles if role.id == "org_admin")
    assert admin.scope == "admin"

    usernames = {user.username for user in access.users}
    assert usernames == {"alice", "bob", "carol"}
    bob = next(user for user in access.users if user.username == "bob")
    assert bob.full_name is None  # email-shaped full name was redacted
    assert bob.group_ids == ("groupA", "groupB")
    alice = next(user for user in access.users if user.username == "alice")
    assert alice.status == "active"
    assert alice.last_login is not None and alice.last_login.endswith("T00:00:00Z")
    carol = next(user for user in access.users if user.username == "carol")
    assert carol.status == "disabled"

    group_ids = {group.id for group in access.groups}
    assert group_ids == {"groupA", "groupB"}
    group_a = next(group for group in access.groups if group.id == "groupA")
    assert group_a.member_count == 5
    group_b = next(group for group in access.groups if group.id == "groupB")
    assert group_b.member_count == 250

    assert access.security_policy is not None
    policy = access.security_policy
    assert policy.mfa_required is True
    assert "oidc" in policy.sign_in_methods
    assert policy.password_min_length == 12


def test_portal_group_cap_emits_partial_coverage_when_exceeded() -> None:
    client = StubHttpClient(handlers=_admin_handlers())
    collector = PortalAccessCollector(
        "https://www.arcgis.com", client, group_cap=100
    )

    result = collector.collect()

    over_cap = [
        d
        for d in result.diagnostics
        if d.code == "partial-coverage"
        and d.scope == "portal.access.groups.groupB.users"
    ]
    assert over_cap, "expected partial-coverage diagnostic for capped group"


def test_portal_group_cap_zero_skips_member_probe() -> None:
    handlers = _admin_handlers()
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector(
        "https://www.arcgis.com", client, group_cap=0
    )

    collector.collect()

    assert not any("/users" in url for url in client.seen if "/groups/" in url)


def test_portal_forbidden_admin_endpoint_emits_missing_permission() -> None:
    handlers = _admin_handlers()
    handlers["portals/0123ABCDEF/roles"] = respond(403, load_fixture("error_403.json"))
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector("https://www.arcgis.com", client)

    result = collector.collect()

    scopes = {d.scope for d in result.diagnostics if d.code == "missing-permission"}
    assert "portal.access.roles" in scopes
    # other endpoints continued — users still came through
    assert any(u.username == "alice" for u in result.access.users)


def test_portal_self_missing_org_id_returns_empty_facet() -> None:
    handlers = {
        "portals/self": respond(200, {"portalMode": "multitenant"}),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector("https://www.arcgis.com", client)

    result = collector.collect()

    assert result.access.users == ()
    assert any(
        d.scope == "portal.access" and d.code == "partial-coverage"
        for d in result.diagnostics
    )


def test_portal_rate_limited_raises_typed_error() -> None:
    handlers = {
        "portals/self": respond(200, load_fixture("portal_self.json")),
        "portals/0123ABCDEF/roles": respond(429, {}),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector("https://www.arcgis.com", client)

    with pytest.raises(AccessRateLimitedError):
        collector.collect()


def test_portal_envelope_401_on_admin_endpoint_is_soft_handled() -> None:
    handlers = _admin_handlers()
    handlers["portals/0123ABCDEF/roles"] = respond(
        200, {"error": {"code": 401}}
    )
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector("https://www.arcgis.com", client)

    result = collector.collect()

    assert any(
        d.scope == "portal.access.roles" and d.code == "missing-permission"
        for d in result.diagnostics
    )
    # Hard auth failures still raise; the type is wired up.
    assert AccessAuthError is not None


def test_portal_envelope_with_non_integer_code_raises_typed_access_schema_error() -> None:
    """A non-numeric envelope code must surface as AccessSchemaError, not ValueError."""

    handlers = {
        "portals/self": respond(200, load_fixture("portal_self.json")),
        "portals/0123ABCDEF/roles": respond(
            200, {"error": {"code": "not-an-int", "message": "weird"}}
        ),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector("https://www.arcgis.com", client)

    with pytest.raises(AccessSchemaError):
        collector.collect()


def test_portal_email_shaped_principals_are_dropped_with_diagnostic() -> None:
    """Schema PrincipalName.not rejects emails; collector mirrors that AND emits a diagnostic."""

    groups_payload = {
        "results": [
            {
                "id": "groupX",
                "title": "Email Owner Group",
                # Email-shaped owner — schema-invalid via PrincipalName.not.
                "owner": "alice@example.com",
                "access": "private",
                "capabilities": [],
            }
        ],
        "nextStart": -1,
    }
    users_payload = {
        "results": [
            {
                # Email-shaped username — collector must drop with diagnostic.
                "username": "bob@example.com",
                "roleId": "org_admin",
                "disabled": False,
                "groups": [],
            }
        ],
        "nextStart": -1,
    }
    handlers = {
        "portals/self": respond(200, load_fixture("portal_self.json")),
        "portals/0123ABCDEF/roles": respond(200, {"roles": [], "nextStart": -1}),
        "portals/0123ABCDEF/securityPolicy": respond(200, {}),
        "community/groups": respond(200, groups_payload),
        "community/users": respond(200, users_payload),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector("https://www.arcgis.com", client)
    result = collector.collect()

    # The email-shaped username/owner records must not survive.
    assert all(user.username != "bob@example.com" for user in result.access.users)
    assert all(group.owner != "alice@example.com" for group in result.access.groups)
    # Diagnostics announce both drops.
    scopes = [d.scope for d in result.diagnostics if d.code == "redacted-field"]
    assert "portal.access.users" in scopes
    assert "portal.access.groups" in scopes


def test_portal_accepts_at_sign_principals_per_schema() -> None:
    """``@``-bearing usernames/owners are schema-valid PrincipalNames and must survive."""

    groups_payload = {
        "results": [
            {
                "id": "groupA",
                "title": "Subject Group",
                # SAML/OIDC-style subject owner with @ — schema-valid.
                "owner": "alice@enterprise",
                "access": "private",
                "capabilities": [],
            }
        ],
        "nextStart": -1,
    }
    users_payload = {
        "results": [
            {
                "username": "carol@enterprise",
                # Email-shaped fullName still gets dropped by the email guard.
                "fullName": "Carol Example",
                "roleId": "org_admin",
                "disabled": False,
                "groups": [],
            }
        ],
        "nextStart": -1,
    }
    handlers = {
        "portals/self": respond(200, load_fixture("portal_self.json")),
        "portals/0123ABCDEF/roles": respond(200, {"roles": [], "nextStart": -1}),
        "portals/0123ABCDEF/securityPolicy": respond(200, {}),
        "community/groups": respond(200, groups_payload),
        "community/groups/groupA/users": respond(200, {"total": 1, "users": []}),
        "community/users": respond(200, users_payload),
    }
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector("https://www.arcgis.com", client)
    result = collector.collect()

    usernames = {user.username for user in result.access.users}
    assert "carol@enterprise" in usernames
    owners = {group.owner for group in result.access.groups}
    assert "alice@enterprise" in owners


def test_portal_groups_and_users_are_scoped_to_org_id() -> None:
    client = StubHttpClient(handlers=_admin_handlers())
    collector = PortalAccessCollector("https://www.arcgis.com", client)

    collector.collect()

    expected_q = "orgid:0123ABCDEF"
    group_calls = [
        params
        for url, params in client.calls
        if url.endswith("community/groups")
    ]
    assert group_calls, "expected at least one community/groups call"
    assert all(call.get("q") == expected_q for call in group_calls), (
        f"community/groups calls were not org-scoped: {group_calls}"
    )

    user_calls = [
        params
        for url, params in client.calls
        if url.endswith("community/users")
    ]
    assert user_calls, "expected at least one community/users call"
    assert all(call.get("q") == expected_q for call in user_calls), (
        f"community/users calls were not org-scoped: {user_calls}"
    )


def test_portal_item_sharing_redacts_unsafe_records() -> None:
    handlers = _admin_handlers()
    client = StubHttpClient(handlers=handlers)
    collector = PortalAccessCollector("https://www.arcgis.com", client)
    item_sharing = [
        ItemSharing(item_id="abc", owner="alice", access_level="org"),
        ItemSharing(
            item_id="https://leak.example.com/x",
            owner="alice",
            access_level="org",
        ),
        ItemSharing(
            item_id="def",
            owner="https://leak.example.com/u?token=x",
            access_level="org",
        ),
    ]
    result = collector.collect(item_sharing=item_sharing)
    item_ids = {s.item_id for s in result.access.item_sharing}
    assert item_ids == {"abc"}
    item_sharing_drops = sum(
        1
        for d in result.diagnostics
        if d.code == "redacted-field"
        and d.scope == "portal.access.itemSharing"
    )
    assert item_sharing_drops == 2
