"""Credentials must never reach the access-footprint artifact."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from honua_esri_assess.entitlements.http import HttpResponse
from honua_esri_assess.footprint.access import build_access_footprint
from honua_esri_assess.scanners.admin_rbac import scan_portal_rbac, scan_server_rbac

from .conftest import StubHttpClient, load_fixture

SECRET_TARGET = (
    "https://alice:superpass@demo.maps.arcgis.com/sharing/rest"
    "?token=topsecret-token&password=hidden-password#frag"
)

_SECRETS = (
    "alice:superpass",
    "superpass",
    "topsecret-token",
    "hidden-password",
    "token=topsecret",
    "password=hidden",
    "#frag",
)


def _assert_no_secrets(value: Any) -> None:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    for secret in _SECRETS:
        assert secret not in text, secret


def _portal_client() -> StubHttpClient:
    def _portal_payload(name: str):
        def handler(url: str, params):
            return HttpResponse(status_code=200, body=load_fixture(name))

        return handler

    return StubHttpClient(
        handlers={
            "portals/self/users": _portal_payload("portal_users.json"),
            "portals/self/roles": _portal_payload("portal_roles.json"),
            "portals/self": _portal_payload("portal_self.json"),
            "community/groups": _portal_payload("portal_groups.json"),
        }
    )


def test_scanner_uses_raw_target_but_artifact_is_credential_free() -> None:
    client = _portal_client()
    footprint = scan_portal_rbac(SECRET_TARGET, client)
    artifact = build_access_footprint(footprint)

    # The scanner uses the raw target for its requests...
    assert any("alice:superpass@" in url for url in client.seen)
    # ...but the artifact (and its locator) carry no credentials.
    locator = artifact["source"]["locator"]
    assert "@" not in locator and "token" not in locator
    assert urlsplit("https://" + locator).path.startswith("/sharing/rest") or "/" in locator
    _assert_no_secrets(artifact)


def test_service_permission_url_strips_embedded_credentials() -> None:
    from honua_esri_assess.scanners.admin_rbac import model_service_permission

    perm = model_service_permission(
        "https://svc:secret@host.local/server/rest/services/X/FeatureServer?token=topsecret-token",
        "role",
        "publishers",
        "allow",
    )
    assert perm.service_url == "https://host.local/server/rest/services/X/FeatureServer"
    _assert_no_secrets(perm.service_url)


def test_server_scan_locator_is_credential_free() -> None:
    client = StubHttpClient(
        handlers={
            "security/roles/getRoles": lambda u, p: HttpResponse(200, {"roles": []}),
            "security/users/getUsers": lambda u, p: HttpResponse(200, {"users": []}),
            "services/Secret.MapServer/permissions": lambda u, p: HttpResponse(
                200,
                {"permissions": [{"principal": "publishers", "permission": {"isAllowed": True}}]},
            ),
            "services": lambda u, p: HttpResponse(
                200, {"folders": [], "services": [{"serviceName": "Secret", "type": "MapServer"}]}
            ),
        }
    )
    footprint = scan_server_rbac(
        "https://admin:secret@host.local/arcgis/admin?token=topsecret-token", client
    )
    artifact = build_access_footprint(footprint)
    assert "@" not in artifact["source"]["locator"]
    # The crawled service URLs carry no credentials from the secret-laden target.
    for perm in artifact["servicePermissions"]:
        assert "@" not in perm["serviceUrl"] and "token" not in perm["serviceUrl"]
    _assert_no_secrets(artifact)
