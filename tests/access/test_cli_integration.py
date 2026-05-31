"""CLI integration tests for the --include-access flag."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from honua_esri_assess.cli import main as cli_main
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.commands.scan_handlers import HANDLERS, ScanHandler, register
from honua_esri_assess.footprint import build_footprint


@pytest.fixture(autouse=True)
def restore_handlers() -> Iterator[None]:
    original = dict(HANDLERS)
    try:
        yield
    finally:
        HANDLERS.clear()
        HANDLERS.update(original)


def test_include_access_without_token_env_exits_with_typed_diagnostic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(
        [
            "scan",
            "agol",
            "--target",
            "https://fixture.local/sharing/rest",
            "--output",
            str(tmp_path / "out.json"),
            "--include-access",
        ]
    )
    assert exit_code != 0
    captured = capsys.readouterr()
    assert "access-token-required" in captured.err


def test_include_access_negative_group_cap_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_TOKEN", "x")
    exit_code = cli_main(
        [
            "scan",
            "agol",
            "--target",
            "https://fixture.local/sharing/rest",
            "--output",
            str(tmp_path / "out.json"),
            "--token-env",
            "FAKE_TOKEN",
            "--include-access",
            "--access-group-cap",
            "-1",
        ]
    )
    assert exit_code != 0


def test_handler_receives_include_access_and_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake(options: ScanOptions) -> ScanResult:
        seen["include_access"] = options.include_access
        seen["access_group_cap"] = options.access_group_cap
        seen["token"] = options.token
        return ScanResult(
            footprint=build_footprint(
                source_kind="arcgis-online",
                target=options.target,
                inventory=[],
                diagnostics=[],
                portal={
                    "orgId": "fixture-org",
                    "orgUrl": "https://fixture.local",
                    "itemCounts": {},
                },
            ),
        )

    register(ScanHandler(name="agol", run=fake))
    monkeypatch.setenv("FAKE_TOKEN", "topsecret-token-value")
    output = tmp_path / "EsriFootprint.json"
    exit_code = cli_main(
        [
            "scan",
            "agol",
            "--target",
            "https://fixture.local/sharing/rest",
            "--output",
            str(output),
            "--token-env",
            "FAKE_TOKEN",
            "--include-access",
            "--access-group-cap",
            "50",
        ]
    )
    assert exit_code == 0, output.read_text(encoding="utf-8")
    assert seen["include_access"] is True
    assert seen["access_group_cap"] == 50
    assert seen["token"] == "topsecret-token-value"


def test_embed_access_diagnostics_appends_locked_wire_shape() -> None:
    """Access diagnostics must flow into the artifact's diagnostics[] array."""

    from honua_esri_assess.commands.scan_handlers.agol import (
        _embed_access_diagnostics as _embed_agol,
    )
    from honua_esri_assess.commands.scan_handlers.server import (
        _embed_access_diagnostics as _embed_server,
    )
    from honua_esri_assess.entitlements.diagnostics import Diagnostic as AccessDiagnostic

    diags = (
        AccessDiagnostic(
            code="missing-permission",
            severity="warn",
            message="Token cannot read security policy.",
            scope="portal.access.securityPolicy",
        ),
        AccessDiagnostic(
            code="partial-coverage",
            severity="info",
            message="Group cap hit.",
            scope="portal.access.groups.groupB.users",
            hint="Re-run with --access-group-cap >= 500.",
        ),
    )
    for embed in (_embed_agol, _embed_server):
        footprint: dict[str, object] = {"diagnostics": [{"code": "rate-limited",
                                                          "severity": "info",
                                                          "message": "pre-existing",
                                                          "scope": "arcgis-online"}]}
        embed(footprint, diags)

        codes = [d["code"] for d in footprint["diagnostics"]]
        assert codes == ["rate-limited", "missing-permission", "partial-coverage"]
        # Locked-code wire shape: required keys + optional hint.
        missing = footprint["diagnostics"][1]
        assert set(missing) == {"code", "severity", "message", "scope"}
        capped = footprint["diagnostics"][2]
        assert capped["hint"] == "Re-run with --access-group-cap >= 500."


def test_embed_access_diagnostics_noop_on_empty_diags() -> None:
    from honua_esri_assess.commands.scan_handlers.agol import (
        _embed_access_diagnostics,
    )

    footprint: dict[str, object] = {"diagnostics": []}
    _embed_access_diagnostics(footprint, ())
    assert footprint["diagnostics"] == []


