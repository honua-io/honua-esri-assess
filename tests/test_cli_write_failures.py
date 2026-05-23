"""CLI tests for prospect-safe handling of output-write failures."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from honua_esri_assess.cli import main as cli_main
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.commands.scan_handlers import HANDLERS, ScanHandler, register

TRACEBACK_RE = re.compile(r"Traceback \(most recent call")
ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_/])(/home/|/Users/|C:\\)")


def _assert_prospect_safe(stderr: str) -> None:
    assert stderr.strip(), "expected a typed diagnostic line on stderr"
    for line in stderr.splitlines():
        assert not TRACEBACK_RE.search(line), f"stderr leaked a traceback: {line!r}"
        assert not ABSOLUTE_PATH_RE.search(line), f"stderr leaked a filesystem path: {line!r}"
        assert "token=" not in line
        assert "password=" not in line
        assert "Authorization:" not in line


@pytest.fixture(autouse=True)
def restore_handlers() -> Iterator[None]:
    original = dict(HANDLERS)
    try:
        yield
    finally:
        HANDLERS.clear()
        HANDLERS.update(original)


def _sample_filegdb_footprint() -> dict:
    return {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-01-01T00:00:00Z",
        "tool": {"name": "honua-esri-assess", "version": "0.1.0"},
        "source": {
            "kind": "filegdb",
            "locator": "sha256:" + "0" * 64,
            "capturedAt": "2026-01-01T00:00:00Z",
        },
        "filegdb": {
            "featureClassCount": 1,
            "pathHash": "sha256:" + "0" * 64,
        },
        "inventory": [
            {
                "kind": "filegdb-feature-class",
                "name": "Parcels",
                "geometryType": "esriGeometryPolygon",
                "sr": {"wkid": 4326},
            }
        ],
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": 0,
                "filegdb-feature-class": 1,
            },
            "layers": 0,
            "featureClasses": 1,
        },
        "diagnostics": [],
    }


def _stub_filegdb() -> None:
    def _fake_scan(options: ScanOptions) -> ScanResult:
        del options
        return ScanResult(footprint=_sample_filegdb_footprint())

    register(ScanHandler(name="filegdb", run=_fake_scan))


def test_scan_write_to_directory_emits_typed_diagnostic(
    tmp_path: Path,
    capsys,
) -> None:
    _stub_filegdb()
    output_dir = tmp_path / "footprint-as-directory"
    output_dir.mkdir()

    exit_code = cli_main(
        [
            "scan",
            "filegdb",
            "--target",
            str(tmp_path),
            "--output",
            str(output_dir),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 20
    assert "error[output-write-failed]" in captured.err
    _assert_prospect_safe(captured.err)
    assert str(output_dir) not in captured.err
    assert str(tmp_path) not in captured.err


def test_report_write_to_directory_emits_typed_diagnostic(
    tmp_path: Path,
    capsys,
) -> None:
    footprint = _sample_filegdb_footprint()
    footprint["inventory"] = []
    footprint["counts"]["items"]["filegdb-feature-class"] = 0
    footprint["counts"]["featureClasses"] = 0
    footprint["filegdb"]["featureClassCount"] = 0
    input_path = tmp_path / "EsriFootprint.json"
    input_path.write_text(json.dumps(footprint), encoding="utf-8")
    output_dir = tmp_path / "report-as-directory"
    output_dir.mkdir()

    exit_code = cli_main(
        [
            "report",
            "--input",
            str(input_path),
            "--output",
            str(output_dir),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.err.startswith("error: [report.input.write]")
    _assert_prospect_safe(captured.err)
    assert str(output_dir) not in captured.err
    assert str(input_path) not in captured.err
