"""Fixture-driven tests for the ArcGIS Server access collector."""

from __future__ import annotations

import pytest

from honua_esri_assess.access import (
    AccessRateLimitedError,
    ServerAccessCollector,
)
from honua_esri_assess.access.diagnostics import AccessSchemaError
from honua_esri_assess.access.server import ServiceRef

from .conftest import StubHttpClient, load_fixture, respond


def _admin_handlers() -> dict[str, object]:
    return {
        "admin/security/config": respond(
            200, load_fixture("server_security_config.json")
        ),
        "admin/security/users/search": respond(
            200, load_fixture("server_users.json")
        ),
        "admin/security/roles/search": respond(
            200, load_fixture("server_roles.json")
        ),
        "admin/services/Utilities/Water.MapServer/permissions": respond(
            200, load_fixture("server_service_permissions.json")
        ),
    }


def test_server_collect_returns_users_roles_permissions() -> None:
    client = StubHttpClient(handlers=_admin_handlers())
    collector = ServerAccessCollector("https://gis.example.com/arcgis", client)
    services = [ServiceRef(folder="Utilities", name="Water", type="MapServer")]

    result = collector.collect(services=services)

    assert result.access.security_mode == "BUILTIN"
    assert result.access.auth_tier == "GIS_SERVER"

    usernames = {u.username for u in result.access.users}
    assert {"alice", "bob"} <= usernames
    bob = next(u for u in result.access.users if u.username == "bob")
    assert bob.full_name is None  # email-shaped full_name was suppressed

    role_ids = {r.id for r in result.access.roles}
    assert role_ids == {"Administrator", "Publisher", "FieldEditor"}
    admin_role = next(r for r in result.access.roles if r.id == "Administrator")
    assert admin_role.scope == "admin"

    perms = result.access.service_permissions
    principals = {(p.principal, p.principal_kind) for p in perms}
    assert ("Publisher", "role") in principals
    assert ("alice", "user") in principals
    assert ("GuestGroup", "group") in principals
    # Empty operations or unsafe principal records were dropped
    assert all(p.capabilities for p in perms)
    assert all(p.service_url.endswith("/Water/MapServer") for p in perms)
    assert all("?" not in p.service_url and "#" not in p.service_url for p in perms)


def test_server_unsafe_service_ref_is_skipped() -> None:
    client = StubHttpClient(handlers=_admin_handlers())
    collector = ServerAccessCollector("https://gis.example.com/arcgis", client)
    bad = ServiceRef(folder="bad folder", name="x", type="MapServer")
    result = collector.collect(services=[bad])
    assert result.access.service_permissions == ()


def test_server_rate_limit_on_admin_raises() -> None:
    handlers = _admin_handlers()
    handlers["admin/security/users/search"] = respond(429, {})
    client = StubHttpClient(handlers=handlers)
    collector = ServerAccessCollector("https://gis.example.com/arcgis", client)
    with pytest.raises(AccessRateLimitedError):
        collector.collect(services=[])


def test_server_forbidden_admin_endpoint_emits_missing_permission() -> None:
    handlers = _admin_handlers()
    handlers["admin/security/config"] = respond(
        200, {"error": {"code": 403}}
    )
    client = StubHttpClient(handlers=handlers)
    collector = ServerAccessCollector("https://gis.example.com/arcgis", client)
    result = collector.collect(services=[])
    assert any(
        d.code == "missing-permission" and d.scope == "server.access.securityConfig"
        for d in result.diagnostics
    )
    assert result.access.security_mode is None


def test_server_email_shaped_principals_are_dropped_with_diagnostic() -> None:
    """Schema PrincipalName.not rejects emails; server collector mirrors that."""

    users_payload = {
        "users": [
            {
                "username": "alice@example.com",
                "role": "Publisher",
                "disabled": False,
            }
        ],
        "hasMore": False,
    }
    permissions_payload = {
        "permissions": [
            {
                "principal": "guest@example.com",
                "principalKind": "user",
                "operations": ["Query"],
            }
        ]
    }
    handlers = _admin_handlers()
    handlers["admin/security/users/search"] = respond(200, users_payload)
    handlers["admin/services/Utilities/Water.MapServer/permissions"] = respond(
        200, permissions_payload
    )
    client = StubHttpClient(handlers=handlers)
    collector = ServerAccessCollector("https://gis.example.com/arcgis", client)
    services = [ServiceRef(folder="Utilities", name="Water", type="MapServer")]
    result = collector.collect(services=services)

    assert all(user.username != "alice@example.com" for user in result.access.users)
    assert all(
        perm.principal != "guest@example.com"
        for perm in result.access.service_permissions
    )
    scopes = {d.scope for d in result.diagnostics if d.code == "redacted-field"}
    assert "server.access.users" in scopes
    # The service-scope diagnostic identifies which service the principal belonged to.
    assert any(
        d.scope.startswith("server.access.services/Utilities/Water.MapServer")
        and d.code == "redacted-field"
        for d in result.diagnostics
    )


