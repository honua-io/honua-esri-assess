"""Unit coverage for usage ranking and binding-mode routing (pure logic)."""

from __future__ import annotations

from honua_esri_assess.footprint.binding import (
    DatastoreRegistration,
    binding_mode_for_connection,
    build_binding_plan,
    connection_kind_for_type,
    rank_services_by_usage,
    recommend_binding,
)


def test_rank_services_is_usage_driven_descending_with_alpha_tiebreak() -> None:
    ranked = rank_services_by_usage(
        {
            "Parcels.MapServer": 60,
            "Hydro/Streams.MapServer": 15,
            "Planning/Zoning.FeatureServer": 2,
            "B.MapServer": 2,
        }
    )
    assert [(s.service, s.rank) for s in ranked] == [
        ("Parcels.MapServer", 1),
        ("Hydro/Streams.MapServer", 2),
        ("B.MapServer", 3),
        ("Planning/Zoning.FeatureServer", 4),
    ]
    assert ranked[0].requests == 60


def test_connection_kind_detected_from_declared_type_token() -> None:
    assert connection_kind_for_type("egdb") == "enterprise-geodatabase"
    assert connection_kind_for_type("Enterprise Geodatabase") == (
        "enterprise-geodatabase"
    )
    assert connection_kind_for_type("cloudStore") == "cloud-store"
    assert connection_kind_for_type("folder") == "file-share"
    assert connection_kind_for_type("bigDataFileShare") == "big-data-file-share"
    assert connection_kind_for_type("whatever-new") == "unknown"


def test_binding_mode_mapping() -> None:
    assert binding_mode_for_connection("enterprise-geodatabase") == "federate"
    assert binding_mode_for_connection("relational") == "federate"
    assert binding_mode_for_connection("cloud-store") == "connect-in-place"
    assert binding_mode_for_connection("big-data-file-share") == "connect-in-place"
    assert binding_mode_for_connection("file-share") == "materialize"
    assert binding_mode_for_connection("unknown") == "materialize"


def test_recommend_binding_round_trips_registration() -> None:
    reg = DatastoreRegistration(
        item_id="/enterpriseDatabases/parcels_egdb",
        type="egdb",
        connection_kind="enterprise-geodatabase",
    )
    binding = recommend_binding(reg)
    assert binding.to_dict() == {
        "datasetId": "/enterpriseDatabases/parcels_egdb",
        "storageType": "egdb",
        "connectionKind": "enterprise-geodatabase",
        "bindingMode": "federate",
    }


def test_build_binding_plan_combines_facets() -> None:
    plan = build_binding_plan(
        usage={"A.MapServer": 5, "B.MapServer": 9},
        registrations=[
            DatastoreRegistration("/c/cloud", "cloudStore", "cloud-store"),
            DatastoreRegistration("/f/folder", "folder", "file-share"),
        ],
    )
    out = plan.to_dict()
    assert [s["service"] for s in out["usageRankedServices"]] == [
        "B.MapServer",
        "A.MapServer",
    ]
    assert [b["bindingMode"] for b in out["datasetBindings"]] == [
        "connect-in-place",
        "materialize",
    ]
