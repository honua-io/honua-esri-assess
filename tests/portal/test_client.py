from __future__ import annotations

from typing import Any, Callable

import pytest

from honua_esri_assess.diagnostics import PortalAuthError
from honua_esri_assess.portal import PortalClient, RetryPolicy, TokenCredential
from honua_esri_assess.portal.client import normalize_portal_url, redact_url


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object], headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> dict[str, object]:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, object], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return self.responses.pop(0)


def test_normalizes_portal_and_sharing_rest_urls() -> None:
    urls = normalize_portal_url("https://demo.maps.arcgis.com/sharing/rest")

    assert urls.portal_url == "https://demo.maps.arcgis.com"
    assert urls.sharing_rest_url == "https://demo.maps.arcgis.com/sharing/rest"


def test_normalized_urls_drop_userinfo_query_and_fragment() -> None:
    urls = normalize_portal_url(
        "https://alice:secret@demo.maps.arcgis.com/sharing/rest?token=secret#session"
    )

    assert urls.portal_url == "https://demo.maps.arcgis.com"
    assert urls.sharing_rest_url == "https://demo.maps.arcgis.com/sharing/rest"


def test_redacts_sensitive_query_values() -> None:
    redacted = redact_url("https://alice:pw@example.com/path?token=secret&password=pw&f=json")

    assert "alice" not in redacted
    assert "secret" not in redacted
    assert "pw" not in redacted
    assert "token=%5BREDACTED%5D" in redacted


def test_token_auth_error_is_typed_and_redacted() -> None:
    session = FakeSession(
        [FakeResponse(200, {"error": {"code": 498, "message": "Invalid token secret-token"}})]
    )
    client = PortalClient(
        "https://demo.maps.arcgis.com",
        TokenCredential("secret-token"),
        session=session,  # type: ignore[arg-type]
    )

    with pytest.raises(PortalAuthError) as exc_info:
        client.get_json("portals/self")

    assert session.calls[0]["params"]["token"] == "secret-token"
    assert "secret-token" not in str(exc_info.value)
    assert "secret-token" not in str(exc_info.value.context)


def test_http_401_auth_error_is_typed(fixture_json: Callable[[str], dict[str, Any]]) -> None:
    session = FakeSession([FakeResponse(401, fixture_json("expired_token.json"))])
    client = PortalClient(
        "https://demo.maps.arcgis.com",
        TokenCredential("secret-token"),
        session=session,  # type: ignore[arg-type]
    )

    with pytest.raises(PortalAuthError):
        client.get_json("portals/self")


def test_rate_limit_retries_before_success(fixture_json: Callable[[str], dict[str, Any]]) -> None:
    sleeps: list[float] = []
    session = FakeSession(
        [
            FakeResponse(429, fixture_json("rate_limited.json"), {"Retry-After": "0"}),
            FakeResponse(200, {"ok": True}),
        ]
    )
    client = PortalClient(
        "https://demo.maps.arcgis.com",
        retry_policy=RetryPolicy(attempts=2),
        session=session,  # type: ignore[arg-type]
        sleep=sleeps.append,
    )

    assert client.get_json("portals/self") == {"ok": True}
    assert len(session.calls) == 2
    assert sleeps == [0.0]


def test_client_exposes_no_write_helpers() -> None:
    client = PortalClient("https://demo.maps.arcgis.com")

    assert not hasattr(client, "post")
    assert not hasattr(client, "put")
    assert not hasattr(client, "delete")


def test_normalize_portal_url_rejects_bad_port() -> None:
    from honua_esri_assess.diagnostics import PortalApiError

    with pytest.raises(PortalApiError) as exc_info:
        normalize_portal_url("https://demo.maps.arcgis.com:bad/sharing/rest")
    assert exc_info.value.code == "portal.api"


def test_redact_url_handles_bad_port_without_raising() -> None:
    redacted = redact_url(
        "https://demo.maps.arcgis.com:bad/path?token=secret"
    )
    # No exception, and the credential is still redacted.
    assert "secret" not in redacted
    assert "token=%5BREDACTED%5D" in redacted


def test_get_json_translates_url_value_error_to_portal_connection_error() -> None:
    class _ExplodingSession:
        headers: dict[str, str] = {}

        def get(self, *_args: Any, **_kwargs: Any) -> Any:  # noqa: ANN401
            raise ValueError("invalid port")

    from honua_esri_assess.diagnostics import PortalConnectionError

    client = PortalClient(
        "https://demo.maps.arcgis.com",
        session=_ExplodingSession(),  # type: ignore[arg-type]
    )
    with pytest.raises(PortalConnectionError):
        client.get_json("portals/self")
