"""HTTP client behavior — base URL canonicalization, retries, error mapping."""

from __future__ import annotations

import logging

import pytest
import responses

from honua_esri_assess.diagnostics import (
    ServerApiError,
    ServerAuthError,
    ServerConnectionError,
    ServerForbiddenError,
    ServerNotFoundError,
    ServerRateLimitedError,
)
from honua_esri_assess.server.auth import AnonymousCredential, TokenCredential
from honua_esri_assess.server.client import (
    RetryPolicy,
    ServerClient,
    normalize_base_url,
)


@pytest.mark.parametrize(
    ("input_url", "expected"),
    [
        ("https://gis.example.com", "https://gis.example.com/arcgis/rest/services"),
        ("https://gis.example.com/", "https://gis.example.com/arcgis/rest/services"),
        ("https://gis.example.com/arcgis", "https://gis.example.com/arcgis/rest/services"),
        ("https://gis.example.com/arcgis/", "https://gis.example.com/arcgis/rest/services"),
        ("https://gis.example.com/arcgis/rest", "https://gis.example.com/arcgis/rest/services"),
        (
            "https://gis.example.com/arcgis/rest/services",
            "https://gis.example.com/arcgis/rest/services",
        ),
        (
            "https://gis.example.com/arcgis/rest/services/",
            "https://gis.example.com/arcgis/rest/services",
        ),
        (
            "https://user:pass@gis.example.com/arcgis?token=secret#frag",
            "https://gis.example.com/arcgis/rest/services",
        ),
    ],
)
def test_normalize_base_url_canonicalizes(input_url: str, expected: str) -> None:
    assert normalize_base_url(input_url) == expected


def test_normalize_base_url_passes_through_when_allowed() -> None:
    custom = "https://user:pass@gis.example.com/custom/mount/point?token=secret#frag"
    expected = "https://gis.example.com/custom/mount/point"
    assert normalize_base_url(custom, allow_nonstandard=True) == expected


def test_normalize_base_url_rejects_unparseable() -> None:
    with pytest.raises(ValueError):
        normalize_base_url("not-a-url")
    with pytest.raises(ValueError):
        normalize_base_url("")


@responses.activate
def test_get_json_appends_token_to_query() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": [], "services": []},
        status=200,
    )
    client = ServerClient("https://gis.example.com/arcgis", credential=TokenCredential("s3cret"))
    client.get_services_root()
    call = responses.calls[0]
    assert "token=s3cret" in call.request.url
    assert "f=json" in call.request.url


@responses.activate
def test_get_json_anonymous_omits_token() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": [], "services": []},
        status=200,
    )
    client = ServerClient("https://gis.example.com/arcgis", credential=AnonymousCredential())
    client.get_services_root()
    assert "token=" not in responses.calls[0].request.url


@responses.activate
def test_get_layer_builds_layer_url() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Hydro/Watersheds/FeatureServer/0",
        json={"id": 0, "name": "Watersheds"},
        status=200,
    )
    client = ServerClient("https://gis.example.com/arcgis")
    body = client.get_layer(
        name="Watersheds",
        service_type="FeatureServer",
        folder="Hydro",
        layer_id=0,
    )
    assert body["name"] == "Watersheds"
    assert responses.calls[0].request.url.startswith(
        "https://gis.example.com/arcgis/rest/services/Hydro/Watersheds/FeatureServer/0"
    )


@responses.activate
def test_get_layer_root_service_omits_folder() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services/Cities/MapServer/2",
        json={"id": 2, "name": "Cities"},
        status=200,
    )
    client = ServerClient("https://gis.example.com/arcgis")
    body = client.get_layer(
        name="Cities",
        service_type="MapServer",
        folder=None,
        layer_id=2,
    )
    assert body["id"] == 2


@responses.activate
def test_http_401_raises_typed_auth_error() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"error": "auth"},
        status=401,
    )
    client = ServerClient("https://gis.example.com/arcgis")
    with pytest.raises(ServerAuthError):
        client.get_services_root()


