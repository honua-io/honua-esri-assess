"""Regression tests for the EsriFootprint handoff contract."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.diagnostics import DIAGNOSTIC_CODES, SEVERITY_LEVELS, Diagnostic
from honua_esri_assess.footprint import SCHEMA_VERSION, TOOL_NAME, build_footprint

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "esri-footprint-v0.1.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_header_matches_documented_handoff_contract() -> None:
    schema = _schema()

    assert "tool" in schema["required"]
    assert "producer" not in schema["required"]
    assert schema["properties"]["schemaVersion"]["const"] == "v0.1"
    assert "tool" in schema["properties"]
    assert "producer" not in schema["properties"]

    source_kind = schema["$defs"]["Source"]["properties"]["kind"]
    assert set(source_kind["enum"]) == {"arcgis-online", "arcgis-server", "filegdb"}

    diagnostic = schema["$defs"]["Diagnostic"]
    assert set(diagnostic["required"]) == {"code", "severity", "message", "scope"}
    assert set(diagnostic["properties"]["code"]["enum"]) == DIAGNOSTIC_CODES
    assert set(diagnostic["properties"]["severity"]["enum"]) == SEVERITY_LEVELS
    assert "scope" in diagnostic["properties"]
    assert "hint" in diagnostic["properties"]
    assert "field" not in diagnostic["properties"]
    assert "target" not in diagnostic["properties"]


def test_footprint_builder_emits_contract_header_for_each_backend() -> None:
    for source_kind, kwargs in [
        (
            "arcgis-online",
            {
                "portal": {
                    "orgId": "fixture-org",
                    "orgUrl": "https://fixture.local",
                    "itemCounts": {},
                }
            },
        ),
        ("arcgis-server", {"server": {"folders": [], "serviceCounts": {}}}),
        (
            "filegdb",
            {"filegdb": {"pathHash": "sha256:" + "0" * 64, "featureClassCount": 0}},
        ),
    ]:
        footprint = build_footprint(
            source_kind=source_kind,
            target="https://fixture.local/source",
            inventory=[],
            diagnostics=[
                Diagnostic(
                    code="missing-permission",
                    message="A restricted item could not be inspected.",
                    scope="items.restricted-map",
                )
            ],
            **kwargs,
        )

        assert footprint["schemaVersion"] == SCHEMA_VERSION == "v0.2"
        assert footprint["tool"]["name"] == TOOL_NAME == "honua-esri-assess"
        assert "producer" not in footprint
        assert footprint["source"]["kind"] == source_kind
        assert "locator" in footprint["source"]
        assert "capturedAt" in footprint["source"]
        assert footprint["diagnostics"] == [
            {
                "code": "missing-permission",
                "severity": "warn",
                "message": "A restricted item could not be inspected.",
                "scope": "items.restricted-map",
            }
        ]
        assert "field" not in footprint["diagnostics"][0]
        assert "target" not in footprint["diagnostics"][0]
