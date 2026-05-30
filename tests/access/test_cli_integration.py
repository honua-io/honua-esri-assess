"""CLI integration tests for the --include-access flag."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

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