def test_server_access_excludes_services_omitted_from_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-service permission probes must skip services the v0.1 emitter drops."""

    from honua_esri_assess.access.server import ServiceRef
    from honua_esri_assess.commands.scan_handlers import server as server_handler
    from honua_esri_assess.entitlements.diagnostics import (
        Diagnostic as AccessDiagnostic,
    )
    from honua_esri_assess.server.models import (
        ScanDiagnostic,
        ServerInfo,
        ServerScanResult,
        ServiceRecord,
    )

    visible_service = ServiceRecord(
        name="Visible",
        folder="",
        service_type="MapServer",
        kind="mapService",
        url="https://gis.fixture.local/arcgis/rest/services/Visible/MapServer",
    )
    forbidden_service = ServiceRecord(
        name="Forbidden",
        folder="Restricted",
        service_type="FeatureServer",
        kind="featureService",
        url=(
            "https://gis.fixture.local/arcgis/rest/services/Restricted/"
            "Forbidden/FeatureServer"
        ),
    )
    rate_limited_service = ServiceRecord(
        name="Throttled",
        folder="",
        service_type="MapServer",
        kind="mapService",
        url="https://gis.fixture.local/arcgis/rest/services/Throttled/MapServer",
    )
    diagnostics = (
        ScanDiagnostic(
            code="server.service.missing-permission",
            severity="warning",
            message="forbidden",
            field="services/Restricted/Forbidden/FeatureServer",
        ),
        ScanDiagnostic(
            code="server.service.rate-limited",
            severity="warning",
            message="429",
            field="services/_root/Throttled/MapServer",
        ),
    )
    scan_result = ServerScanResult(
        info=ServerInfo(url="https://gis.fixture.local/arcgis/rest/services"),
        auth_mode="token",
        deep=True,
        folders=(),
        services=(visible_service, forbidden_service, rate_limited_service),
        diagnostics=diagnostics,
    )

    captured: dict[str, object] = {}

    class _FakeServerClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class _FakeServerScanner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def scan(self, _client: object) -> ServerScanResult:
            return scan_result

    def _fake_collect_server_access(
        *,
        footprint: dict[str, Any],
        target: str,
        services: list[ServiceRecord],
        token: str,
        user_agent: str,
        timeout: float,
        max_attempts: int,
    ) -> tuple[dict[str, Any], list[object]]:
        captured["services"] = list(services)
        captured["max_attempts"] = max_attempts
        return footprint, []

    monkeypatch.setattr(server_handler, "ServerClient", _FakeServerClient)
    monkeypatch.setattr(server_handler, "ServerScanner", _FakeServerScanner)
    monkeypatch.setattr(
        server_handler, "_collect_server_access", _fake_collect_server_access
    )

    options = ScanOptions(
        target="https://gis.fixture.local/arcgis",
        output=tmp_path / "out.json",
        token_env="FAKE_TOKEN",
        log_format="text",
        log_level="info",
        no_network_telemetry_confirm=False,
        user_agent="ua",
        max_retries=4,
        timeout=10.0,
        validate=False,
        include_access=True,
        access_group_cap=10,
        token="fake-token-value",
    )

    server_handler.run(options)

    services_passed = [
        (s.folder or "", s.name, s.service_type)
        for s in captured["services"]  # type: ignore[union-attr]
    ]
    # Only the visible service survives the omission filter.
    assert services_passed == [("", "Visible", "MapServer")]
    # And --max-retries=4 → max_attempts=5 reaches the access call.
    assert captured["max_attempts"] == 5
    # Suppress the unused-import lint for the typed alias.
    assert AccessDiagnostic is not None
    assert ServiceRef is not None


def test_scan_default_omits_access_block(tmp_path: Path) -> None:
    def fake(options: ScanOptions) -> ScanResult:
        return ScanResult(
            footprint=build_footprint(
                source_kind="arcgis-online",
                target=options.target,
                inventory=[],
                diagnostics=[],
                portal={
                    "orgId": "fixture-org",
                    "orgUrl": "https://fixture.local",
                    "itemCounts": {},
                },
            ),
        )

    register(ScanHandler(name="agol", run=fake))
    output = tmp_path / "EsriFootprint.json"
    exit_code = cli_main(
        [
            "scan",
            "agol",
            "--target",
            "https://fixture.local/sharing/rest",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    footprint = json.loads(output.read_text(encoding="utf-8"))
    assert footprint["schemaVersion"] == "v0.1"
    assert "access" not in footprint.get("portal", {})
