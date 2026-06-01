"""Tests for the migratability verdict engine."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess import verdict
from honua_esri_assess.verdict.engine import evaluate
from honua_esri_assess.verdict.registry import HARD_LOCK_IN_KEYS, SHOP_PROFILES

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
SAMPLE = FIXTURES / "esri-footprint-sample.json"
UTILITY_NETWORK = FIXTURES / "esri-footprint-utility-network.json"
LOCK_IN_EXTENT = FIXTURES / "esri-footprint-lock-in-extent.json"
SERVER_USAGE_BREADTH = FIXTURES / "esri-footprint-server-usage-breadth.json"
PORTAL_FEDERATION = FIXTURES / "esri-footprint-portal-federation.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _profile(result, name: str):
    return next(p for p in result.profiles if p.profile == name)


def test_all_profiles_present_and_ordered() -> None:
    result = evaluate(_load(SAMPLE))
    assert tuple(p.profile for p in result.profiles) == SHOP_PROFILES


def test_web_map_and_services_is_go() -> None:
    # Sample has Web Map + Feature Service -> first-class supported.
    result = evaluate(_load(SAMPLE))
    web = _profile(result, "web-map-and-services")
    assert web.verdict == "go"
    assert web.boundaries == ()
    assert web.effort == "Low"


def test_survey123_makes_editing_heavy_conditional() -> None:
    # Sample has a Survey123 Form -> conditional fidelity for editing-heavy.
    result = evaluate(_load(SAMPLE))
    editing = _profile(result, "editing-heavy")
    assert editing.verdict == "conditional"
    boundary_keys = {b.key for b in editing.boundaries}
    assert "survey123" in boundary_keys
    assert editing.effort in {"Moderate", "High"}


def test_utility_network_is_no_go_for_utility_profile() -> None:
    result = evaluate(_load(UTILITY_NETWORK))
    utility = _profile(result, "utility")
    assert utility.verdict == "no-go"
    assert utility.effort == "Very High"
    boundary_keys = {b.key for b in utility.boundaries}
    assert "utility-network" in boundary_keys
    un_boundary = next(b for b in utility.boundaries if b.key == "utility-network")
    assert un_boundary.hard_lock_in is True
    assert un_boundary.tier == "no-go"


def test_hard_lock_in_never_silently_dropped_across_profiles() -> None:
    # Utility Network must appear as an explicit boundary on EVERY profile,
    # not only the "utility" profile, and be surfaced at the top level.
    result = evaluate(_load(UTILITY_NETWORK))
    assert {b.key for b in result.hard_lock_ins} == {"utility-network"}
    for profile in result.profiles:
        boundary_keys = {b.key for b in profile.boundaries}
        assert "utility-network" in boundary_keys, profile.profile
        # A detected hard lock-in forces no-go everywhere.
        assert profile.verdict == "no-go", profile.profile


def test_registry_declares_three_hard_lock_ins() -> None:
    assert HARD_LOCK_IN_KEYS == {"utility-network", "parcel-fabric", "lrs"}


def test_empty_footprint_is_go_with_no_boundaries() -> None:
    result = evaluate({"schemaVersion": "v0.1", "inventory": []})
    for profile in result.profiles:
        assert profile.verdict == "go"
        assert profile.boundaries == ()
    assert result.hard_lock_ins == ()


def test_render_surfaces_verdict_and_lock_ins() -> None:
    markdown = verdict.render(_load(UTILITY_NETWORK))
    assert markdown.startswith("# Honua Migratability Verdict")
    assert "## Hard Lock-ins (explicit non-goals)" in markdown
    assert "Utility Network" in markdown
    assert "NO-GO" in markdown


def test_enumerated_extent_feeds_hard_lock_in_detail() -> None:
    # #46: the verdict reports lock-in extent (counts), not just presence.
    result = evaluate(_load(LOCK_IN_EXTENT))
    by_key = {b.key: b for b in result.hard_lock_ins}
    assert set(by_key) == {"utility-network", "parcel-fabric", "lrs"}

    un = by_key["utility-network"]
    assert un.extent is not None
    assert un.extent.feature_class_count == 9
    assert un.extent.domain_network_count == 2
    assert un.extent.rule_count == 14
    assert "9 feature class(es)" in un.detail
    assert "2 domain network(s)" in un.detail
    assert "14 rule(s)" in un.detail

    pf = by_key["parcel-fabric"]
    assert pf.extent is not None and pf.extent.feature_class_count == 6
    assert "6 feature class(es)" in pf.detail

    lrs = by_key["lrs"]
    assert lrs.extent is not None and lrs.extent.network_count == 3
    assert "3 network(s)" in lrs.detail


def test_enumerated_extent_aggregates_across_services() -> None:
    # Two UN services -> extent counts sum and report a service spread.
    footprint = {
        "schemaVersion": "v0.2",
        "inventory": [
            {
                "kind": "server-service",
                "serviceType": "FeatureServer",
                "capabilities": ["UtilityNetwork"],
                "lockIns": [{"type": "utility-network", "featureClassCount": 4}],
            },
            {
                "kind": "server-service",
                "serviceType": "FeatureServer",
                "capabilities": ["UtilityNetwork"],
                "lockIns": [{"type": "utility-network", "featureClassCount": 5}],
            },
        ],
    }
    result = evaluate(footprint)
    un = next(b for b in result.hard_lock_ins if b.key == "utility-network")
    assert un.extent is not None
    assert un.extent.services == 2
    assert un.extent.feature_class_count == 9
    assert "across 2 services" in un.detail


def test_extent_in_rendered_markdown() -> None:
    markdown = verdict.render(_load(LOCK_IN_EXTENT))
    assert "Enumerated extent:" in markdown
    assert "9 feature class(es)" in markdown


def test_lock_in_detected_without_extent_block_still_flags() -> None:
    # A lock-in with no enumerated extent (older footprint) still surfaces,
    # with the registry boundary text unchanged.
    result = evaluate(_load(UTILITY_NETWORK))
    un = next(b for b in result.hard_lock_ins if b.key == "utility-network")
    assert un.extent is None
    assert "Enumerated extent" not in un.detail


# --- #61: enriched footprint signals feed verdict + ordering --------------


def test_usage_ranking_drives_migration_order() -> None:
    # #31: server.bindingPlan.usageRankedServices sequences the migration by
    # observed request volume, highest first, with the producer's 1-based rank.
    result = evaluate(_load(SERVER_USAGE_BREADTH))
    assert result.signals.usage_ranked is True
    assert [s.identifier for s in result.migration_order] == [
        "Base/Parcels.FeatureServer",
        "Imagery/Ortho2024.ImageServer",
        "Tools/Geocode.GeocodeServer",
        "Roads/Network.NAServer",
    ]
    first = result.migration_order[0]
    assert first.rank == 1
    assert first.source == "usage"
    assert first.requests == 12840


def test_usage_ranking_resorts_unsorted_input_deterministically() -> None:
    footprint = {
        "schemaVersion": "v0.2",
        "inventory": [],
        "server": {
            "bindingPlan": {
                "usageRankedServices": [
                    {"service": "b/B.MapServer", "requests": 5, "rank": 2},
                    {"service": "a/A.FeatureServer", "requests": 9, "rank": 1},
                ]
            }
        },
    }
    result = evaluate(footprint)
    assert [s.rank for s in result.migration_order] == [1, 2]
    assert result.migration_order[0].identifier == "a/A.FeatureServer"


def test_non_feature_map_service_breadth_lifts_effort() -> None:
    # #43: image/geocode/network-analysis service kinds widen the migration
    # surface, lifting the effort band beyond the capability-tier baseline.
    result = evaluate(_load(SERVER_USAGE_BREADTH))
    assert result.signals.non_feature_map_service_kinds == (
        "geocodeService",
        "imageService",
        "networkAnalysisService",
    )
    web = _profile(result, "web-map-and-services")
    # Web/feature only -> would be "Low"; breadth lifts it one step.
    assert web.effort == "Moderate"
    raster = _profile(result, "raster/imagery")
    assert raster.verdict == "conditional"
    # conditional baseline "Moderate" + breadth lift -> "High".
    assert raster.effort == "High"
    assert any(
        "Non-feature/map service breadth" in line for line in web.rationale
    )


def test_feature_map_only_does_not_register_breadth() -> None:
    # The lock-in-extent fixture is feature/map only -> no breadth signal.
    result = evaluate(_load(LOCK_IN_EXTENT))
    assert result.signals.non_feature_map_service_kinds == ()


def test_federation_advanced_roles_feed_verdict_and_effort() -> None:
    # #54: federated advanced server roles change the migration story; they
    # surface in the rationale and lift the effort band.
    result = evaluate(_load(PORTAL_FEDERATION))
    assert result.signals.advanced_roles == ("geoanalytics", "geoevent", "notebook")
    gov = _profile(result, "gov")
    # Dashboards make gov "conditional" (Moderate base) + role lift -> "High".
    assert gov.effort == "High"
    assert any(
        "Federated advanced server roles present" in line for line in gov.rationale
    )


def test_federation_falls_back_to_per_server_roles() -> None:
    # When the rolled-up advancedRoles union is absent, the per-server roles
    # are still unioned so the signal is never lost.
    footprint = {
        "schemaVersion": "v0.2",
        "inventory": [],
        "portal": {
            "federation": {
                "servers": [
                    {"url": "https://a.example.com/arcgis", "advancedRoles": ["notebook"]},
                    {"url": "https://b.example.com/arcgis", "advancedRoles": ["geoevent"]},
                ]
            }
        },
    }
    result = evaluate(footprint)
    assert result.signals.advanced_roles == ("geoevent", "notebook")


def test_dependency_order_drives_migration_when_no_usage_signal() -> None:
    # #42: with no usage ranking, the dependency graph orders dependencies
    # first (referenced service before the web map before the dashboard).
    result = evaluate(_load(PORTAL_FEDERATION))
    assert result.signals.usage_ranked is False
    assert all(step.source == "dependency" for step in result.migration_order)
    assert [s.identifier for s in result.migration_order] == [
        "eeee5555ffff6666aaaa7777bbbb8888",  # Parcels feature service (referenced)
        "aaaa1111bbbb2222cccc3333dddd4444",  # Web Map references it
        "cccc9999dddd0000eeee1111ffff2222",  # Dashboard references the web map
    ]


def test_no_signals_yields_empty_order_and_summary() -> None:
    result = evaluate({"schemaVersion": "v0.1", "inventory": []})
    assert result.migration_order == ()
    assert result.signals.non_feature_map_service_kinds == ()
    assert result.signals.advanced_roles == ()
    assert result.signals.usage_ranked is False


def test_render_surfaces_usage_ordering() -> None:
    markdown = verdict.render(_load(SERVER_USAGE_BREADTH))
    assert "## Recommended Migration Order" in markdown
    assert "usage-ranked" in markdown
    assert "Base/Parcels.FeatureServer" in markdown
    assert "12840" in markdown
    assert "imageService" in markdown  # breadth surfaced in a rationale


def test_render_surfaces_dependency_ordering_and_federation() -> None:
    markdown = verdict.render(_load(PORTAL_FEDERATION))
    assert "## Recommended Migration Order" in markdown
    assert "dependency graph" in markdown
    assert "geoevent" in markdown
