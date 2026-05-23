"""CLI tests for prospect-safe handling of output-write failures.

If the supplied ``--output`` path is unwritable (existing directory, missing
parent, permission denied), the scanner must surface a typed, prospect-safe
diagnostic instead of an OSError traceback. The same guard applies to
``report`` writes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from honua_esri_assess import cli as cli_module
from honua_esri_assess.cli import main as cli_main

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


def _stub_filegdb(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_scan(target: Any) -> dict[str, Any]:
        return {
            "inventory": [
                {
                    "kind": "filegdb-feature-class",
                    "name": "Parcels",
                    "geometryType": "esriGeometryPolygon",
                    "sr": {"wkid": 4326},
                }
            ],
            "diagnostics": [],
            "filegdb": {"featureClassCount": 1, "pathHash": "sha256:" + "0" * 64},
        }

    monkeypatch.setattr(cli_module.filegdb_scanner, "scan", _fake_scan)


def test_scan_write_to_directory_emits_typed_diagnostic(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_filegdb(monkeypatch)
    # Point --output at an existing directory so write_text raises IsADirectoryError.
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

    assert exit_code == 1
    _assert_prospect_safe(captured.err)
    assert str(output_dir) not in captured.err
    assert str(tmp_path) not in captured.err


def test_report_write_to_directory_emits_typed_diagnostic(
    tmp_path: Path,
    capsys,
) -> None:
    footprint = {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-01-01T00:00:00Z",
        "tool": {"name": "honua-esri-assess", "version": "0.0.0"},
        "source": {
            "kind": "filegdb",
            "locator": "sha256:" + "0" * 64,
            "capturedAt": "2026-01-01T00:00:00Z",
        },
        "filegdb": {"featureClassCount": 0, "pathHash": "sha256:" + "0" * 64},
        "inventory": [],
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": 0,
                "filegdb-feature-class": 0,
            },
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }
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

    assert exit_code == 1
    _assert_prospect_safe(captured.err)
    assert str(output_dir) not in captured.err
    assert str(input_path) not in captured.err
