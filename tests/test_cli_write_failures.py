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
            "inventory": [{"kind": "feature-class", "name": "Parcels"}],
            "diagnostics": [],
            "filegdb": {"featureClassCount": 1, "path": "stub.gdb"},
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
        "tool": {"name": "honua-esri-assess", "version": "0.0.0"},
        "source": {"kind": "filegdb", "target": "stub.gdb"},
        "generatedAt": "2026-01-01T00:00:00Z",
        "inventory": [],
        "counts": {"total": 0, "byKind": {}},
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
