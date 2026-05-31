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
