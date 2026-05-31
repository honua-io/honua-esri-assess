"""Redaction tests: access-tier export must never leak credentials."""

from __future__ import annotations

import json

from honua_esri_assess.access import (
    AccessFacet,
    PortalAccessCollector,
    ServerAccessCollector,
)
from honua_esri_assess.access.server import ServiceRef
from honua_esri_assess.footprint.access import apply_access_facet

from .conftest import StubHttpClient, respond


_FORBIDDEN_FRAGMENTS = (
    "topsecret-token",
    "hidden-password",
    "alice:superpass",
    "session-secret",
    "Bearer ",
    "client_secret=",
    "mfa_seed",
    "passwordHash",
    "password_hash",
    "email=",
    "@example.com",
)


def _assert_no_forbidden(payload: object) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
    for fragment in _FORBIDDEN_FRAGMENTS:
        assert fragment not in text, f"leaked {fragment!r} in: {text}"


def test_portal_admin_payload_with_secret_fields_is_redacted_from_emitter() -> None:
    self_payload = {"id": "0123ABCDEF"}
    roles_payload = {
        "roles": [
            {
                "id": "org_admin",
                "name": "Administrator",
                "privileges": ["portal:admin:*"],
                "description": "secret token=topsecret-token in description",
            }
        ],
        "nextStart": -1,
    }
    users_payload = {
        "results": [
            {
                "username": "alice",
                "fullName": "alice@example.com",
                "email": "alice@example.com",
                "passwordHash": "deadbeef",
                "password_hash": "deadbeef",
                "mfa_seed": "JBSWY3DPEHPK3PXP",
                "client_secret": "OAUTHSECRET",
                "roleId": "org_admin",
                "userType": "creatorUT",
                "disabled": False,
                "groups": [],
            }
        ],
        "nextStart": -1,
    }
    groups_payload = {"results": [], "nextStart": -1}
    security_payload = {
        "mfaRequired": True,
        "signinOptions": ["builtin"],
        "minLength": 12,
    }
    client = StubHttpClient(
        handlers={
            "portals/self": respond(200, self_payload),
            "portals/0123ABCDEF/roles": respond(200, roles_payload),
            "portals/0123ABCDEF/securityPolicy": respond(200, security_payload),
            "community/groups": respond(200, groups_payload),
            "community/users": respond(200, users_payload),
        }
    )
    collector = PortalAccessCollector("https://www.arcgis.com", client)
    result = collector.collect()
    facet = AccessFacet(portal=result.access)

    base = {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.2.0"},
        "source": {
            "kind": "arcgis-online",
            "locator": "fixture.local/0123ABCDEF",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "portal": {
            "orgId": "0123ABCDEF",
            "orgUrl": "https://fixture.local",
            "itemCounts": {},
        },
        "inventory": [],
        "counts": {
            "items": {"portal-item": 0, "server-service": 0, "filegdb-feature-class": 0},
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }
    out = apply_access_facet(base, facet)
    # The description text would leak the secret token; relax once we
    # confirm it's gone from the emitted artifact.
    serialized = json.dumps(out, sort_keys=True)
    assert "topsecret-token" not in serialized, (
        "secret token leaked through a role description into the artifact"
    )
    _assert_no_forbidden(out)
    user = out["portal"]["access"]["users"][0]
    # Email-shaped full name was redacted; no email field at all
    assert "fullName" not in user
    assert "email" not in user
    assert "passwordHash" not in user
    assert "mfa_seed" not in user
    assert "client_secret" not in user


def test_server_permission_payload_strips_url_credentials() -> None:
    handlers = {
        "admin/security/config": respond(200, {"securityMode": "BUILTIN"}),
        "admin/security/users/search": respond(200, {"users": [], "hasMore": False}),
        "admin/security/roles/search": respond(200, {"roles": [], "hasMore": False}),
        "admin/services/W.MapServer/permissions": respond(
            200,
            {
                "permissions": [
                    {
                        "principal": "alice",
                        "principalKind": "user",
                        "operations": ["Query"],
                    }
                ]
            },
        ),
    }
    client = StubHttpClient(handlers=handlers)
    collector = ServerAccessCollector(
        "https://alice:superpass@gis.fixture.local/arcgis", client
    )
    result = collector.collect(
        services=[ServiceRef(folder="", name="W", type="MapServer")]
    )
    facet = AccessFacet(server=result.access)
    base = {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.2.0"},
        "source": {
            "kind": "arcgis-server",
            "locator": "https://gis.fixture.local/arcgis/rest/services",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "server": {"folders": [], "serviceCounts": {"MapServer": 1}},
        "inventory": [
            {
                "kind": "server-service",
                "serviceUrl": "https://gis.fixture.local/arcgis/rest/services/W/MapServer",
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
    out = apply_access_facet(base, facet)
    _assert_no_forbidden(out)
    serialized = json.dumps(out, sort_keys=True)
    assert "alice:superpass" not in serialized


def test_portal_free_text_fields_strip_credential_fragments() -> None:
    """Valid records with credential-shaped substrings in title/fullName/name must redact."""

    self_payload = {"id": "0123ABCDEF"}
    roles_payload = {
        "roles": [
            {
                "id": "org_admin",
                # Role display name with a leaked authorization-style fragment.
                "name": "Admin authorization=role-name-leak-9182",
                "privileges": ["portal:admin:*"],
            }
        ],
        "nextStart": -1,
    }
    users_payload = {
        "results": [
            {
                "username": "alice",
                # No @ → bypasses the email guard; redaction must catch token=.
                "fullName": "Alice token=full-name-leak-3429",
                "roleId": "org_admin",
                "userType": "creatorUT",
                "disabled": False,
                "groups": [],
            }
        ],
        "nextStart": -1,
    }
    groups_payload = {
        "results": [
            {
                "id": "groupA",
                # Group title with an embedded token=.
                "title": "Field Crew api_key=group-title-leak-7765",
                "owner": "alice",
                "access": "private",
                "capabilities": [],
            }
        ],
        "nextStart": -1,
    }
    security_payload = {
        "mfaRequired": True,
        "signinOptions": ["builtin"],
        # Origin URL with embedded userinfo — sanitizer must strip it.
        "allowedOrigins": ["https://attacker:origin-leak-5511@allowed.local"],
        "minLength": 12,
    }
    client = StubHttpClient(
        handlers={
            "portals/self": respond(200, self_payload),
            "portals/0123ABCDEF/roles": respond(200, roles_payload),
            "portals/0123ABCDEF/securityPolicy": respond(200, security_payload),
            "community/groups": respond(200, groups_payload),
            "community/groups/groupA/users": respond(200, {"total": 1, "users": []}),
            "community/users": respond(200, users_payload),
        }
    )
    collector = PortalAccessCollector("https://www.arcgis.com", client)
    result = collector.collect()
    facet = AccessFacet(portal=result.access)
    base = {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.2.0"},
        "source": {
            "kind": "arcgis-online",
            "locator": "fixture.local/0123ABCDEF",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "portal": {
            "orgId": "0123ABCDEF",
            "orgUrl": "https://fixture.local",
            "itemCounts": {},
        },
        "inventory": [],
        "counts": {
            "items": {"portal-item": 0, "server-service": 0, "filegdb-feature-class": 0},
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }
    out = apply_access_facet(base, facet)
    serialized = json.dumps(out, sort_keys=True)

    # The credential-shaped value sides must not survive emission.
    for leaked_value in (
        "role-name-leak-9182",
        "full-name-leak-3429",
        "group-title-leak-7765",
        "attacker:origin-leak-5511",
        "origin-leak-5511",
    ):
        assert leaked_value not in serialized, f"leaked {leaked_value!r} in artifact"

    # Surrounding context survives — only the credential value was scrubbed.
    user = out["portal"]["access"]["users"][0]
    assert user["fullName"].startswith("Alice ")
    assert "<redacted>" in user["fullName"]
    role = out["portal"]["access"]["roles"][0]
    assert role["name"].startswith("Admin ")
    assert "<redacted>" in role["name"]
    group = out["portal"]["access"]["groups"][0]
    assert group["title"].startswith("Field Crew ")
    assert "<redacted>" in group["title"]
    policy = out["portal"]["access"]["securityPolicy"]
    # The userinfo-bearing origin survives as a schema-shaped URL,
    # never the redactor's "<redacted>" sentinel (which would violate
    # the v0.2 allowedOrigins pattern).
    assert policy["allowedOrigins"] == ["https://allowed.local"]

    # And the resulting v0.2 artifact must actually pass schema validation.
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "esri-footprint-v0.2.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(out)


def test_server_full_name_strips_credential_fragments() -> None:
    """Server-side user records must also scrub credential-like fullName/description values."""

    handlers = {
        "admin/security/config": respond(200, {"securityMode": "BUILTIN"}),
        "admin/security/users/search": respond(
            200,
            {
                "users": [
                    {
                        "username": "alice",
                        "fullname": "Alice token=server-fullname-leak-2233",
                        "role": "publisher",
                        "disabled": False,
                    }
                ],
                "hasMore": False,
            },
        ),
        "admin/security/roles/search": respond(
            200,
            {
                "roles": [
                    {
                        "rolename": "publisher",
                        "description": "Publisher api_key=server-desc-leak-4477 desc",
                        "privileges": ["publish:editing"],
                    }
                ],
                "hasMore": False,
            },
        ),
    }
    client = StubHttpClient(handlers=handlers)
    collector = ServerAccessCollector("https://gis.fixture.local/arcgis", client)
    result = collector.collect(services=[])
    facet = AccessFacet(server=result.access)
    base = {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.2.0"},
        "source": {
            "kind": "arcgis-server",
            "locator": "https://gis.fixture.local/arcgis/rest/services",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "server": {"folders": [], "serviceCounts": {}},
        "inventory": [],
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": 0,
                "filegdb-feature-class": 0,
            },
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }
    out = apply_access_facet(base, facet)
    serialized = json.dumps(out, sort_keys=True)
    assert "server-fullname-leak-2233" not in serialized
    assert "server-desc-leak-4477" not in serialized
    user = out["server"]["access"]["users"][0]
    assert user["fullName"].startswith("Alice ")
    assert "<redacted>" in user["fullName"]
    role = out["server"]["access"]["roles"][0]
    assert "<redacted>" in role["description"]


def test_access_models_forbid_secret_fields_at_import_time() -> None:
    """Smoke check that the runtime guard in access.models is wired up."""

    from honua_esri_assess.access import models as access_models

    # If a hostile change adds an `email` field on UserPrincipal, the guard
    # raises AssertionError during import. This test just confirms the
    # module loads cleanly today.
    assert hasattr(access_models, "UserPrincipal")
    assert hasattr(access_models, "ServicePermission")
