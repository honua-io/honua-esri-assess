"""Tests for crosswalking a footprint's detected capabilities to Honua keys."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.caps.crosswalk import load_bundled_crosswalk
from honua_esri_assess.caps.mapper import evaluate

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "docs" / "samples" / "esri-footprint.sample.json"
UTILITY_NETWORK = REPO_ROOT / "tests" / "fixtures" / "esri-footprint-utility-network.json"
PORTAL_FEDERATION = REPO_ROOT / "tests" / "fixtures" / "esri-footprint-portal-federation.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _by_key(capabilities) -> dict:
    return {entry.key: entry for entry in capabilities}


def _by_assess_key(unmapped) -> dict:
    return {entry.assess_key: entry for entry in unmapped}


def test_evaluate_sample_footprint_maps_expected_capabilities() -> None:
    footprint = _load(SAMPLE)
    crosswalk = load_bundled_crosswalk()

    result = evaluate(footprint, crosswalk)

    capabilities = _by_key(result.capabilities)
    assert set(capabilities) == {"serve.geoservices-featureserver", "identity.portal-sharing", "fieldops.forms"}

    feature_service = capabilities["serve.geoservices-featureserver"]
    assert feature_service.assess_keys == ("feature-service",)
    assert capabilities["identity.portal-sharing"].assess_keys == ("web-map",)
    assert capabilities["fieldops.forms"].assess_keys == ("survey123",)
    assert feature_service.matched_inventory_count == 2  # 2 Feature Service items; Web Map now maps to identity.portal-sharing
    assert feature_service.tier == "go"

    portal_sharing = capabilities["identity.portal-sharing"]
    assert portal_sharing.matched_inventory_count == 1
    assert portal_sharing.tier == "go"


def test_evaluate_sample_footprint_maps_survey123_to_fieldops_forms() -> None:
    footprint = _load(SAMPLE)
    crosswalk = load_bundled_crosswalk()

    result = evaluate(footprint, crosswalk)

    unmapped = _by_assess_key(result.unmapped)
    capabilities = _by_key(result.capabilities)
    assert "survey123" not in unmapped
    forms = capabilities["fieldops.forms"]
    assert forms.matched_inventory_count == 1
    assert forms.tier == "conditional"


def test_evaluate_sample_footprint_has_no_units_estimate() -> None:
    footprint = _load(SAMPLE)
    crosswalk = load_bundled_crosswalk()

    result = evaluate(footprint, crosswalk)

    assert result.units_estimate is None


def test_evaluate_utility_network_marks_not_supported() -> None:
    footprint = _load(UTILITY_NETWORK)
    crosswalk = load_bundled_crosswalk()

    result = evaluate(footprint, crosswalk)

    unmapped = _by_assess_key(result.unmapped)
    assert unmapped["utility-network"].reason == "not-supported"
    assert unmapped["utility-network"].tier == "no-go"
    assert unmapped["utility-network"].matched_inventory_count == 1

    capabilities = _by_key(result.capabilities)
    assert set(capabilities) == {"serve.geoservices-featureserver", "serve.geoservices-mapserver", "editing.featureserver-edits"}


def test_evaluate_utility_network_units_estimate_falls_back_to_one() -> None:
    footprint = _load(UTILITY_NETWORK)
    crosswalk = load_bundled_crosswalk()

    result = evaluate(footprint, crosswalk)

    assert result.units_estimate == 1


def test_evaluate_portal_federation_units_estimate_counts_federated_servers() -> None:
    footprint = _load(PORTAL_FEDERATION)
    crosswalk = load_bundled_crosswalk()

    result = evaluate(footprint, crosswalk)

    assert result.units_estimate == 2


def test_evaluate_portal_federation_reports_dashboard_as_unmapped() -> None:
    footprint = _load(PORTAL_FEDERATION)
    crosswalk = load_bundled_crosswalk()

    result = evaluate(footprint, crosswalk)

    unmapped = _by_assess_key(result.unmapped)
    assert "dashboards-apps" not in unmapped
    assert "collaboration.map-sessions" in _by_key(result.capabilities)


def test_evaluate_never_drops_a_detected_capability() -> None:
    """Honesty invariant (#84): every detected assess key surfaces somewhere."""

    crosswalk = load_bundled_crosswalk()
    for path in (SAMPLE, UTILITY_NETWORK, PORTAL_FEDERATION):
        footprint = _load(path)
        result = evaluate(footprint, crosswalk)

        surfaced_assess_keys = {
            assess_key for entry in result.capabilities for assess_key in entry.assess_keys
        } | {entry.assess_key for entry in result.unmapped}

        assert surfaced_assess_keys == set(result.detected_assess_keys), path


def test_evaluate_empty_inventory_yields_no_capabilities_or_unmapped() -> None:
    footprint = {"source": {"kind": "arcgis-online"}, "inventory": []}
    crosswalk = load_bundled_crosswalk()

    result = evaluate(footprint, crosswalk)

    assert result.capabilities == ()
    assert result.unmapped == ()
    assert result.detected_assess_keys == ()
    assert result.units_estimate is None
