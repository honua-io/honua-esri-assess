"""CLI framework tests."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import responses
from typer.testing import CliRunner

from honua_esri_assess.app import cli_app
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.commands.scan_handlers import HANDLERS, ScanHandler, register
from honua_esri_assess.commands.scan_handlers import agol as agol_handler
from honua_esri_assess.commands.scan_handlers import server as server_handler
from honua_esri_assess.diagnostics import DiagnosticError
from honua_esri_assess.portal.models import OrgInfo, PortalScanResult
from honua_esri_assess.server.models import ServerInfo, ServerScanResult

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = REPO_ROOT / "tests" / "fixtures" / "esri-footprint-sample.json"
MUTATION_WORDS = re.compile(r"\b(apply|update|mutate|delete|write|upload|push)\b", re.I)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def visible_cli_output(output: str) -> str:
    return ANSI_ESCAPE.sub("", output)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def sample_footprint() -> dict[str, Any]:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def restore_handlers() -> Iterator[None]:
    original = dict(HANDLERS)
    try:
        yield
    finally:
        HANDLERS.clear()
        HANDLERS.update(original)


def test_top_level_help_lists_stable_command_tree(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["--help"], env={"COLUMNS": "160"})
    output = visible_cli_output(result.output)

    assert result.exit_code == 0
    for command in ("scan", "report", "schema", "version"):
        assert command in output


def test_scan_help_lists_backend_slots(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["scan", "--help"], env={"COLUMNS": "160"})
    output = visible_cli_output(result.output)

    assert result.exit_code == 0
    for command in ("agol", "server", "filegdb"):
        assert command in output


@pytest.mark.parametrize("backend", ["agol", "server", "filegdb"])
def test_scan_backend_help_has_common_options_without_mutation_words(
    runner: CliRunner,
    backend: str,
) -> None:
    result = runner.invoke(
        cli_app,
        ["scan", backend, "--help"],
        env={"COLUMNS": "160"},
    )
    output = visible_cli_output(result.output)

    assert result.exit_code == 0
    for option in (
        "--target",
        "--output",
        "--token-env",
        "--log-format",
        "--log-level",
        "--no-network-telemetry-confirm",
        "--user-agent",
        "--max-retries",
        "--timeout",
        "--validate",
    ):
        assert option in output
    assert MUTATION_WORDS.search(output) is None


def test_scan_does_not_accept_plaintext_token_flag(runner: CliRunner) -> None:
    result = runner.invoke(
        cli_app,
        [
            "scan",
            "agol",
            "--target",
            "https://example.maps.arcgis.com",
            "--token",
            "secret",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output


def test_token_env_logs_name_without_value(
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    def run(options: ScanOptions) -> ScanResult:
        del options
        return ScanResult(footprint=json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))

    register(ScanHandler(name="agol", run=run))

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "agol",
            "--target",
            "https://example.maps.arcgis.com",
            "--token-env",
            "AGOL_TOKEN",
            "--output",
            str(tmp_path / "EsriFootprint.json"),
        ],
        env={"AGOL_TOKEN": "super-secret-token"},
    )

    combined_output = result.output + (result.stderr or "")
    assert result.exit_code == 0
    assert "AGOL_TOKEN" in combined_output
    assert "super-secret-token" not in combined_output


@pytest.mark.parametrize("backend", ["agol", "server"])
def test_network_scan_options_reach_builtin_handlers_without_secret_leakage(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    seen: dict[str, Any] = {}

    if backend == "agol":
        class FakePortalClient:
            def __init__(
                self,
                target: str,
                *,
                credential: Any,
                timeout: float,
                retry_policy: Any,
                user_agent: str,
            ) -> None:
                seen["target"] = target
                seen["credential"] = credential
                seen["timeout"] = timeout
                seen["attempts"] = retry_policy.attempts
                seen["user_agent"] = user_agent
                self.auth_mode = credential.auth_mode

        class FakePortalScanner:
            def __init__(self, client: FakePortalClient, *, deep: bool) -> None:
                seen["deep"] = deep
                self._client = client

            def scan(self) -> PortalScanResult:
                return PortalScanResult(
                    org=OrgInfo(
                        id="fixture-org",
                        name="Fixture",
                        portal_url="https://fixture.local",
                        sharing_rest_url="https://fixture.local/sharing/rest",
                    ),
                    auth_mode=self._client.auth_mode,
                    captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )

        monkeypatch.setattr(agol_handler, "PortalClient", FakePortalClient)
        monkeypatch.setattr(agol_handler, "PortalScanner", FakePortalScanner)
    else:
        class FakeServerClient:
            def __init__(
                self,
                target: str,
                *,
                credential: Any,
                timeout: float,
                retry: Any,
                user_agent: str,
            ) -> None:
                seen["target"] = target
                seen["credential"] = credential
                seen["timeout"] = timeout
                seen["attempts"] = retry.max_attempts
                seen["user_agent"] = user_agent
                self.credential = credential
                self.rest_root = "https://fixture.local/server/rest/services"

        class FakeServerScanner:
            def __init__(self, *, deep: bool) -> None:
                seen["deep"] = deep

            def scan(self, client: FakeServerClient) -> ServerScanResult:
                return ServerScanResult(
                    info=ServerInfo(url=client.rest_root, current_version="11.1"),
                    auth_mode=client.credential.auth_mode,
                    deep=True,
                    folders=(),
                    services=(),
                    diagnostics=(),
                )

        monkeypatch.setattr(server_handler, "ServerClient", FakeServerClient)
        monkeypatch.setattr(server_handler, "ServerScanner", FakeServerScanner)
    output = tmp_path / "EsriFootprint.json"

    result = runner.invoke(
        cli_app,
        [
            "scan",
            backend,
            "--target",
            "https://fixture.local/sharing/rest",
            "--token-env",
            "ESRI_TOKEN",
            "--user-agent",
            "honua-test/1.0",
            "--max-retries",
            "1",
            "--timeout",
            "7.5",
            "--output",
            str(output),
        ],
        env={"ESRI_TOKEN": "top-secret-token"},
    )

    assert result.exit_code == 0
    combined_output = result.output + (result.stderr or "")
    footprint_text = output.read_text(encoding="utf-8")
    assert seen["credential"].auth_mode == "token"
    if backend == "agol":
        assert seen["credential"].params()["token"] == "top-secret-token"
        assert seen["deep"] is False
    else:
        assert seen["credential"].apply({})["token"] == "top-secret-token"
        assert seen["deep"] is True
    assert seen["user_agent"] == "honua-test/1.0"
    assert seen["attempts"] == 2
    assert seen["timeout"] == 7.5
    assert "ESRI_TOKEN" in combined_output
    assert "top-secret-token" not in combined_output
    assert "top-secret-token" not in footprint_text


@responses.activate
def test_server_handler_uses_canonical_contract_and_retries_once(
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    output = tmp_path / "EsriFootprint.json"
    responses.add(
        responses.GET,
        "https://fixture.local/server/rest/info",
        json={"currentVersion": 11.1},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://fixture.local/server/rest/services",
        json={},
        status=503,
        headers={"Retry-After": "0"},
    )
    responses.add(
        responses.GET,
        "https://fixture.local/server/rest/services",
        json={"folders": [], "services": []},
        status=200,
    )

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "server",
            "--target",
            "https://fixture.local/server",
            "--token-env",
            "SERVER_TOKEN",
            "--user-agent",
            "honua-test/1.0",
            "--max-retries",
            "1",
            "--output",
            str(output),
        ],
        env={"SERVER_TOKEN": "top-secret-token"},
    )

    assert result.exit_code == 0
    footprint = json.loads(output.read_text(encoding="utf-8"))
    assert footprint["source"]["locator"] == "https://fixture.local/server/rest/services"
    assert footprint["server"]["version"] == "11.1"

    service_calls = [
        call
        for call in responses.calls
        if call.request.url.startswith("https://fixture.local/server/rest/services?")
    ]
    assert len(service_calls) == 2
    assert all("token=top-secret-token" in call.request.url for call in responses.calls)
    assert all(call.request.headers["User-Agent"] == "honua-test/1.0" for call in responses.calls)
    assert "top-secret-token" not in output.read_text(encoding="utf-8")
    assert "top-secret-token" not in result.output + (result.stderr or "")


def test_typed_scanner_error_returns_exit_10_without_traceback(
    runner: CliRunner,
) -> None:
    def run(options: ScanOptions) -> ScanResult:
        del options
        raise DiagnosticError(
            "Authentication failed while reading the target.",
            code="scanner-error",
            scope="agol",
        )

    register(ScanHandler(name="agol", run=run))

    result = runner.invoke(
        cli_app,
        ["scan", "agol", "--target", "https://example.com"],
    )

    combined_output = result.output + (result.stderr or "")
    assert result.exit_code == 10
    assert "error[scanner-error]" in combined_output
    assert "Authentication failed" in combined_output
    assert "Traceback" not in combined_output


def test_version_command_mentions_tool_and_schema_versions(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["version"])

    assert result.exit_code == 0
    assert "honua-esri-assess 0.1.0" in result.output
    assert "EsriFootprint schema v0.1" in result.output


def test_root_version_option_mentions_tool_and_schema_versions(
    runner: CliRunner,
) -> None:
    result = runner.invoke(cli_app, ["--version"])

    assert result.exit_code == 0
    assert "honua-esri-assess 0.1.0" in result.output
    assert "EsriFootprint schema v0.1" in result.output


def test_schema_validate_accepts_canonical_sample(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["schema", "validate", str(SAMPLE_PATH)])

    assert result.exit_code == 0
    assert "valid:" in result.output


def test_registered_handler_success_writes_validated_footprint(
    runner: CliRunner,
    tmp_path: Path,
    sample_footprint: dict[str, Any],
) -> None:
    def run(options: ScanOptions) -> ScanResult:
        assert options.target == "file://tests/fixtures/agol-happy"
        return ScanResult(footprint=deepcopy(sample_footprint))

    register(ScanHandler(name="agol", run=run))
    output = tmp_path / "EsriFootprint.json"

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "agol",
            "--target",
            "file://tests/fixtures/agol-happy",
            "--output",
            str(output),
            "--validate",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schemaVersion"] == "v0.1"


def test_registered_handler_output_failure_returns_exit_20(
    runner: CliRunner,
    tmp_path: Path,
    sample_footprint: dict[str, Any],
) -> None:
    def run(options: ScanOptions) -> ScanResult:
        del options
        return ScanResult(footprint=sample_footprint)

    register(ScanHandler(name="agol", run=run))

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "agol",
            "--target",
            "https://example.maps.arcgis.com",
            "--output",
            str(tmp_path),
        ],
    )

    combined_output = result.output + (result.stderr or "")
    assert result.exit_code == 20
    assert "error[output-write-failed]" in combined_output


def test_registered_handler_validation_failure_returns_exit_30(
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    def run(options: ScanOptions) -> ScanResult:
        del options
        return ScanResult(footprint={"schemaVersion": "v9"})

    register(ScanHandler(name="agol", run=run))

    result = runner.invoke(
        cli_app,
        [
            "scan",
            "agol",
            "--target",
            "https://example.maps.arcgis.com",
            "--output",
            str(tmp_path / "out.json"),
            "--validate",
        ],
    )

    combined_output = result.output + (result.stderr or "")
    assert result.exit_code == 30
    assert "error[schema-validation-failed]" in combined_output


def test_unexpected_handler_error_returns_generic_exit_1(
    runner: CliRunner,
) -> None:
    def run(options: ScanOptions) -> ScanResult:
        del options
        raise RuntimeError("token=super-secret")

    register(ScanHandler(name="agol", run=run))

    result = runner.invoke(
        cli_app,
        ["scan", "agol", "--target", "https://example.com"],
        env={"HONUA_ESRI_ASSESS_CRASH_DUMPS": "0"},
    )

    combined_output = result.output + (result.stderr or "")
    assert result.exit_code == 1
    assert "error[internal-error]" in combined_output
    assert "RuntimeError" not in combined_output
    assert "super-secret" not in combined_output
    assert "Traceback" not in combined_output


def test_crash_dump_redacts_url_credentials_and_session_ids(
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    leaky = (
        "https://alice:superpass@example.com/arcgis;jsessionid=session-secret"
        "?f=json&token=topsecret-token"
    )

    def run(options: ScanOptions) -> ScanResult:
        del options
        raise RuntimeError(f"request failed against {leaky}")

    register(ScanHandler(name="agol", run=run))

    result = runner.invoke(
        cli_app,
        ["scan", "agol", "--target", "https://example.com"],
        env={
            "HOME": str(tmp_path),
            "HONUA_ESRI_ASSESS_CRASH_DUMPS": "1",
        },
    )

    crash_dir = tmp_path / ".cache" / "honua-esri-assess" / "crashes"
    crash_files = list(crash_dir.glob("crash-*.json"))

    assert result.exit_code == 1
    assert len(crash_files) == 1
    crash_text = crash_files[0].read_text(encoding="utf-8")
    for secret in (
        "alice:superpass",
        "superpass",
        "session-secret",
        "topsecret-token",
    ):
        assert secret not in crash_text, f"crash dump leaked {secret!r}"
    assert "<redacted>@example.com" in crash_text
    assert "jsessionid=<redacted>" in crash_text
    assert "token=<redacted>" in crash_text

    combined_output = result.output + (result.stderr or "")
    assert str(crash_files[0]) not in combined_output
    assert str(tmp_path) not in combined_output
    assert "~/.cache/honua-esri-assess/crashes/" in combined_output
    assert crash_files[0].name in combined_output
