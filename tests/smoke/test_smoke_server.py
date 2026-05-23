"""Smoke test for the ArcGIS Server happy-path scan."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.cli import main as cli_main
from honua_esri_assess.diagnostics import DIAGNOSTIC_CODES


def test_server_happy_scan(
    mocked_routes,
    schema_validator,
    expected_counts,
    tmp_output_dir: Path,
) -> None:
    output = tmp_output_dir / "EsriFootprint.json"
    with mocked_routes("arcgis-server/happy"):
        exit_code = cli_main(
            [
                "scan",
                "server",
                "--target",
                "https://fixture.local/server/rest",
                "--output",
                str(output),
            ]
        )

    assert exit_code == 0
    assert output.exists()

    footprint = json.loads(output.read_text(encoding="utf-8"))
    schema_validator.validate(footprint)

    assert footprint["source"]["kind"] == "arcgis-server"

    expected = expected_counts["arcgis-server-happy-counts"]
    assert footprint["counts"] == {
        "items": expected["items"],
        "layers": expected["layers"],
        "featureClasses": expected["featureClasses"],
    }
    assert footprint["server"]["serviceCounts"] == expected["serviceCounts"]
    assert footprint["server"]["folders"] == expected["folders"]
    assert footprint["server"]["version"] == "11.1"

    for diag in footprint["diagnostics"]:
        assert diag["code"] in DIAGNOSTIC_CODES
