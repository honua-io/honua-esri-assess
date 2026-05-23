"""Smoke test for the ArcGIS Server diagnostics fixture (200 + error envelope)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from honua_esri_assess.cli import main as cli_main
from honua_esri_assess.diagnostics import DIAGNOSTIC_CODES

TRACEBACK_RE = re.compile(r"Traceback \(most recent call")
ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_/])(/home/|/Users/|C:\\)")


def test_server_diagnostics_scan(
    mocked_routes,
    schema_validator,
    expected_counts,
    tmp_output_dir: Path,
    capsys,
) -> None:
    output = tmp_output_dir / "EsriFootprint.json"
    with mocked_routes("arcgis-server/diagnostics"):
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

    captured = capsys.readouterr()
    assert exit_code == 0, "partial scans should still exit cleanly"
    assert output.exists()

    footprint = json.loads(output.read_text(encoding="utf-8"))
    schema_validator.validate(footprint)

    expected = expected_counts["arcgis-server-diagnostics-counts"]
    assert footprint["counts"] == {
        "items": expected["items"],
        "layers": expected["layers"],
        "featureClasses": expected["featureClasses"],
    }
    assert footprint["server"]["serviceCounts"] == expected["serviceCounts"]
    assert footprint["server"]["folders"] == expected["folders"]
    assert footprint["server"]["version"] == "11.1"
    assert footprint["inventory"] == []

    codes = [d["code"] for d in footprint["diagnostics"]]
    assert codes, "expected at least one diagnostic from the 200+envelope probes"
    assert {"missing-permission", "rate-limited"} <= set(codes), (
        f"expected envelope-derived diagnostics, got {codes!r}"
    )
    assert set(codes) <= DIAGNOSTIC_CODES

    stderr_text = captured.err
    assert stderr_text.strip(), "expected typed diagnostics to be surfaced on stderr"
    for line in stderr_text.splitlines():
        assert not TRACEBACK_RE.search(line), f"stderr leaked a traceback: {line!r}"
        assert not ABSOLUTE_PATH_RE.search(line), f"stderr leaked a filesystem path: {line!r}"
        assert "token=" not in line
        assert "password=" not in line
        assert "Authorization:" not in line
