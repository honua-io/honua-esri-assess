"""Regression tests for the EsriFootprint handoff contract."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.diagnostics import DIAGNOSTIC_CODES, SEVERITY_LEVELS, Diagnostic
from honua_esri_assess.footprint import PRODUCER_NAME, SCHEMA_VERSION, build_footprint

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "esri-footprint-v0.1.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_header_matches_documented_handoff_contract() -> None:
    schema = _schema()

    assert "producer" in schema["required"]
    assert "tool" not in schema["required"]
    assert schema["properties"]["schemaVersion"]["pattern"] == r"^0\.1\.\d+$"
    assert "producer" in schema["properties"]
    assert "tool" not in schema["properties"]

    source_kind = schema["properties"]["source"]["properties"]["kind"]
    assert set(source_kind["enum"]) == {"agol", "arcgis-server", "filegdb"}

    diagnostic = schema["$defs"]["Diagnostic"]
    assert set(diagnostic["required"]) == {"code", "severity", "message"}
    assert set(diagnostic["properties"]["code"]["enum"]) == DIAGNOSTIC_CODES
    assert set(diagnostic["properties"]["severity"]["enum"]) == SEVERITY_LEVELS
    assert "field" in diagnostic["properties"]
    assert "target" not in diagnostic["properties"]


def test_footprint_builder_emits_contract_header_for_each_backend() -> None:
    source_kinds = _schema()["properties"]["source"]["properties"]["kind"]["enum"]

    for source_kind in source_kinds:
        footprint = build_footprint(
            source_kind=source_kind,
            target="fixture-target",
            inventory=[],
            diagnostics=[
                Diagnostic(
                    code="missing-permission",
                    message="A restricted item could not be inspected.",
                    field="items.restricted-map",
                )
            ],
        )

        assert footprint["schemaVersion"] == SCHEMA_VERSION == "0.1.0"
        assert footprint["producer"]["name"] == PRODUCER_NAME == "honua-esri-assess"
        assert "tool" not in footprint
        assert footprint["source"] == {"kind": source_kind, "target": "fixture-target"}
        assert footprint["diagnostics"] == [
            {
                "code": "missing-permission",
                "severity": "warning",
                "message": "A restricted item could not be inspected.",
                "field": "items.restricted-map",
            }
        ]
        assert "target" not in footprint["diagnostics"][0]
