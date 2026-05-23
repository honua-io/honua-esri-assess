"""Tests for the read-only FileGDB scanner path."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from honua_esri_assess.cli import main
from honua_esri_assess.filegdb import (
    FileGdbLayer,
    FileGdbReaderUnavailable,
    FileGdbScanOptions,
    hash_filegdb_path,
    scan_filegdb_workspace,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "esri-footprint-v0.1.json"
CAPTURED_AT = "2026-05-22T14:02:11Z"
GENERATED_AT = "2026-05-22T14:08:33Z"

FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("date-time")
def _is_utc_rfc3339(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() == timezone.utc.utcoffset(None)


class FakeFileGdbReader:
    def __init__(
        self,
        layers: list[FileGdbLayer],
        info_by_layer: Mapping[str, Mapping[str, Any]],
        *,
        failing_layers: set[str] | None = None,
    ) -> None:
        self.layers = layers
        self.info_by_layer = info_by_layer
        self.failing_layers = failing_layers or set()

    def list_layers(self, workspace: Path) -> list[FileGdbLayer]:
        return self.layers

    def read_layer_info(
        self,
        workspace: Path,
        layer_name: str,
        *,
        force_feature_count: bool = False,
    ) -> Mapping[str, Any]:
        if layer_name in self.failing_layers:
            raise RuntimeError(f"boom: {workspace}/{layer_name}")
        return self.info_by_layer[layer_name]


class MissingDependencyReader:
    def list_layers(self, workspace: Path) -> list[FileGdbLayer]:
        raise FileGdbReaderUnavailable("pyogrio missing")

    def read_layer_info(
        self,
        workspace: Path,
        layer_name: str,
        *,
        force_feature_count: bool = False,
    ) -> Mapping[str, Any]:
        raise AssertionError("read_layer_info should not be called")


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def _fixed_options() -> FileGdbScanOptions:
    return FileGdbScanOptions(
        path_hash_salt="unit-test-salt",
        captured_at=CAPTURED_AT,
        generated_at=GENERATED_AT,
    )


def _assert_schema_valid(artifact: Mapping[str, Any]) -> None:
    errors = sorted(_validator().iter_errors(artifact), key=lambda e: list(e.path))
    assert errors == [], "\n".join(
        f"{list(err.path)}: {err.message}" for err in errors
    )


def test_filegdb_scanner_emits_schema_valid_filegdb_footprint(tmp_path: Path) -> None:
    workspace = tmp_path / "customer.gdb"
    workspace.mkdir()
    reader = FakeFileGdbReader(
        layers=[FileGdbLayer("Parcels", "Polygon")],
        info_by_layer={
            "Parcels": {
                "crs": "EPSG:4326",
                "geometry_type": "Polygon",
                "features": 12,
                "fields": ["OBJECTID", "PARCEL_ID", "CREATED_AT"],
                "ogr_types": ["Integer", "String", "DateTime"],
                "nullable": [False, False, True],
            }
        },
    )

    artifact = scan_filegdb_workspace(
        workspace,
        options=_fixed_options(),
        reader=reader,
    )

    _assert_schema_valid(artifact)
    path_hash = hash_filegdb_path(workspace, salt="unit-test-salt")
    assert artifact["source"] == {
        "kind": "filegdb",
        "locator": path_hash,
        "capturedAt": CAPTURED_AT,
    }
    assert artifact["filegdb"] == {
        "pathHash": path_hash,
        "featureClassCount": 1,
    }
    assert artifact["counts"] == {
        "items": {
            "portal-item": 0,
            "server-service": 0,
            "filegdb-feature-class": 1,
        },
        "layers": 0,
        "featureClasses": 1,
    }
    assert artifact["inventory"] == [
        {
            "kind": "filegdb-feature-class",
            "name": "Parcels",
            "geometryType": "esriGeometryPolygon",
            "sr": {"wkid": 4326},
            "featureCount": 12,
            "fields": [
                {"name": "OBJECTID", "type": "esriFieldTypeOID", "nullable": False},
                {"name": "PARCEL_ID", "type": "esriFieldTypeString", "nullable": False},
                {"name": "CREATED_AT", "type": "esriFieldTypeDate", "nullable": True},
            ],
        }
    ]
    serialized = json.dumps(artifact)
    assert str(workspace) not in serialized
    assert "customer.gdb" not in serialized


def test_filegdb_scanner_surfaces_layer_failures_as_safe_diagnostics(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "customer.gdb"
    workspace.mkdir()
    reader = FakeFileGdbReader(
        layers=[
            FileGdbLayer("Parcels", "Polygon"),
            FileGdbLayer("Bad/Layer", "Polygon"),
        ],
        info_by_layer={
            "Parcels": {
                "crs": "EPSG:2926",
                "geometry_type": "Polygon",
                "features": 4,
                "fields": [],
            }
        },
        failing_layers={"Bad/Layer"},
    )

    artifact = scan_filegdb_workspace(
        workspace,
        options=_fixed_options(),
        reader=reader,
    )

    _assert_schema_valid(artifact)
    assert len(artifact["inventory"]) == 1
    assert artifact["diagnostics"] == [
        {
            "code": "partial-coverage",
            "severity": "warn",
            "message": "Skipped one FileGDB layer because its metadata could not be read.",
            "scope": "Bad_Layer",
            "hint": "Confirm this layer can be opened read-only by GDAL/OGR.",
        }
    ]
    diagnostics_text = json.dumps(artifact["diagnostics"])
    assert "Traceback" not in diagnostics_text
    assert str(workspace) not in diagnostics_text
    assert "customer.gdb" not in diagnostics_text
    assert "boom" not in diagnostics_text


def test_filegdb_scanner_emits_error_diagnostic_when_reader_is_unavailable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "customer.gdb"
    workspace.mkdir()

    artifact = scan_filegdb_workspace(
        workspace,
        options=_fixed_options(),
        reader=MissingDependencyReader(),
    )

    _assert_schema_valid(artifact)
    assert artifact["inventory"] == []
    assert artifact["counts"]["items"]["filegdb-feature-class"] == 0
    assert artifact["diagnostics"][0]["code"] == "partial-coverage"
    assert artifact["diagnostics"][0]["severity"] == "error"
    assert "honua-esri-assess[filegdb]" in artifact["diagnostics"][0]["hint"]


def test_filegdb_cli_writes_footprint_json_with_fake_scanner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "customer.gdb"
    workspace.mkdir()
    output_path = tmp_path / "EsriFootprint.json"

    def fake_scan_filegdb_workspace(
        workspace_arg: str,
        *,
        options: FileGdbScanOptions,
    ) -> Mapping[str, Any]:
        assert Path(workspace_arg) == workspace
        assert options.path_hash_salt == "cli-salt"
        return scan_filegdb_workspace(
            workspace,
            options=FileGdbScanOptions(
                path_hash_salt="cli-salt",
                captured_at=CAPTURED_AT,
                generated_at=GENERATED_AT,
            ),
            reader=FakeFileGdbReader(
                layers=[FileGdbLayer("Roads", "LineString")],
                info_by_layer={
                    "Roads": {
                        "crs": "EPSG:4326",
                        "geometry_type": "LineString",
                        "features": 3,
                        "fields": [],
                    }
                },
            ),
        )

    import honua_esri_assess.filegdb as filegdb

    monkeypatch.setattr(filegdb, "scan_filegdb_workspace", fake_scan_filegdb_workspace)

    exit_code = main(
        [
            "filegdb",
            str(workspace),
            "--output",
            str(output_path),
            "--path-hash-salt",
            "cli-salt",
        ]
    )

    assert exit_code == 0
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    _assert_schema_valid(artifact)
    assert artifact["source"]["kind"] == "filegdb"
    assert artifact["inventory"][0]["geometryType"] == "esriGeometryPolyline"
