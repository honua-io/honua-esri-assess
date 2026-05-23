"""Golden-file and section coverage tests for the readiness report renderer."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.report import RenderOptions, render

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_FOOTPRINT = REPO_ROOT / "docs" / "samples" / "esri-footprint.sample.json"
SAMPLE_REPORT = REPO_ROOT / "docs" / "samples" / "readiness-report.sample.md"


def _load_sample() -> dict:
    with SAMPLE_FOOTPRINT.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_render_matches_committed_sample() -> None:
    rendered = render(_load_sample())
    expected = SAMPLE_REPORT.read_text(encoding="utf-8")
    assert rendered == expected


def test_render_is_deterministic() -> None:
    sample = _load_sample()
    assert render(sample) == render(sample)


def test_render_handles_empty_inventory() -> None:
    footprint = {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.1.0"},
        "source": {
            "kind": "arcgis-online",
            "locator": "example.maps.arcgis.com/0123ABCDEF456789",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "inventory": [],
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": 0,
                "filegdb-feature-class": 0,
            },
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }

    rendered = render(footprint)

    for heading in (
        "## Service Inventory",
        "## Layer Count",
        "## Complexity Estimate",
        "## Manual Review Items",
        "## Migration Ordering",
        "## Diagnostics Summary",
    ):
        assert heading in rendered
    assert "No inventory entries were captured." in rendered
    assert "No diagnostics were captured." in rendered


def test_render_truncates_at_max_inventory_rows() -> None:
    sample = _load_sample()
    rendered = render(sample, options=RenderOptions(max_inventory_rows=2))
    inventory_section = rendered.split("## Layer Count", 1)[0]

    assert "2 inventory records hidden by the report row limit" in rendered
    assert "Field Damage Survey" not in inventory_section