@responses.activate
def test_http_403_raises_forbidden() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        body="",
        status=403,
    )
    client = ServerClient("https://gis.example.com/arcgis")
    with pytest.raises(ServerForbiddenError):
        client.get_services_root()


@responses.activate
def test_http_404_raises_not_found() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        body="",
        status=404,
    )
    client = ServerClient("https://gis.example.com/arcgis")
    with pytest.raises(ServerNotFoundError):
        client.get_services_root()


@responses.activate
def test_esri_error_envelope_498_raises_auth_error() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"error": {"code": 498, "message": "Invalid token"}},
        status=200,
    )
    client = ServerClient("https://gis.example.com/arcgis")
    with pytest.raises(ServerAuthError):
        client.get_services_root()


@responses.activate
def test_esri_error_envelope_unknown_raises_api_error() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"error": {"code": 5000, "message": "Internal server problem"}},
        status=200,
    )
    client = ServerClient("https://gis.example.com/arcgis")
    with pytest.raises(ServerApiError) as exc_info:
        client.get_services_root()
    assert exc_info.value.esri_code == 5000


@responses.activate
def test_esri_error_message_strips_urls() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={
            "error": {
                "code": 498,
                "message": "Token expired. Refresh at https://gis.example.com/arcgis/tokens",
            }
        },
        status=200,
    )
    client = ServerClient("https://gis.example.com/arcgis")
    with pytest.raises(ServerAuthError) as exc_info:
        client.get_services_root()
    assert "https://" not in exc_info.value.message


@responses.activate
def test_429_with_retry_after_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        body="",
        status=429,
        headers={"Retry-After": "1"},
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": [], "services": []},
        status=200,
    )
    client = ServerClient(
        "https://gis.example.com/arcgis",
        retry=RetryPolicy(max_attempts=3, initial_backoff=0.01),
        sleep=sleeps.append,
    )
    client.get_services_root()
    assert sleeps and sleeps[0] == pytest.approx(1.0)


@responses.activate
def test_429_exhausts_attempts_raises_rate_limited() -> None:
    for _ in range(3):
        responses.add(
            responses.GET,
            "https://gis.example.com/arcgis/rest/services",
            body="",
            status=429,
        )
    client = ServerClient(
        "https://gis.example.com/arcgis",
        retry=RetryPolicy(max_attempts=3, initial_backoff=0.0),
        sleep=lambda _: None,
    )
    with pytest.raises(ServerRateLimitedError):
        client.get_services_root()


@responses.activate
def test_connection_error_raises_connection_diagnostic() -> None:
    import requests

    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        body=requests.exceptions.ConnectTimeout("simulated"),
    )
    client = ServerClient("https://gis.example.com/arcgis")
    with pytest.raises(ServerConnectionError):
        client.get_services_root()


@responses.activate
def test_token_does_not_appear_in_log_records(caplog: pytest.LogCaptureFixture) -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        body="",
        status=429,
        headers={"Retry-After": "0"},
    )
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"folders": [], "services": []},
        status=200,
    )
    client = ServerClient(
        "https://gis.example.com/arcgis",
        credential=TokenCredential("s3cret"),
        retry=RetryPolicy(max_attempts=3, initial_backoff=0.0),
        sleep=lambda _: None,
    )
    with caplog.at_level(logging.DEBUG, logger="honua_esri_assess"):
        client.get_services_root()
    joined = "\n".join(record.getMessage() for record in caplog.records)
    extras = "\n".join(str(record.__dict__) for record in caplog.records)
    assert "s3cret" not in joined
    assert "s3cret" not in extras


def test_client_has_no_write_helpers() -> None:
    forbidden = {"post", "put", "delete", "patch"}
    for name in forbidden:
        assert not hasattr(ServerClient, name), f"ServerClient must not expose {name!r}"


@responses.activate
def test_diagnostic_context_url_is_redacted() -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        body="",
        status=401,
    )
    client = ServerClient(
        "https://gis.example.com/arcgis",
        credential=TokenCredential("s3cret"),
    )
    with pytest.raises(ServerAuthError) as exc_info:
        client.get_services_root()
    ctx_url = exc_info.value.context.get("url", "")
    assert "s3cret" not in ctx_url
