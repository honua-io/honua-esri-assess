from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from honua_migrate.services.geoserver import (
    HonuaMigrationClient,
    MigrationError,
    geoserver_app,
    redact_artifact,
    resolve_secret_reference,
    write_artifact,
)


def test_secret_reference_is_env_only_and_never_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOSERVER_PASSWORD", "very-secret")
    assert resolve_secret_reference("env:GEOSERVER_PASSWORD") == "very-secret"
    with pytest.raises(MigrationError):
        resolve_secret_reference("very-secret")
    assert redact_artifact({"password": "very-secret", "url": "https://a:b@example.test/x?token=no"}) == {
        "password": "<redacted>",
        "url": "https://example.test/x",
    }


def test_scan_uses_discover_endpoint_and_transient_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_KEY", "key")
    monkeypatch.setenv("GEOSERVER_PASSWORD", "password")
    calls: list[tuple[str, str, dict[str, object]]] = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"sourceUrl": "https://user:password@example.test/rest?token=x"}

    def fake_request(method: str, url: str, **kwargs: object) -> Response:
        calls.append((method, url, kwargs["json"]))  # type: ignore[arg-type]
        return Response()

    monkeypatch.setattr("honua_migrate.services.geoserver.requests.request", fake_request)
    client = HonuaMigrationClient("https://honua.test", "env:HONUA_KEY", retries=0)
    assert client.scan("https://example.test/rest", "admin", "env:GEOSERVER_PASSWORD", include_styles=True)
    assert calls == [("POST", "https://honua.test/api/v1/admin/import/geoserver/discover", {"geoServerRestUrl": "https://example.test/rest", "includeStyleContent": True, "username": "admin", "password": "password"})]


def test_apply_requires_acknowledgement() -> None:
    result = CliRunner().invoke(
        geoserver_app,
        ["apply", "--honua-url", "https://honua.test", "--honua-api-key-ref", "env:KEY", "--plan", "reviewed-plan.json"],
    )
    assert result.exit_code != 0
    assert "acknowledge-apply" in result.output


def test_artifact_redacts_secrets(tmp_path) -> None:
    output = tmp_path / "artifact.json"
    write_artifact({"nested": {"apiKey": "key"}, "passwordSecretReference": "env:PASS"}, output, force=False)
    payload = json.loads(output.read_text())
    assert payload == {"nested": {"apiKey": "<redacted>"}, "passwordSecretReference": "env:PASS"}


def test_client_rejects_unsafe_urls_and_job_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_KEY", "key")
    with pytest.raises(MigrationError):
        HonuaMigrationClient("https://key@honua.test", "env:HONUA_KEY")
    client = HonuaMigrationClient("https://honua.test/base", "env:HONUA_KEY")
    with pytest.raises(MigrationError):
        client.status("../other-job")


def test_cancel_requires_acknowledgement() -> None:
    result = CliRunner().invoke(
        geoserver_app,
        ["cancel", "--honua-url", "https://honua.test", "--honua-api-key-ref", "env:KEY", "job-1"],
    )
    assert result.exit_code != 0
    assert "acknowledge-cancel" in result.output
