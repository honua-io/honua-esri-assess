"""CLI tests for the readiness report command."""

from __future__ import annotations

import io
import json
from pathlib import Path

from honua_esri_assess import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_FOOTPRINT = REPO_ROOT / "docs" / "samples" / "esri-footprint.sample.json"


def test_report_writes_output_file(tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "readiness.md"

    exit_code = cli.main(
        ["report", "--input", str(SAMPLE_FOOTPRINT), "--output", str(output_path)]
    )

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8").startswith("# Honua Esri Readiness Report")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_report_reads_stdin_and_writes_stdout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(SAMPLE_FOOTPRINT.read_text(encoding="utf-8")),
    )

    exit_code = cli.main(["report", "--input", "-", "--output", "-"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "# Honua Esri Readiness Report" in captured.out
    assert captured.err == ""


def test_report_missing_file_is_prospect_safe(capsys) -> None:
    exit_code = cli.main(["report", "--input", "does-not-exist.json"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.input.read]")
    assert "Traceback" not in captured.err


def test_report_malformed_json_is_prospect_safe(tmp_path: Path, capsys) -> None:
    bad_json = tmp_path / "bad.json"
    bad_json.write_text('{"schemaVersion": ', encoding="utf-8")

    exit_code = cli.main(["report", "--input", str(bad_json)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.input.parse]")
    assert "Traceback" not in captured.err


def test_report_strict_schema_failure_is_typed(tmp_path: Path, capsys) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schemaVersion": "v0.1"}), encoding="utf-8")

    exit_code = cli.main(["report", "--input", str(invalid), "--strict"])

    assert exit_code == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.schema.invalid]")
    assert "Traceback" not in captured.err


def test_report_best_effort_schema_warning(tmp_path: Path, capsys) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schemaVersion": "v0.1"}), encoding="utf-8")

    exit_code = cli.main(["report", "--input", str(invalid)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "## Schema Warnings" in captured.out
    assert "Schema validation failed" in captured.out
    assert captured.err == ""
