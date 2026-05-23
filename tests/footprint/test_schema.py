"""JSON Schema discovery for emitted footprints."""

from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

from honua_esri_assess.footprint import schema as schema_module


def test_find_schema_path_accepts_semver_for_minor_schema_file(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    schema_path = tmp_path / "esri-footprint.v0.1.json"
    schema_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(schema_module, "_SCHEMA_DIR_CANDIDATES", (tmp_path,))

    assert schema_module.find_schema_path("0.1.0") == schema_path


def test_validate_footprint_uses_documented_minor_schema_name(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    schema_path = tmp_path / "esri-footprint.v0.1.json"
    schema_path.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    monkeypatch.setattr(schema_module, "_SCHEMA_DIR_CANDIDATES", (tmp_path,))

    assert schema_module.validate_footprint({"schemaVersion": "v0.1"}) is True
