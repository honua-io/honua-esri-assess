"""Smoke test for the `scan filegdb-workspace` CLI command.

The pyogrio/GDAL workspace scanner is wired through the CLI here. The smoke
environment does not install the optional ``filegdb`` extra, so this run
exercises the dependency-unavailable path: the command must still exit 0 and
write a schema-valid EsriFootprint.json whose ``diagnostics[]`` explains the
missing backend. When pyogrio is installed the same assertions hold because the
fixture directory is not a real ``.gdb``, which is surfaced as a diagnostic
rather than an error exit.
"""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.cli import main as cli_main

FIXTURE_GDB = Path(__file__).parent / "fixtures" / "filegdb" / "happy" / "sample.gdb"


def test_filegdb_workspace_scan_writes_schema_valid_artifact(
    schema_validator,
    tmp_output_dir: Path,
) -> None:
    output = tmp_output_dir / "EsriFootprint.json"
    exit_code = cli_main(
        [
            "scan",
            "filegdb-workspace",
            "--target",
            str(FIXTURE_GDB),
            "--output",
            str(output),
            "--validate",
        ]
    )
    assert exit_code == 0
    assert output.exists()

    footprint = json.loads(output.read_text(encoding="utf-8"))
    schema_validator.validate(footprint)

    assert footprint["source"]["kind"] == "filegdb"
    assert footprint["filegdb"]["pathHash"].startswith("sha256:")
    # Without the optional backend the inventory is empty and the reason is a
    # typed, prospect-safe diagnostic rather than a raised error.
    assert isinstance(footprint["diagnostics"], list)
    assert footprint["diagnostics"], "expected a diagnostic explaining coverage"
    for diagnostic in footprint["diagnostics"]:
        assert "code" in diagnostic
        assert "Traceback" not in json.dumps(diagnostic)
