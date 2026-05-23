"""JSON Schema discovery for emitted footprints."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from honua_esri_assess.footprint import schema as schema_module

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    monkeypatch.setattr(schema_module, "_PACKAGE_SCHEMA_DIR", "__missing_schemas__")

    assert schema_module.validate_footprint({"schemaVersion": "v0.1"}) is True


def test_packaged_schema_resource_matches_published_schema() -> None:
    packaged = (
        resources.files("honua_esri_assess")
        .joinpath("schemas")
        .joinpath("esri-footprint-v0.1.json")
    )
    published = REPO_ROOT / "schemas" / "esri-footprint-v0.1.json"

    assert json.loads(packaged.read_text(encoding="utf-8")) == json.loads(
        published.read_text(encoding="utf-8")
    )


def test_validate_footprint_uses_packaged_schema_when_repo_paths_are_absent(
    monkeypatch: MonkeyPatch,
) -> None:
    sample = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "esri-footprint-sample.json").read_text(
            encoding="utf-8"
        )
    )
    monkeypatch.setattr(schema_module, "_SCHEMA_DIR_CANDIDATES", ())

    assert schema_module.validate_footprint(sample) is True


def test_validate_footprint_fails_closed_when_schema_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(schema_module, "_SCHEMA_DIR_CANDIDATES", ())
    monkeypatch.setattr(schema_module, "_PACKAGE_SCHEMA_DIR", "__missing_schemas__")

    with pytest.raises(schema_module.FootprintSchemaNotFoundError):
        schema_module.validate_footprint({"schemaVersion": "v0.1"})
