"""CLI tests for the migratability verdict command."""

from __future__ import annotations

import io
import json
from pathlib import Path

from honua_esri_assess import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "tests" / "fixtures" / "esri-footprint-sample.json"
UTILITY_NETWORK = REPO_ROOT / "tests" / "fixtures" / "esri-footprint-utility-network.json"


def test_verdict_writes_output_file(tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "verdict.md"

    exit_code = cli.main(
        ["verdict", "--input", str(SAMPLE), "--output", str(output_path)]
    )

    assert exit_code == 0
    text = output_path.read_text(encoding="utf-8")
    assert text.startswith("# Honua Migratability Verdict")
    assert "## Verdict by Shop Profile" in text
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_verdict_reads_stdin_and_writes_stdout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(UTILITY_NETWORK.read_text(encoding="utf-8")),
    )

    exit_code = cli.main(["verdict", "--input", "-", "--output", "-"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "# Honua Migratability Verdict" in captured.out
    assert "NO-GO" in captured.out
    assert "Utility Network" in captured.out
    assert captured.err == ""


def test_verdict_missing_file_is_prospect_safe(capsys) -> None:
    exit_code = cli.main(["verdict", "--input", "does-not-exist.json"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.input.read]")
    assert "Traceback" not in captured.err


def test_verdict_malformed_json_is_prospect_safe(tmp_path: Path, capsys) -> None:
    bad_json = tmp_path / "bad.json"
    bad_json.write_text('{"schemaVersion": ', encoding="utf-8")

    exit_code = cli.main(["verdict", "--input", str(bad_json)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.input.parse]")
    assert "Traceback" not in captured.err


def test_verdict_strict_schema_failure_is_typed(tmp_path: Path, capsys) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schemaVersion": "v0.1"}), encoding="utf-8")

    exit_code = cli.main(["verdict", "--input", str(invalid), "--strict"])

    assert exit_code == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.schema.invalid]")
    assert "Traceback" not in captured.err
