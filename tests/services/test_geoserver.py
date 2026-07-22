from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests
from typer.testing import CliRunner

from honua_migrate.services.geoserver import (
    HonuaMigrationClient,
    MigrationError,
    _load_completed_plan,
    geoserver_app,
    redact_artifact,
    resolve_secret_reference,
    write_artifact,
)

runner = CliRunner()


def _completed_job(job_id: str = "job-1") -> dict[str, Any]:
    return {
        "jobId": job_id,
        "status": "completed",
        "completedAt": "2026-07-22T20:00:00Z",
        "geoServerUrl": "https://geoserver.test/rest",
        "progress": {
            "resourcesProcessed": 4,
            "estimatedTotalResources": 4,
            "failedResources": 0,
            "resourceBreakdown": {"layersProcessed": 2},
            "applyPlan": {"steps": []},
        },
    }


def _plan_payload(*, status: str = "completed") -> dict[str, Any]:
    return {
        "schemaVersion": "honua-migrate/geoserver-plan/v1",
        "kind": "geoserver-plan",
        "request": {
            "geoServerRestUrl": "https://geoserver.test/rest",
            "dryRun": True,
            "applyMode": False,
            "requestTimeoutSeconds": 120,
            "maxRetries": 3,
        },
        "dryRunJob": {
            "jobId": "job-1",
            "status": status,
            "completedAt": "2026-07-22T20:00:00Z",
        },
        "result": {"failedResources": 0},
    }


def _write_plan(path: Path, payload: dict[str, Any] | None = None) -> None:
    path.write_text(json.dumps(payload or _plan_payload()), encoding="utf-8")


def test_secret_reference_is_env_only_and_never_echoed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEOSERVER_PASSWORD", "very-secret")
    assert resolve_secret_reference("env:GEOSERVER_PASSWORD") == "very-secret"
    with pytest.raises(MigrationError):
        resolve_secret_reference("very-secret")
    assert redact_artifact(
        {
            "password": "very-secret",
            "passwordSecretReference": "env:PASS",
            "url": "https://a:b@example.test/x?token=no",
        }
    ) == {
        "url": "https://example.test/x",
    }


def test_scan_uses_discover_endpoint_and_transient_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HONUA_KEY", "key")
    monkeypatch.setenv("GEOSERVER_PASSWORD", "password")
    calls: list[tuple[str, str, dict[str, object]]] = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "sourceUrl": (
                    "https://user:password@example.test/rest?token=x"
                )
            }

    def fake_request(method: str, url: str, **kwargs: object) -> Response:
        calls.append((method, url, kwargs["json"]))  # type: ignore[arg-type]
        return Response()

    monkeypatch.setattr(
        "honua_migrate.services.geoserver.requests.request", fake_request
    )
    client = HonuaMigrationClient(
        "https://honua.test", "env:HONUA_KEY", retries=0
    )
    assert client.scan(
        "https://example.test/rest",
        "admin",
        "env:GEOSERVER_PASSWORD",
        include_styles=True,
    )
    assert calls == [
        (
            "POST",
            "https://honua.test/api/v1/admin/import/geoserver/discover",
            {
                "geoServerRestUrl": "https://example.test/rest",
                "includeStyleContent": True,
                "username": "admin",
                "password": "password",
            },
        )
    ]


def test_apply_acknowledgement_precedes_secret_resolution(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan)
    result = runner.invoke(
        geoserver_app,
        [
            "apply",
            "--honua-url",
            "https://honua.test",
            "--honua-api-key-ref",
            "env:MISSING_KEY",
            "--geoserver-password-ref",
            "env:SERVER_SIDE_PASSWORD",
            "--plan",
            str(plan),
        ],
    )
    assert result.exit_code == 2
    assert "acknowledge-apply" in result.output
    assert "not available" not in result.output


def test_cancel_acknowledgement_precedes_secret_resolution() -> None:
    result = runner.invoke(
        geoserver_app,
        [
            "cancel",
            "--honua-url",
            "https://honua.test",
            "--honua-api-key-ref",
            "env:MISSING_KEY",
            "job-1",
        ],
    )
    assert result.exit_code == 2
    assert "acknowledge-cancel" in result.output
    assert "not available" not in result.output


