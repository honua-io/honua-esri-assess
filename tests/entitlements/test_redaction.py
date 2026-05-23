"""Token and admin-URL redaction safeguards."""

from __future__ import annotations

import logging

import pytest

from honua_esri_assess.entitlements.diagnostics import (
    EntitlementsApiError,
    EntitlementsConnectionError,
)
from honua_esri_assess.entitlements.http import safe_url
from honua_esri_assess.entitlements.server import ServerEntitlementsCollector

from .conftest import StubHttpClient, respond


def test_safe_url_redacts_token_query_param() -> None:
    redacted = safe_url(
        "https://example.com/arcgis/admin/info?f=json&token=ABCDEF123456"
    )
    assert "ABCDEF123456" not in redacted
    assert "token=REDACTED" in redacted
    assert "/admin/info" not in redacted
    assert "/admin/[redacted]" in redacted


def test_safe_url_redacts_userinfo() -> None:
    redacted = safe_url("https://alice:secret@example.com/arcgis/rest/info?f=json")
    assert "alice" not in redacted
    assert "secret" not in redacted
    assert redacted == "https://example.com/arcgis/rest/info?f=json"


def test_safe_url_redacts_multiple_credential_keys() -> None:
    redacted = safe_url(
        "https://example.com/arcgis?f=json&token=t&password=p&client_secret=s"
    )
    assert "t" not in redacted.split("token=", 1)[1].split("&", 1)[0]
    assert "password=REDACTED" in redacted
    assert "client_secret=REDACTED" in redacted


def test_safe_url_passes_through_safe_query_unchanged() -> None:
    assert safe_url("https://example.com/x?f=json").endswith("?f=json")


def test_safe_url_handles_empty_input() -> None:
    assert safe_url("") == ""


def test_safe_url_strips_fragment() -> None:
    assert "#" not in safe_url("https://example.com/x?f=json#section")


def test_collector_error_messages_redact_admin_token(caplog: pytest.LogCaptureFixture) -> None:
    handlers = {
        "rest/info": respond(500, {"error": {"code": 500, "message": "boom"}}),
    }
    client = StubHttpClient(handlers=handlers)
    collector = ServerEntitlementsCollector("https://example.com/arcgis", client)

    caplog.set_level(logging.DEBUG, logger="honua_esri_assess")
    with pytest.raises(EntitlementsApiError) as ctx:
        collector.collect()

    message = str(ctx.value)
    assert "token=" not in message or "REDACTED" in message


def test_collector_connection_error_messages_redact_admin_token() -> None:
    client = StubHttpClient(
        handlers={},
        raise_on={"rest/info": ConnectionError("ConnectionRefused")},
    )
    collector = ServerEntitlementsCollector(
        "https://example.com/arcgis?token=SUPERSECRET", client
    )

    with pytest.raises(EntitlementsConnectionError) as ctx:
        collector.collect()

    assert "SUPERSECRET" not in str(ctx.value)