def test_server_overlong_user_role_strings_truncate_with_diagnostics() -> None:
    """v0.2 schema caps must hold across server user/role/permission fields."""

    overlong_full_name = "n" * 300
    overlong_description = "D" * 700
    overlong_privilege = "p" * 200
    overlong_capability = "c" * 100
    overlong_security_mode = "S" * 80
    overlong_auth_tier = "T" * 80

    users_payload = {
        "users": [
            {
                "username": "alice",
                "fullname": overlong_full_name,
                "role": "Publisher",
                "disabled": False,
            }
        ],
        "hasMore": False,
    }
    roles_payload = {
        "roles": [
            {
                "rolename": "Publisher",
                "description": overlong_description,
                "privileges": [overlong_privilege],
            }
        ],
        "hasMore": False,
    }
    permissions_payload = {
        "permissions": [
            {
                "principal": "alice",
                "principalKind": "user",
                "operations": [overlong_capability],
            }
        ]
    }
    config_payload = {
        "securityMode": overlong_security_mode,
        "authenticationTier": overlong_auth_tier,
    }

    handlers = _admin_handlers()
    handlers["admin/security/config"] = respond(200, config_payload)
    handlers["admin/security/users/search"] = respond(200, users_payload)
    handlers["admin/security/roles/search"] = respond(200, roles_payload)
    handlers["admin/services/Utilities/Water.MapServer/permissions"] = respond(
        200, permissions_payload
    )
    client = StubHttpClient(handlers=handlers)
    collector = ServerAccessCollector("https://gis.example.com/arcgis", client)
    services = [ServiceRef(folder="Utilities", name="Water", type="MapServer")]
    result = collector.collect(services=services)

    alice = next(u for u in result.access.users if u.username == "alice")
    assert alice.full_name is not None and len(alice.full_name) <= 256
    publisher = next(r for r in result.access.roles if r.id == "Publisher")
    assert publisher.description is not None and len(publisher.description) <= 512
    assert all(len(p) <= 128 for p in publisher.privileges)
    assert result.access.security_mode is not None
    assert len(result.access.security_mode) <= 64
    assert result.access.auth_tier is not None
    assert len(result.access.auth_tier) <= 64
    for perm in result.access.service_permissions:
        assert all(len(c) <= 64 for c in perm.capabilities)

    truncation_scopes = {
        d.scope
        for d in result.diagnostics
        if d.code == "redacted-field"
        and "truncated" in d.message
    }
    assert "server.access.users" in truncation_scopes
    assert "server.access.roles" in truncation_scopes
    assert "server.access.securityConfig" in truncation_scopes
    assert any(
        s.startswith("server.access.services/Utilities/Water.MapServer")
        for s in truncation_scopes
    )


def test_server_pagination_cap_exhaustion_emits_partial_coverage() -> None:
    """Server _paginate must announce when the cap halts collection mid-stream."""

    def _runaway(url: str, params):
        next_start = int(params.get("start", "0")) + int(params.get("size", "100"))
        return respond(
            200,
            {"users": [], "roles": [], "hasMore": True, "nextStart": next_start},
        )(url, params)

    handlers = _admin_handlers()
    handlers["admin/security/users/search"] = _runaway
    handlers["admin/security/roles/search"] = _runaway
    client = StubHttpClient(handlers=handlers)
    collector = ServerAccessCollector("https://gis.example.com/arcgis", client)
    result = collector.collect(services=[])
    capped = {
        d.scope
        for d in result.diagnostics
        if d.code == "partial-coverage" and "capped" in d.message
    }
    assert {"server.access.users", "server.access.roles"} <= capped


def test_server_envelope_with_non_integer_code_raises_typed_access_schema_error() -> None:
    """Server collector must map a malformed envelope code to AccessSchemaError."""

    handlers = _admin_handlers()
    handlers["admin/security/config"] = respond(
        200, {"error": {"code": "not-an-int", "message": "weird"}}
    )
    client = StubHttpClient(handlers=handlers)
    collector = ServerAccessCollector("https://gis.example.com/arcgis", client)
    with pytest.raises(AccessSchemaError):
        collector.collect(services=[])