def test_plan_polls_to_completion_and_omits_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "plan.json"

    class Client:
        def start(self, request: dict[str, Any]) -> dict[str, str]:
            assert request["passwordSecretReference"] == "vault:source/password"
            return {"jobId": "job-1"}

        def wait_for_completed(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return _completed_job()

    monkeypatch.setattr(
        "honua_migrate.services.geoserver._client",
        lambda *args, **kwargs: Client(),
    )
    result = runner.invoke(
        geoserver_app,
        [
            "plan",
            "--honua-url",
            "https://honua.test",
            "--honua-api-key-ref",
            "env:KEY",
            "--geoserver-url",
            "https://geoserver.test/rest",
            "--geoserver-password-ref",
            "vault:source/password",
            "--output",
            str(output),
            "--poll-interval",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(artifact).lower()
    assert "password" not in serialized
    assert "secret" not in serialized
    assert artifact["dryRunJob"]["status"] == "completed"
    assert artifact["dryRunJob"]["jobId"] == "job-1"
    assert artifact["result"]["failedResources"] == 0


@pytest.mark.parametrize("status", ["queued", "processing", "failed"])
def test_apply_rejects_noncompleted_plan_before_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan, _plan_payload(status=status))
    called = False

    def fail_client(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "honua_migrate.services.geoserver._client", fail_client
    )
    result = runner.invoke(
        geoserver_app,
        [
            "apply",
            "--acknowledge-apply",
            "--honua-url",
            "https://honua.test",
            "--honua-api-key-ref",
            "env:MISSING_KEY",
            "--geoserver-password-ref",
            "env:SOURCE_PASSWORD",
            "--plan",
            str(plan),
        ],
    )
    assert result.exit_code != 0
    assert called is False


def test_apply_rejects_incomplete_and_credential_bearing_plans(
    tmp_path: Path,
) -> None:
    for index, payload in enumerate(
        [
            {"kind": "geoserver-plan"},
            {
                **_plan_payload(),
                "passwordSecretReference": "env:SHOULD_NOT_PERSIST",
            },
        ]
    ):
        plan = tmp_path / f"plan-{index}.json"
        _write_plan(plan, payload)
        with pytest.raises(MigrationError):
            _load_completed_plan(plan)


def test_apply_revalidates_plan_job_and_rejects_forgery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan)

    class Client:
        started = False

        def status(self, job_id: str) -> dict[str, Any]:
            job = _completed_job(job_id)
            job["completedAt"] = "2026-07-22T21:00:00Z"
            return job

        def start(self, request: dict[str, Any]) -> dict[str, str]:
            self.started = True
            return {"jobId": "apply-1"}

    client = Client()
    monkeypatch.setattr(
        "honua_migrate.services.geoserver._client",
        lambda *args, **kwargs: client,
    )
    result = runner.invoke(
        geoserver_app,
        [
            "apply",
            "--acknowledge-apply",
            "--honua-url",
            "https://honua.test",
            "--honua-api-key-ref",
            "env:KEY",
            "--geoserver-password-ref",
            "env:SOURCE_PASSWORD",
            "--plan",
            str(plan),
        ],
    )
    assert result.exit_code != 0
    assert client.started is False


def test_apply_requires_password_reference_at_apply_time(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan)
    result = runner.invoke(
        geoserver_app,
        [
            "apply",
            "--acknowledge-apply",
            "--honua-url",
            "https://honua.test",
            "--honua-api-key-ref",
            "env:KEY",
            "--plan",
            str(plan),
        ],
    )
    assert result.exit_code == 2
    assert "geoserver-password-ref" in result.output


def test_artifact_refuses_overwrite_and_redacts_references(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifact.json"
    output.write_text("original", encoding="utf-8")
    with pytest.raises(MigrationError, match="already exists"):
        write_artifact(
            {"passwordSecretReference": "env:PASS"},
            output,
            force=False,
        )
    assert output.read_text(encoding="utf-8") == "original"
    write_artifact(
        {"passwordSecretReference": "env:PASS"}, output, force=True
    )
    assert json.loads(output.read_text(encoding="utf-8")) == {}


def test_plan_refuses_existing_output_before_starting_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "plan.json"
    output.write_text("keep", encoding="utf-8")
    called = False

    def fail_client(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "honua_migrate.services.geoserver._client", fail_client
    )
    result = runner.invoke(
        geoserver_app,
        [
            "plan",
            "--honua-url",
            "https://honua.test",
            "--honua-api-key-ref",
            "env:KEY",
            "--geoserver-url",
            "https://geoserver.test/rest",
            "--geoserver-password-ref",
            "env:SOURCE_PASSWORD",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code != 0
    assert called is False
    assert output.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("status", ["failed", "cancelled", "mystery"])
def test_plan_wait_rejects_unsuccessful_or_unknown_terminal_state(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    monkeypatch.setenv("HONUA_KEY", "key")
    client = HonuaMigrationClient(
        "https://honua.test", "env:HONUA_KEY", retries=0
    )
    monkeypatch.setattr(
        client,
        "status",
        lambda job_id: {"jobId": job_id, "status": status},
    )
    with pytest.raises(MigrationError):
        client.wait_for_completed(
            "job-1", wait_timeout=1, poll_interval=0
        )


def test_client_rejects_unsafe_urls_and_job_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HONUA_KEY", "key")
    with pytest.raises(MigrationError):
        HonuaMigrationClient("https://key@honua.test", "env:HONUA_KEY")
    client = HonuaMigrationClient(
        "https://honua.test/base", "env:HONUA_KEY"
    )
    with pytest.raises(MigrationError):
        client.status("../other-job")


def test_raw_server_error_body_is_never_leaked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HONUA_KEY", "key")

    class Response:
        ok = False
        status_code = 500
        text = "password=raw-server-secret"

    monkeypatch.setattr(
        "honua_migrate.services.geoserver.requests.request",
        lambda *args, **kwargs: Response(),
    )
    client = HonuaMigrationClient(
        "https://honua.test", "env:HONUA_KEY", retries=3
    )
    with pytest.raises(MigrationError) as caught:
        client.request("POST", "/start", body={})
    assert "raw-server-secret" not in str(caught.value)
    assert "password" not in str(caught.value).lower()


def test_mutating_post_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_KEY", "key")
    calls = 0

    def fail(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        raise requests.ConnectionError("password=server-secret")

    monkeypatch.setattr(
        "honua_migrate.services.geoserver.requests.request", fail
    )
    client = HonuaMigrationClient(
        "https://honua.test", "env:HONUA_KEY", retries=3
    )
    with pytest.raises(MigrationError) as caught:
        client.request("POST", "/start", body={})
    assert calls == 1
    assert "server-secret" not in str(caught.value)


def test_resume_command_is_not_advertised() -> None:
    result = runner.invoke(geoserver_app, ["--help"])
    assert result.exit_code == 0
    assert "resume" not in result.output
