"""Tests for honua-caps.json + Markdown + shareable-URL rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from honua_esri_assess.caps.crosswalk import load_bundled_crosswalk
from honua_esri_assess.caps.mapper import evaluate
from honua_esri_assess.caps.renderer import (
    CATALOG_BASE_URL,
    build_url,
    render_markdown,
    to_json_dict,
)
from honua_esri_assess.diagnostics import ReportRenderError

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "docs" / "samples" / "esri-footprint.sample.json"
UTILITY_NETWORK = REPO_ROOT / "tests" / "fixtures" / "esri-footprint-utility-network.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_build_url_omits_units_when_none() -> None:
    url = build_url(("serve.feature-service", "serve.map-service"), None)

    assert url == f"{CATALOG_BASE_URL}?caps=serve.feature-service,serve.map-service"


def test_build_url_includes_units_when_present() -> None:
    url = build_url(("serve.feature-service",), 4)

    assert url == f"{CATALOG_BASE_URL}?caps=serve.feature-service&units=4"


def test_build_url_empty_keys() -> None:
    url = build_url((), None)

    assert url == f"{CATALOG_BASE_URL}?caps="


def test_to_json_dict_shape_for_sample_footprint() -> None:
    footprint = _load(SAMPLE)
    crosswalk = load_bundled_crosswalk()
    result = evaluate(footprint, crosswalk)

    payload = to_json_dict(
        footprint, crosswalk, result, generated_at="2026-07-16T00:00:00Z"
    )

    assert payload["schemaVersion"] == "honua-caps.v1"
    assert payload["generatedAt"] == "2026-07-16T00:00:00Z"
    assert payload["source"] == {
        "kind": "arcgis-online",
        "locator": "example.maps.arcgis.com/0123ABCDEF456789",
    }
    assert payload["crosswalk"]["schemaVersion"] == "capability-keys.v1"
    assert payload["crosswalk"]["source"].startswith("DRAFT-FIXTURE")
    assert {entry["key"] for entry in payload["capabilities"]} == {
        "serve.feature-service",
        "serve.map-service",
    }
    assert {entry["assessKey"] for entry in payload["unmapped"]} == {"survey123"}
    assert payload["unitsEstimate"] is None
    assert payload["url"] == (
        "https://honua.io/capabilities.html?caps=serve.feature-service,serve.map-service"
    )


def test_to_json_dict_rejects_non_mapping_footprint() -> None:
    crosswalk = load_bundled_crosswalk()
    result = evaluate({"inventory": []}, crosswalk)

    with pytest.raises(ReportRenderError):
        to_json_dict(["not", "a", "mapping"], crosswalk, result, generated_at="x")


def test_render_markdown_has_expected_sections() -> None:
    footprint = _load(UTILITY_NETWORK)
    crosswalk = load_bundled_crosswalk()
    result = evaluate(footprint, crosswalk)
    payload = to_json_dict(footprint, crosswalk, result, generated_at="2026-07-16T00:00:00Z")

    markdown = render_markdown(payload)

    assert markdown.startswith("# Honua Capability Crosswalk")
    assert "## Mapped Capabilities" in markdown
    assert "## Unmapped / Not Supported" in markdown
    assert "## Shareable Catalog URL" in markdown
    assert "utility-network" in markdown
    assert "not-supported" in markdown
    assert payload["url"] in markdown


def test_render_markdown_no_unmapped_entries_says_so() -> None:
    footprint = {
        "source": {"kind": "arcgis-online"},
        "inventory": [
            {"kind": "portal-item", "type": "Feature Service", "id": "a"},
        ],
    }
    crosswalk = load_bundled_crosswalk()
    result = evaluate(footprint, crosswalk)
    payload = to_json_dict(footprint, crosswalk, result, generated_at="2026-07-16T00:00:00Z")

    markdown = render_markdown(payload)

    assert "nothing was dropped" in markdown
