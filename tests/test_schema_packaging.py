"""Ensure the bundled v0.1 schema ships and matches the canonical copy.

The repository ships the EsriFootprint v0.1 contract in two locations:

* The canonical, human-readable file at ``schemas/esri-footprint-v0.1.json``
  (the same path referenced by ``docs/schemas/*``).
* A package-data copy at ``src/honua_esri_assess/schemas/esri-footprint-v0.1.json``
  that the installed wheel exposes through :mod:`importlib.resources`.

These tests fail loud if the two diverge or if the runtime loader cannot
find the bundled file. Without them, an installed CLI could emit an
artifact without ever validating it against the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from honua_esri_assess.diagnostics import PortalSchemaError
from honua_esri_assess.footprint import schema as schema_module

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SCHEMA = REPO_ROOT / "schemas" / "esri-footprint-v0.1.json"
PACKAGE_SCHEMA = (
    REPO_ROOT
    / "src"
    / "honua_esri_assess"
    / "schemas"
    / "esri-footprint-v0.1.json"
)


def test_package_schema_is_bundled() -> None:
    assert PACKAGE_SCHEMA.exists(), (
        "The package-data copy of esri-footprint-v0.1.json is missing. "
        "Installed CLIs would silently skip schema validation."
    )


def test_package_schema_matches_canonical() -> None:
    canonical = json.loads(CANONICAL_SCHEMA.read_text(encoding="utf-8"))
    bundled = json.loads(PACKAGE_SCHEMA.read_text(encoding="utf-8"))
    assert canonical == bundled, (
        "schemas/esri-footprint-v0.1.json and "
        "src/honua_esri_assess/schemas/esri-footprint-v0.1.json have diverged. "
        "Update both copies in lock-step."
    )


def test_load_schema_returns_v0_1() -> None:
    schema_module.load_schema.cache_clear()
    schema = schema_module.load_schema()
    assert schema["properties"]["schemaVersion"]["const"] == "v0.1"


def test_load_schema_fails_closed_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    schema_module.load_schema.cache_clear()
    monkeypatch.setattr(schema_module, "SCHEMA_FILENAME", "missing-schema.json")
    with pytest.raises(PortalSchemaError):
        schema_module.load_schema()
    schema_module.load_schema.cache_clear()


def test_validate_footprint_propagates_schema_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_module.load_schema.cache_clear()
    monkeypatch.setattr(schema_module, "SCHEMA_FILENAME", "missing-schema.json")
    with pytest.raises(PortalSchemaError):
        schema_module.validate_footprint({})
    schema_module.load_schema.cache_clear()
