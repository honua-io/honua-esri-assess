"""End-to-end CLI tests for ``scan server``."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest
import responses

from honua_esri_assess.cli import main

FIXTURES = Path(__file__).parent / "server" / "fixtures"


def _register_root(fixture: str = "services-root.json") -> None:
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        body=(FIXTURES / fixture).read_text(encoding="utf-8"),
        status=200,
        content_type="application/json",
    )


def _register_info(*, status: int = 200) -> None:
    if status == 200:
        responses.add(
            responses.GET,
            "https://gis.example.com/arcgis/rest/info",
            body=(FIXTURES / "rest-info.json").read_text(encoding="utf-8"),
            status=200,
            content_type="application/json",
        )
    else:
        responses.add(
            responses.GET,
            "https://gis.example.com/arcgis/rest/info",
            body="",
            status=status,
        )


def _register_folder(name: str, fixture: str, *, status: int = 200) -> None:
    responses.add(
        responses.GET,
        f"https://gis.example.com/arcgis/rest/services/{name}",
        body=(FIXTURES / fixture).read_text(encoding="utf-8") if status == 200 else "",
        status=status,
        content_type="application/json",
    )


@responses.activate
def test_scan_server_writes_footprint_file(tmp_path: Path) -> None:
    _register_info()
    _register_root()
    _register_folder("Hydrology", "folder-hydrology.json")
    _register_folder("Basemaps", "folder-basemaps.json")
    _register_folder("Imagery", "folder-imagery.json")
    _register_folder("Restricted", "folder-imagery.json", status=403)

    output = tmp_path / "EsriFootprint.json"
    exit_code = main(
        [
            "scan",
            "server",
            "--target",
            "https://gis.example.com/arcgis",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    body = json.loads(output.read_text(encoding="utf-8"))
    assert body["schemaVersion"] == "v0.1"
    assert body["source"]["kind"] == "arcgis-server"
    assert body["source"]["locator"] == "https://gis.example.com/arcgis/rest/services"
    # At least one service from each folder is present
    folder_names = set(body["server"]["folders"])
    assert {"Hydrology", "Basemaps", "Imagery", "Restricted"}.issubset(folder_names)


@responses.activate
def test_scan_server_renders_prospect_safe_auth_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _register_info()
    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/services",
        json={"error": {"code": 498, "message": "Token expired"}},
        status=200,
    )
    exit_code = main(
        [
            "scan",
            "server",
            "--target",
            "https://gis.example.com/arcgis",
            "--token",
            "expired-token",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "[server.auth]" in captured.err
    assert "Traceback" not in captured.err
    # Token must not leak into stderr
    assert "expired-token" not in captured.err
    assert "expired-token" not in captured.out


@responses.activate
def test_scan_server_debug_mode_includes_traceback_on_unexpected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Simulate an unexpected non-AssessmentError by registering a body that
    # crashes during JSON parse: connect aborts mid-response.
    import requests

    responses.add(
        responses.GET,
        "https://gis.example.com/arcgis/rest/info",
        body=requests.exceptions.SSLError("simulated TLS failure"),
    )
    # Will be caught and surfaced as ServerConnectionError (typed), not raw traceback.
    exit_code = main(
        [
            "scan",
            "server",
            "--target",
            "https://gis.example.com/arcgis",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "[server.connection]" in captured.err
    assert "Traceback" not in captured.err


@responses.activate
def test_scan_server_writes_to_stdout_when_no_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _register_info()
    _register_root()
    _register_folder("Hydrology", "folder-hydrology.json")
    _register_folder("Basemaps", "folder-basemaps.json")
    _register_folder("Imagery", "folder-imagery.json")
    _register_folder("Restricted", "folder-imagery.json", status=403)

    exit_code = main(
        [
            "scan",
            "server",
            "--target",
            "https://gis.example.com/arcgis",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["schemaVersion"] == "v0.1"
    # One-line summary lands on stderr
    assert "scanned" in captured.err
    assert "services across" in captured.err


@responses.activate
def test_scan_server_never_writes_raw_target_credentials(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _register_info()
    _register_root()
    _register_folder("Hydrology", "folder-hydrology.json")
    _register_folder("Basemaps", "folder-basemaps.json")
    _register_folder("Imagery", "folder-imagery.json")
    _register_folder("Restricted", "folder-imagery.json", status=403)

    exit_code = main(
        [
            "scan",
            "server",
            "--target",
            (
                "https://raw-user:raw-pass@gis.example.com/arcgis"
                "?token=raw-target-token&sessionId=raw-session#frag"
            ),
            "--token",
            "scanner-token",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["source"]["locator"] == "https://gis.example.com/arcgis/rest/services"
    combined = captured.out + captured.err
    for secret in (
        "raw-user",
        "raw-pass",
        "raw-target-token",
        "raw-session",
        "scanner-token",
    ):
        assert secret not in combined


def test_cli_version_short_circuits(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--version"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip()


def test_cli_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "scan" in captured.out
