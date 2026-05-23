"""End-to-end smoke test for the AGOL happy-path scan."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from honua_esri_assess.cli import main as cli_main
from honua_esri_assess.diagnostics import DIAGNOSTIC_CODES

UNSAFE_DIAGNOSTIC_PATTERNS = (
    re.compile(r"Traceback \(most recent call"),
    re.compile(r"token="),
    re.compile(r"password="),
    re.compile(r"Authorization:"),
)


def _assert_diagnostic_is_prospect_safe(message: str) -> None:
    for pattern in UNSAFE_DIAGNOSTIC_PATTERNS:
        assert not pattern.search(message), f"Diagnostic message leaked sensitive content: {message!r}"


def test_agol_happy_scan(
    mocked_routes,
    schema_validator,
    expected_counts,
    tmp_output_dir: Path,
    capsys,
) -> None:
    output = tmp_output_dir / "EsriFootprint.json"
    with mocked_routes("agol/happy"):
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

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert output.exists(), "scan did not write EsriFootprint.json"

    footprint = json.loads(output.read_text(encoding="utf-8"))
    schema_validator.validate(footprint)

    assert footprint["schemaVersion"] == "0.1.0"
    assert footprint["producer"]["name"] == "honua-esri-assess"
    assert footprint["source"]["kind"] == "agol"
    assert footprint["source"]["portalName"] == "Honua Demo Portal"
    assert footprint["inventory"], "inventory should be non-empty"

    inventory_kinds = {item["kind"] for item in footprint["inventory"]}
    assert inventory_kinds <= {"feature-service", "map-service", "web-map"}

    expected = expected_counts["agol-happy-counts"]
    assert footprint["counts"] == expected, (
        f"counts mismatch: got {footprint['counts']!r}, expected {expected!r}"
    )

    for diag in footprint["diagnostics"]:
        assert diag["code"] in DIAGNOSTIC_CODES
        _assert_diagnostic_is_prospect_safe(diag["message"])

    for line in captured.err.splitlines():
        _assert_diagnostic_is_prospect_safe(line)


def test_agol_console_script_installed() -> None:
    """One subprocess invocation catches packaging regressions of the entry point.

    Prefers the installed ``honua-esri-assess`` console script (the surface
    prospects run from a shell); falls back to ``python -m honua_esri_assess``
    when the entry point has not been linked onto PATH (uninstalled checkouts).
    """

    import shutil

    console_script = shutil.which("honua-esri-assess")
    cmd = (
        [console_script, "--version"]
        if console_script
        else [sys.executable, "-m", "honua_esri_assess", "--version"]
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "expected a version line on stdout"
