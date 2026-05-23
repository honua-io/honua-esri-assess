"""Credential redaction unit tests."""

from honua_esri_assess.server._safe import redact_params, safe_url


def test_redact_params_masks_credential_keys() -> None:
    masked = redact_params({"f": "json", "token": "abc", "password": "p", "key": "k"})
    assert masked == {"f": "json", "token": "***", "password": "***", "key": "***"}


def test_redact_params_is_case_insensitive() -> None:
    masked = redact_params({"Token": "abc", "API_KEY": "secret"})
    assert masked["Token"] == "***"
    assert masked["API_KEY"] == "***"


def test_safe_url_strips_token_query() -> None:
    url = "https://gis.example.com/arcgis/rest/services?token=secret&f=json"
    assert safe_url(url) == "https://gis.example.com/arcgis/rest/services?token=%2A%2A%2A&f=json"


def test_safe_url_passthrough_when_no_query() -> None:
    url = "https://gis.example.com/arcgis/rest/services"
    assert safe_url(url) == url
