"""Smoke test for the FileGDB happy-path scan."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.cli import main as cli_main

FIXTURE_GDB = Path(__file__).parent / "fixtures" / "filegdb" / "happy" / "sample.gdb"


def test_filegdb_happy_scan(
    schema_validator,
    expected_counts,
    tmp_output_dir: Path,
) -> None:
    output = tmp_output_dir / "EsriFootprint.json"
    exit_code = cli_main(
        [
            "scan",
            "filegdb",
            "--target",
            str(FIXTURE_GDB),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert output.exists()

    footprint = json.loads(output.read_text(encoding="utf-8"))
    schema_validator.validate(footprint)

    assert footprint["source"]["kind"] == "filegdb"

    expected = expected_counts["filegdb-happy-counts"]
    assert footprint["counts"] == {"total": expected["total"], "byKind": expected["byKind"]}
    assert footprint["filegdb"]["featureClassCount"] == expected["featureClassCount"]
    assert footprint["filegdb"]["path"] == "sample.gdb"

    for record in footprint["inventory"]:
        assert record["kind"] == "feature-class"
        assert "name" in record
