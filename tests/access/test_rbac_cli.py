"""Fixture-backed CLI coverage for the ``scan rbac`` subcommand."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from honua_esri_assess.app import cli_app
from honua_esri_assess.commands.scan_handlers import HANDLERS
from honua_esri_assess.commands.scan_handlers import rbac as rbac_handler

from .conftest import StubHttpClient, respond, respond_fixture

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def visible(output: str) -> str:
    return ANSI_ESCAPE.sub("", output)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def restore_handlers() -> Iterator[None]:
    original = dict(HANDLERS)
    try:
        yield
    finally:
        HANDLERS.clear()
        HANDLERS.update(original)


def _portal_handlers() -> dict[str, object]:
    return {
        "portals/self/users": respond_fixture("portal_users.json"),
        "portals/self/roles": respond_fixture("portal_roles.json"),
        "portals/self": respond_fixture("portal_self.json"),
        "community/groups": respond_fixture("portal_groups.json"),
    }


def _server_handlers() -> dict[str, object]:
    return {
        "security/roles/getRoles": respond_fixture("server_roles.json"),
        "security/users/getUsers": respond_fixture("server_users.json"),
        "services/Parcels.MapServer/permissions": respond_fixture("server_perms_parcels.json"),
        "services/Hosted/Wells.FeatureServer/permissions": respond_fixture("server_perms_wells.json"),
        "services/Utilities/PrintingTools.GPServer/permissions": respond_fixture(
            "server_perms_printing.json"
        ),
        "services/Hosted": respond_fixture("server_services_hosted.json"),
        "services/Utilities": respond_fixture("server_services_utilities.json"),
        "services": respond_fixture("server_services_root.json"),
    }


def _stub_client(monkeypatch: pytest.MonkeyPatch, handlers: dict[str, object]) -> StubHttpClient:
    captured: dict[str, object] = {}
    stub = StubHttpClient(handlers=handlers)  # type: ignore[arg-type]

    def fake_client(*, token: object, user_agent: object, default_timeout: object) -> StubHttpClient:
        captured["token"] = token
        captured["user_agent"] = user_agent
        captured["default_timeout"] = default_timeout
        return stub

    monkeypatch.setattr(rbac_handler, "RequestsHttpClient", fake_client)
    stub.captured = captured  # type: ignore[attr-defined]
    return stub


def test_scan_help_lists_rbac_backend(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["scan", "--help"], env={"COLUMNS": "160"})
    assert result.exit_code == 0
    assert "rbac" in visible(result.output)


def test_rbac_help_exposes_token_env_not_plaintext_token(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["scan", "rbac", "--help"], env={"COLUMNS": "160"})
    output = visible(result.output)
    assert result.exit_code == 0
    for option in ("--target", "--output", "--token-env", "--kind", "--validate"):
        assert option in output
    assert "--token " not in output


def test_rbac_does_not_accept_plaintext_token_flag(runner: CliRunner) -> None:
    result = runner.invoke(
        cli_app,
        ["scan", "rbac", "--target", "https://example.maps.arcgis.com", "--token", "secret"],
    )
    assert result.exit_code == 2
    assert "No such option" in result.output


def test_rbac_portal_writes_access_footprint_to_file(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _stub_client(monkeypatch, _portal_handlers())
    output = tmp_path / "EsriAccessFootprint.json"

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "rbac",
            "--target",
            "https://demo.maps.arcgis.com/sharing/rest",
            "--output",
            str(output),
            "--validate",
        ],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["schemaVersion"] == "v0.2"
    assert artifact["source"]["kind"] == "arcgis-online"
    assert {u["username"] for u in artifact["users"]} == {"alice", "bob"}
    # Portal is the default --kind, so portal endpoints were queried.
    assert any("portals/self" in url for url in stub.seen)


def test_rbac_writes_to_stdout_by_default(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_client(monkeypatch, _portal_handlers())

    result = runner.invoke(
        cli_app,
        ["scan", "rbac", "--target", "https://demo.maps.arcgis.com/sharing/rest"],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(result.stdout)
    assert artifact["schemaVersion"] == "v0.2"
    assert artifact["source"]["kind"] == "arcgis-online"


def test_rbac_server_kind_reads_admin_security(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _stub_client(monkeypatch, _server_handlers())
    output = tmp_path / "EsriAccessFootprint.json"

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "rbac",
            "--kind",
            "server",
            "--target",
            "https://host.local/arcgis/admin",
            "--output",
            str(output),
            "--validate",
        ],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["source"]["kind"] == "arcgis-server"
    # Server scan reads only the documented admin security + services endpoints.
    assert all(("security/" in url or "/services" in url) for url in stub.seen)
    # ACE crawl produced per-service permissions and resolved effective grants.
    assert artifact["servicePermissions"], "expected crawled per-service ACEs"
    assert artifact["effectivePermissions"], "expected resolved effective grants"


def test_rbac_token_from_env_never_reaches_artifact_or_logs(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _stub_client(monkeypatch, _portal_handlers())
    output = tmp_path / "EsriAccessFootprint.json"
    secret = "super-secret-rbac-token"

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "rbac",
            "--target",
            "https://demo.maps.arcgis.com/sharing/rest",
            "--token-env",
            "RBAC_TOKEN",
            "--output",
            str(output),
        ],
        env={"RBAC_TOKEN": secret},
    )

    assert result.exit_code == 0, result.output
    # Token reaches the HTTP client (so live calls authenticate) ...
    assert stub.captured["token"] == secret  # type: ignore[attr-defined]
    # ... but never the artifact, and only the env-var name appears in logs.
    combined = result.output + (result.stderr or "")
    assert secret not in combined
    assert "RBAC_TOKEN" in combined
    assert secret not in output.read_text(encoding="utf-8")


def test_rbac_partial_coverage_still_writes_valid_artifact(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers = {
        "portals/self/users": respond(403, {"error": {"code": 403}}),
        "portals/self/roles": respond(200, {"roles": []}),
        "portals/self": respond_fixture("portal_self.json"),
        "community/groups": respond(200, {"results": []}),
    }
    _stub_client(monkeypatch, handlers)  # type: ignore[arg-type]
    output = tmp_path / "EsriAccessFootprint.json"

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "rbac",
            "--target",
            "https://demo.maps.arcgis.com/sharing/rest",
            "--output",
            str(output),
            "--validate",
        ],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["users"] == []
    assert any(d["code"] == "missing-permission" for d in artifact["diagnostics"])
