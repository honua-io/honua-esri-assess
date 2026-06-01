"""Enumerate hard Esri lock-ins (Utility Network, Parcel Fabric, LRS) with extent.

The migratability verdict flags these three Esri capabilities as hard lock-ins
that never migrate. This module turns a *bare flag* into an *enumeration*: given
an already-fetched, read-only ArcGIS Server service body, it detects which (if
any) hard lock-ins the service carries and records their extent — counts of
Utility Network feature classes / domain networks / rules, Parcel Fabric feature
classes, and LRS networks — so the verdict can report ``UN: N feature classes``
rather than just ``UN present``.

This module is pure: it takes the JSON body the catalog walk already fetched and
returns typed :class:`~honua_esri_assess.server.models.LockInDetail` records. No
HTTP, no row/feature data, no writes. Lock-in ``kind`` strings match the verdict
registry keys (``utility-network``, ``parcel-fabric``, ``lrs``).
"""

from __future__ import annotations

from typing import Any

from .models import LockInDetail

__all__ = ["enumerate_lock_ins"]

# Lock-in kinds, matching honua_esri_assess.verdict.registry keys.
KIND_UTILITY_NETWORK = "utility-network"
KIND_PARCEL_FABRIC = "parcel-fabric"
KIND_LRS = "lrs"

# Service types that *are* a lock-in surface regardless of capability tokens.
_UN_SERVICE_TYPES = frozenset({"UtilityNetworkServer"})
_PARCEL_SERVICE_TYPES = frozenset({"ParcelFabricServer"})
_LRS_SERVICE_TYPES = frozenset({"LRServer"})

# Capability tokens (lower-cased) that imply each lock-in.
_UN_TOKENS = frozenset({"utilitynetwork", "utilitynetworkversionmanagement"})
_PARCEL_TOKENS = frozenset({"parcelfabric"})
_LRS_TOKENS = frozenset({"lrs", "linearreferencing", "locationreferencing"})


def enumerate_lock_ins(
    body: dict[str, Any],
    *,
    service_type: str | None = None,
    layer_count: int | None = None,
) -> tuple[LockInDetail, ...]:
    """Return the hard lock-ins a service body advertises, with extent.

    Parameters
    ----------
    body:
        The already-fetched service metadata JSON (a deep-probe body). Only
        documented read-only fields are read.
    service_type:
        Raw Esri ``serviceType`` string; used as a fallback signal for the
        dedicated lock-in server types (``UtilityNetworkServer``, ...).
    layer_count:
        Number of layers observed for the service. Used as the feature-class
        extent when the body does not carry an explicit controller-dataset
        layer list. Falls back to the body's own ``layers`` length.
    """

    tokens = _capability_tokens(body)
    controller = _controller_dataset_layers(body)
    fallback_fc = layer_count if layer_count is not None else _layer_len(body)

    lock_ins: list[LockInDetail] = []

    if _has_utility_network(body, controller, tokens, service_type):
        lock_ins.append(
            LockInDetail(
                kind=KIND_UTILITY_NETWORK,
                feature_class_count=_un_feature_class_count(controller, fallback_fc),
                domain_network_count=_un_domain_network_count(body, controller),
                rule_count=_un_rule_count(body, controller),
            )
        )

    if _has_parcel_fabric(body, controller, tokens, service_type):
        lock_ins.append(
            LockInDetail(
                kind=KIND_PARCEL_FABRIC,
                feature_class_count=_parcel_feature_class_count(controller, fallback_fc),
            )
        )

    if _has_lrs(body, tokens, service_type):
        lock_ins.append(
            LockInDetail(
                kind=KIND_LRS,
                network_count=_lrs_network_count(body),
            )
        )

    return tuple(lock_ins)


# --- detection -------------------------------------------------------------


def _has_utility_network(
    body: dict[str, Any],
    controller: dict[str, Any],
    tokens: frozenset[str],
    service_type: str | None,
) -> bool:
    if service_type in _UN_SERVICE_TYPES:
        return True
    if _has_id(controller, "utilityNetworkLayerId"):
        return True
    if _nonempty_list(controller.get("utilityNetworkLayers")):
        return True
    return bool(tokens & _UN_TOKENS)


def _has_parcel_fabric(
    body: dict[str, Any],
    controller: dict[str, Any],
    tokens: frozenset[str],
    service_type: str | None,
) -> bool:
    if service_type in _PARCEL_SERVICE_TYPES:
        return True
    if _has_id(controller, "parcelFabricLayerId"):
        return True
    if _nonempty_list(controller.get("parcelLayers")):
        return True
    return bool(tokens & _PARCEL_TOKENS)


def _has_lrs(
    body: dict[str, Any],
    tokens: frozenset[str],
    service_type: str | None,
) -> bool:
    if service_type in _LRS_SERVICE_TYPES:
        return True
    if isinstance(body.get("lrs"), dict):
        return True
    return bool(tokens & _LRS_TOKENS)


# --- extent ----------------------------------------------------------------


def _un_feature_class_count(controller: dict[str, Any], fallback: int | None) -> int | None:
    layers = controller.get("layers")
    if isinstance(layers, list):
        return sum(1 for entry in layers if isinstance(entry, dict))
    return fallback


def _un_domain_network_count(
    body: dict[str, Any],
    controller: dict[str, Any],
) -> int | None:
    for source in (controller, body):
        networks = source.get("domainNetworks")
        if isinstance(networks, list):
            return sum(1 for entry in networks if isinstance(entry, dict))
    return None


def _un_rule_count(body: dict[str, Any], controller: dict[str, Any]) -> int | None:
    for source in (controller, body):
        rules = source.get("rules")
        if isinstance(rules, list):
            return sum(1 for entry in rules if isinstance(entry, dict))
    return None


def _parcel_feature_class_count(
    controller: dict[str, Any],
    fallback: int | None,
) -> int | None:
    layers = controller.get("parcelLayers")
    if isinstance(layers, list):
        return sum(1 for entry in layers if isinstance(entry, dict))
    return fallback


def _lrs_network_count(body: dict[str, Any]) -> int | None:
    lrs = body.get("lrs")
    if isinstance(lrs, dict):
        networks = lrs.get("networkLayers")
        if isinstance(networks, list):
            return sum(1 for entry in networks if isinstance(entry, dict))
    networks = body.get("networkLayers")
    if isinstance(networks, list):
        return sum(1 for entry in networks if isinstance(entry, dict))
    return None


# --- helpers ---------------------------------------------------------------


def _capability_tokens(body: dict[str, Any]) -> frozenset[str]:
    raw = body.get("capabilities")
    tokens: set[str] = set()
    if isinstance(raw, str):
        tokens.update(part.strip().lower() for part in raw.split(",") if part.strip())
    elif isinstance(raw, list):
        for part in raw:
            if isinstance(part, str) and part.strip():
                tokens.add(part.strip().lower())
    return frozenset(tokens)


def _controller_dataset_layers(body: dict[str, Any]) -> dict[str, Any]:
    controller = body.get("controllerDatasetLayers")
    if isinstance(controller, dict):
        return controller
    return {}


def _has_id(source: dict[str, Any], key: str) -> bool:
    value = source.get(key)
    return isinstance(value, int) and not isinstance(value, bool)


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _layer_len(body: dict[str, Any]) -> int | None:
    layers = body.get("layers")
    if isinstance(layers, list):
        return sum(1 for entry in layers if isinstance(entry, dict))
    return None
