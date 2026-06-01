"""Hard lock-in enumeration (#46) from read-only ArcGIS Server service bodies."""

from __future__ import annotations

from honua_esri_assess.server.lock_in import enumerate_lock_ins


def test_no_lock_in_for_plain_feature_service() -> None:
    body = {
        "capabilities": "Query,Editing,Sync",
        "layers": [{"id": 0}, {"id": 1}],
    }
    assert enumerate_lock_ins(body, service_type="FeatureServer", layer_count=2) == ()


def test_utility_network_from_controller_dataset_with_extent() -> None:
    body = {
        "capabilities": "Query,UtilityNetwork",
        "layers": [{"id": i} for i in range(12)],
        "controllerDatasetLayers": {
            "utilityNetworkLayerId": 4,
            "layers": [{"id": i} for i in range(9)],
            "domainNetworks": [{"name": "Electric"}, {"name": "Structure"}],
            "rules": [{"id": 1}, {"id": 2}, {"id": 3}],
        },
    }
    (lock_in,) = enumerate_lock_ins(body, service_type="FeatureServer", layer_count=12)
    assert lock_in.kind == "utility-network"
    # Controller-dataset layer list wins over the service-level layer count.
    assert lock_in.feature_class_count == 9
    assert lock_in.domain_network_count == 2
    assert lock_in.rule_count == 3
    assert lock_in.network_count is None


def test_utility_network_from_capability_token_falls_back_to_layer_count() -> None:
    body = {"capabilities": "Query,UtilityNetwork", "layers": [{"id": 0}, {"id": 1}]}
    (lock_in,) = enumerate_lock_ins(body, service_type="FeatureServer", layer_count=7)
    assert lock_in.kind == "utility-network"
    assert lock_in.feature_class_count == 7
    assert lock_in.domain_network_count is None
    assert lock_in.rule_count is None


def test_utility_network_from_dedicated_service_type() -> None:
    body: dict = {}
    (lock_in,) = enumerate_lock_ins(body, service_type="UtilityNetworkServer")
    assert lock_in.kind == "utility-network"


def test_parcel_fabric_from_controller_dataset() -> None:
    body = {
        "capabilities": "Query",
        "controllerDatasetLayers": {
            "parcelFabricLayerId": 1,
            "parcelLayers": [{"id": 0}, {"id": 1}, {"id": 2}],
        },
    }
    (lock_in,) = enumerate_lock_ins(body, service_type="FeatureServer", layer_count=5)
    assert lock_in.kind == "parcel-fabric"
    assert lock_in.feature_class_count == 3


def test_parcel_fabric_from_capability_token() -> None:
    body = {"capabilities": "Query,ParcelFabric", "layers": [{"id": 0}]}
    (lock_in,) = enumerate_lock_ins(body, service_type="FeatureServer", layer_count=4)
    assert lock_in.kind == "parcel-fabric"
    assert lock_in.feature_class_count == 4


def test_lrs_from_lrs_block_with_networks() -> None:
    body = {
        "lrs": {
            "networkLayers": [{"id": 1}, {"id": 2}],
        }
    }
    (lock_in,) = enumerate_lock_ins(body, service_type="MapServer", layer_count=3)
    assert lock_in.kind == "lrs"
    assert lock_in.network_count == 2
    assert lock_in.feature_class_count is None


def test_lrs_from_dedicated_service_type() -> None:
    (lock_in,) = enumerate_lock_ins({}, service_type="LRServer")
    assert lock_in.kind == "lrs"
    assert lock_in.network_count is None


def test_lrs_from_capability_token() -> None:
    body = {"capabilities": "Query,LinearReferencing"}
    (lock_in,) = enumerate_lock_ins(body, service_type="FeatureServer")
    assert lock_in.kind == "lrs"


def test_capabilities_as_list_are_tokenized() -> None:
    body = {"capabilities": ["Query", "UtilityNetwork"], "layers": [{"id": 0}]}
    (lock_in,) = enumerate_lock_ins(body, service_type="FeatureServer", layer_count=1)
    assert lock_in.kind == "utility-network"


def test_multiple_lock_ins_on_one_service() -> None:
    body = {
        "capabilities": "Query,UtilityNetwork,ParcelFabric,LRS",
        "layers": [{"id": 0}],
    }
    kinds = {lock_in.kind for lock_in in enumerate_lock_ins(body, layer_count=1)}
    assert kinds == {"utility-network", "parcel-fabric", "lrs"}
