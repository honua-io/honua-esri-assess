"""CLI tests for the readiness report command."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

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


def test_report_creates_output_parent_directories(tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "reports" / "readiness.md"

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


def test_report_output_write_failure_is_prospect_safe(capsys) -> None:
    exit_code = cli.main(
        ["report", "--input", str(SAMPLE_FOOTPRINT), "--output", str(SAMPLE_FOOTPRINT.parent)]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.input.write]")
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


def test_report_best_effort_invalid_filegdb_fields_still_renders(
    tmp_path: Path,
    capsys,
) -> None:
    invalid = tmp_path / "invalid-filegdb.json"
    footprint = _filegdb_footprint()
    footprint["inventory"][0]["fields"] = 123
    invalid.write_text(json.dumps(footprint), encoding="utf-8")

    exit_code = cli.main(["report", "--input", str(invalid)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "## Schema Warnings" in captured.out
    assert "Schema validation failed" in captured.out
    assert "Parcels" in captured.out
    assert "| Parcels | esriGeometryPolygon | 42 | WKID 4326 | 0 |" in captured.out
    assert captured.err == ""


def test_report_best_effort_invalid_type_values_still_renders(
    tmp_path: Path,
    capsys,
) -> None:
    invalid = tmp_path / "invalid-types.json"
    invalid.write_text(json.dumps(_mixed_invalid_type_footprint()), encoding="utf-8")

    exit_code = cli.main(["report", "--input", str(invalid)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "## Schema Warnings" in captured.out
    assert "Schema validation failed" in captured.out
    assert "Broken Portal" in captured.out
    assert "Water/MapServer" in captured.out
    assert "## Migration Ordering" in captured.out
    assert captured.err == ""


def test_packaged_report_strict_schema_failure_is_typed(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheels"
    target_dir = tmp_path / "target"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schemaVersion": "v0.1"}), encoding="utf-8")

    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--wheel-dir", str(wheel_dir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("honua_migrate-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert "honua_esri_assess/schemas/esri-footprint-v0.1.json" in archive.namelist()

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target_dir), str(wheel)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    code = """
import sys
from pathlib import Path
import honua_esri_assess
from honua_esri_assess import cli

package_file = Path(honua_esri_assess.__file__).resolve()
target_dir = Path(sys.argv[1]).resolve()
assert package_file.is_relative_to(target_dir), package_file
raise SystemExit(cli.main(["report", "--input", sys.argv[2], "--strict"]))
"""
    env = {**os.environ, "PYTHONPATH": str(target_dir)}
    result = subprocess.run(
        [sys.executable, "-c", code, str(target_dir), str(invalid)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3
    assert result.stdout == ""
    # Legacy-package use emits its transition warning on stderr before the
    # command's typed diagnostic; stdout remains reserved for artifacts.
    assert "error: [report.schema.invalid]" in result.stderr
    assert "Schema validation failed" in result.stderr


def _filegdb_footprint() -> dict:
    return {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.1.0"},
        "source": {
            "kind": "filegdb",
            "locator": "sha256:" + "0" * 64,
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "filegdb": {
            "pathHash": "sha256:" + "0" * 64,
            "featureClassCount": 1,
            "version": "10.x",
        },
        "inventory": [
            {
                "kind": "filegdb-feature-class",
                "name": "Parcels",
                "geometryType": "esriGeometryPolygon",
                "sr": {"wkid": 4326},
                "featureCount": 42,
                "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
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


def _mixed_invalid_type_footprint() -> dict:
    return {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.1.0"},
        "source": {
            "kind": "arcgis-online",
            "locator": "example.maps.arcgis.com/0123ABCDEF456789",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "portal": {
            "orgId": "0123ABCDEF456789",
            "orgUrl": "https://example.maps.arcgis.com",
            "itemCounts": {"Feature Service": 1},
        },
        "inventory": [
            {
                "kind": "portal-item",
                "id": "portal-invalid",
                "type": ["Feature Service"],
                "owner": "gis.admin",
                "title": "Broken Portal",
                "sharing": "org",
                "modified": "2026-05-22T14:02:11Z",
            },
            {
                "kind": "server-service",
                "serviceUrl": "https://gis.example.com/arcgis/rest/services/Water/MapServer",
                "serviceType": ["MapServer"],
                "folder": "",
                "layerCount": 3,
            },
        ],
        "counts": {
            "items": {
                "portal-item": 1,
                "server-service": 1,
                "filegdb-feature-class": 0,
            },
            "layers": 3,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }
