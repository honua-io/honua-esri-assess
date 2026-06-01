"""Tests for the `scan filegdb-workspace` CLI handler.

These exercise the pyogrio/GDAL workspace scanner through the CLI handler
adapter. The happy path injects a fake metadata reader so the tests run without
the optional ``pyogrio`` backend installed; a separate test asserts the
dependency-unavailable path that real environments hit when the extra is
missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest
from jsonschema import Draft202012Validator

from honua_esri_assess.commands.common import ScanOptions
from honua_esri_assess.commands.scan_handlers import filegdb_workspace
from honua_esri_assess.filegdb import FileGdbLayer

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "esri-footprint-v0.1.json"


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _options(target: Path, output: Path) -> ScanOptions:
    return ScanOptions(
        target=str(target),
        output=output,
        token_env=None,
        log_format="text",
        log_level="info",
        no_network_telemetry_confirm=False,
        user_agent="honua-esri-assess/test",
        max_retries=3,
        timeout=30.0,
        validate=False,
    )


class FakeFileGdbReader:
    def __init__(
        self,
        layers: list[FileGdbLayer],
        info_by_layer: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.layers = layers
        self.info_by_layer = info_by_layer

    def list_layers(self, workspace: Path) -> list[FileGdbLayer]:
        return self.layers

    def read_layer_info(
        self,
        workspace: Path,
        layer_name: str,
        *,
        force_feature_count: bool = False,
    ) -> Mapping[str, Any]:
        return self.info_by_layer[layer_name]


def test_handler_emits_schema_valid_footprint_with_injected_reader(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "customer.gdb"
    workspace.mkdir()
    output = tmp_path / "EsriFootprint.json"
    reader = FakeFileGdbReader(
        layers=[
            FileGdbLayer("Parcels", "Polygon"),
            FileGdbLayer("Hydrants", "Point"),
        ],
        info_by_layer={
            "Parcels": {
                "crs": "EPSG:4326",
                "geometry_type": "Polygon",
                "features": 1248,
                "fields": ["OBJECTID", "PARCEL_ID"],
                "ogr_types": ["Integer", "String"],
            },
            "Hydrants": {
                "crs": "EPSG:4326",
                "geometry_type": "Point",
                "features": 312,
                "fields": [],
            },
        },
    )

    result = filegdb_workspace.run(_options(workspace, output), reader=reader)

    _validator().validate(result.footprint)
    footprint = result.footprint
    assert footprint["source"]["kind"] == "filegdb"
    assert footprint["filegdb"]["featureClassCount"] == 2
    assert footprint["filegdb"]["pathHash"].startswith("sha256:")
    assert footprint["counts"] == {
        "items": {
            "portal-item": 0,
            "server-service": 0,
            "filegdb-feature-class": 2,
        },
        "layers": 0,
        "featureClasses": 2,
    }
    assert [item["name"] for item in footprint["inventory"]] == [
        "Parcels",
        "Hydrants",
    ]
    assert all(
        item["kind"] == "filegdb-feature-class" for item in footprint["inventory"]
    )
    # Prospect-safe: the raw workspace path is never serialized into the artifact.
    serialized = json.dumps(footprint)
    assert str(workspace) not in serialized
    assert "customer.gdb" not in serialized


def test_handler_surfaces_missing_dependency_as_diagnostic(tmp_path: Path) -> None:
    workspace = tmp_path / "customer.gdb"
    workspace.mkdir()
    output = tmp_path / "EsriFootprint.json"

    class MissingDependencyReader:
        def list_layers(self, workspace: Path) -> list[FileGdbLayer]:
            from honua_esri_assess.filegdb import FileGdbReaderUnavailable

            raise FileGdbReaderUnavailable("pyogrio missing")

        def read_layer_info(
            self,
            workspace: Path,
            layer_name: str,
            *,
            force_feature_count: bool = False,
        ) -> Mapping[str, Any]:
            raise AssertionError("read_layer_info should not be called")

    result = filegdb_workspace.run(
        _options(workspace, output), reader=MissingDependencyReader()
    )

    _validator().validate(result.footprint)
    assert result.footprint["inventory"] == []
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "partial-coverage"
    assert diagnostic.severity == "error"
    assert diagnostic.hint is not None
    assert "honua-esri-assess[filegdb]" in diagnostic.hint


def test_handler_rejects_non_gdb_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "plain-directory"
    workspace.mkdir()
    output = tmp_path / "EsriFootprint.json"

    result = filegdb_workspace.run(_options(workspace, output))

    _validator().validate(result.footprint)
    assert result.footprint["inventory"] == []
    assert any(
        diagnostic.code == "unsupported-item-type"
        for diagnostic in result.diagnostics
    )


def test_real_pyogrio_backend_default_reader(tmp_path: Path) -> None:
    """Exercise the default pyogrio reader if (and only if) it is installed.

    Skips cleanly when the optional ``filegdb`` extra (pyogrio/GDAL) is not
    available in the environment.
    """

    pytest.importorskip("pyogrio", reason="pyogrio/GDAL backend not installed")

    workspace = tmp_path / "customer.gdb"
    workspace.mkdir()
    output = tmp_path / "EsriFootprint.json"

    # No fake reader: the handler builds the default PyogrioFileGdbReader. An
    # empty directory is not a real .gdb, so pyogrio fails to list layers; the
    # scanner must still emit a schema-valid footprint with a diagnostic.
    result = filegdb_workspace.run(_options(workspace, output))

    _validator().validate(result.footprint)
    assert result.footprint["source"]["kind"] == "filegdb"
    assert result.footprint["inventory"] == []
    assert result.diagnostics
