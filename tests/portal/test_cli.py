from __future__ import annotations

import json
from typing import Any, Callable

import responses

from honua_esri_assess.cli import main


@responses.activate
def test_scan_agol_writes_footprint_file(
    tmp_path: Any,
    capsys: Any,
    happy_path_responses: Callable[..., None],
) -> None:
    happy_path_responses(responses, include_users=False, include_service=False)
    output = tmp_path / "EsriFootprint.json"

    exit_code = main(
        [
            "scan",
            "agol",
            "--target",
            "https://demo.maps.arcgis.com",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    footprint = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert footprint["schemaVersion"] == "v0.1"
    assert footprint["source"]["kind"] == "arcgis-online"
    assert len(footprint["inventory"]) == 3
    assert "scanned 3 item(s)" in captured.err


@responses.activate
def test_scan_agol_auth_error_is_prospect_safe(
    fixture_json: Callable[[str], dict[str, Any]],
    capsys: Any,
    monkeypatch: Any,
) -> None:
    responses.add(
        responses.GET,
        "https://demo.maps.arcgis.com/sharing/rest/portals/self",
        json=fixture_json("expired_token.json"),
        status=200,
    )
    monkeypatch.setenv("ESRI_TOKEN", "secret-token")

    exit_code = main(
        [
            "scan",
            "agol",
            "--target",
            "https://demo.maps.arcgis.com",
            "--token-env",
            "ESRI_TOKEN",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 21
    assert "error[portal.auth]" in captured.err
    assert "Traceback" not in captured.err
    assert "secret-token" not in captured.err
    assert not captured.out


def test_scan_agol_rejects_zero_timeout(capsys: Any) -> None:
    exit_code = main(
        [
            "scan",
            "agol",
            "--target",
            "https://demo.maps.arcgis.com",
            "--timeout",
            "0",
        ]
    )
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "timeout must be greater than 0" in err


def test_scan_agol_rejects_negative_timeout(capsys: Any) -> None:
    exit_code = main(
        [
            "scan",
            "agol",
            "--target",
            "https://demo.maps.arcgis.com",
            "--timeout",
            "-1.5",
        ]
    )
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "timeout must be greater than 0" in err


def test_scan_agol_typed_error_on_bad_port(capsys: Any) -> None:
    exit_code = main(
        [
            "scan",
            "agol",
            "--target",
            "https://demo.maps.arcgis.com:bad/sharing/rest",
        ]
    )
    captured = capsys.readouterr()
    # Portal API errors exit with the typed PortalApiError code (26).
    assert exit_code == 26
    assert "error[portal.api]" in captured.err
    assert "Traceback" not in captured.err
