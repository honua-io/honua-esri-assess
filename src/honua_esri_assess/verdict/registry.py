"""Capability registry mapping Esri footprint signals to migratability tiers.

The registry is the static source of truth that the verdict engine consults.
Each :class:`CapabilityEntry` describes a capability Honua either supports
(``go``), supports with caveats / partial fidelity (``conditional``), or cannot
take today (``no-go``). The ``no-go`` tier covers the hard Esri lock-ins
(Utility Network, Parcel Fabric, Linear Referencing / LRS) that must always be
surfaced as explicit boundaries and never silently dropped.

Detection is heuristic and deterministic: it matches on portal item ``type``
strings, server ``serviceType`` strings, per-service ``capabilities`` tokens,
and feature-class hints already present in ``EsriFootprint.json``. No network
calls are made — the registry only reads the offline artifact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

Tier = Literal["go", "conditional", "no-go"]

# Ranking helper: a lower number is a more confident "yes".
TIER_RANK: dict[str, int] = {"go": 0, "conditional": 1, "no-go": 2}

# Shop profiles the verdict is rendered for. Order is stable for output.
SHOP_PROFILES: tuple[str, ...] = (
    "web-map-and-services",
    "editing-heavy",
    "raster/imagery",
    "3d",
    "utility",
    "gov",
)


@dataclass(frozen=True)
class CapabilityEntry:
    """A single capability the registry can detect in a footprint.

    Attributes:
        key: Stable identifier used in tests and output.
        label: Human-readable capability name.
        tier: Migratability tier for this capability.
        portal_types: Portal item ``type`` strings that imply this capability.
        server_types: Server ``serviceType`` strings that imply this capability.
        capability_tokens: Per-service ``capabilities`` tokens (case-insensitive)
            that imply this capability.
        hard_lock_in: When true, this capability is an Esri hard lock-in that
            must be surfaced as an explicit boundary even on a "go"/"conditional"
            shop verdict (never silently dropped).
        boundary: Plain-language description of the migration boundary, used when
            the capability is ``conditional`` or ``no-go``.
        profiles: Shop profiles this capability is most relevant to. Empty means
            it is relevant to every profile.
    """

    key: str
    label: str
    tier: Tier
    portal_types: frozenset[str] = field(default_factory=frozenset)
    server_types: frozenset[str] = field(default_factory=frozenset)
    capability_tokens: frozenset[str] = field(default_factory=frozenset)
    hard_lock_in: bool = False
    boundary: str = ""
    profiles: frozenset[str] = field(default_factory=frozenset)


def _ci(values: Iterable[str]) -> frozenset[str]:
    return frozenset(value.lower() for value in values)


# The capability registry. Entries are evaluated in declaration order; the most
# severe tier a footprint triggers determines a profile's verdict.
CAPABILITY_REGISTRY: tuple[CapabilityEntry, ...] = (
    # --- go: first-class supported surface -------------------------------
    CapabilityEntry(
        key="web-map",
        label="Web maps",
        tier="go",
        portal_types=frozenset({"Web Map", "Web Scene"}),
        profiles=frozenset({"web-map-and-services", "gov"}),
    ),
    CapabilityEntry(
        key="feature-service",
        label="Hosted feature services",
        tier="go",
        portal_types=frozenset({"Feature Service"}),
        server_types=frozenset({"FeatureServer"}),
        profiles=frozenset({"web-map-and-services", "editing-heavy", "gov"}),
    ),
    CapabilityEntry(
        key="map-service",
        label="Map services",
        tier="go",
        server_types=frozenset({"MapServer"}),
        profiles=frozenset({"web-map-and-services", "gov"}),
    ),
    CapabilityEntry(
        key="vector-tiles",
        label="Vector tile services",
        tier="go",
        portal_types=frozenset({"Vector Tile Service"}),
        server_types=frozenset({"VectorTileServer"}),
        profiles=frozenset({"web-map-and-services"}),
    ),
    CapabilityEntry(
        key="editing",
        label="Feature editing / sync",
        tier="go",
        capability_tokens=_ci({"Editing", "Sync", "Create", "Update", "Delete"}),
        profiles=frozenset({"editing-heavy"}),
    ),
    # --- conditional: supported with caveats / partial fidelity ----------
    CapabilityEntry(
        key="image-service",
        label="Image services / raster",
        tier="conditional",
        portal_types=frozenset({"Image Service"}),
        server_types=frozenset({"ImageServer"}),
        capability_tokens=_ci({"Image"}),
        boundary=(
            "Raster/imagery services migrate with conditional fidelity; mosaic "
            "dataset rules and on-the-fly raster functions need review."
        ),
        profiles=frozenset({"raster/imagery"}),
    ),
    CapabilityEntry(
        key="scene-service",
        label="3D scene layers",
        tier="conditional",
        portal_types=frozenset({"Scene Service", "Scene Layer Package"}),
        server_types=frozenset({"SceneServer"}),
        boundary=(
            "3D scene layers migrate conditionally; integrated mesh and building "
            "scene layer (BSL) fidelity needs case-by-case review."
        ),
        profiles=frozenset({"3d"}),
    ),
    CapabilityEntry(
        key="survey123",
        label="Survey123 forms",
        tier="conditional",
        portal_types=frozenset({"Survey123 Form", "Form"}),
        boundary=(
            "Survey123 forms need form-logic re-authoring; submissions migrate "
            "as feature data but the form runtime does not."
        ),
        profiles=frozenset({"editing-heavy", "gov"}),
    ),
    CapabilityEntry(
        key="dashboards-apps",
        label="Dashboards and web apps",
        tier="conditional",
        portal_types=frozenset(
            {"Dashboard", "Experience", "Web Mapping Application", "Web Experience"}
        ),
        boundary=(
            "Dashboards and configurable apps need rebuild on Honua app surfaces; "
            "data migrates but app configuration is re-authored."
        ),
        profiles=frozenset({"web-map-and-services", "gov"}),
    ),
    CapabilityEntry(
        key="geocoding",
        label="Geocoding / locator services",
        tier="conditional",
        portal_types=frozenset({"Geocoding Service", "Locator Package"}),
        server_types=frozenset({"GeocodeServer"}),
        boundary=(
            "Locators are re-pointed to a Honua-supported geocoder; custom "
            "address locators need rebuild."
        ),
        profiles=frozenset({"gov"}),
    ),
    CapabilityEntry(
        key="geoprocessing",
        label="Geoprocessing services",
        tier="conditional",
        portal_types=frozenset({"Geoprocessing Service"}),
        server_types=frozenset({"GPServer"}),
        boundary=(
            "Geoprocessing models are re-authored; published GP tasks do not "
            "transfer as-is."
        ),
    ),
    # --- no-go: hard Esri lock-ins (NEVER silently dropped) --------------
    CapabilityEntry(
        key="utility-network",
        label="Utility Network",
        tier="no-go",
        portal_types=frozenset({"Utility Network", "Trace Network"}),
        server_types=frozenset({"UtilityNetworkServer"}),
        capability_tokens=_ci({"UtilityNetwork", "UtilityNetworkVersionManagement"}),
        hard_lock_in=True,
        boundary=(
            "Utility Network is a hard Esri lock-in: the network topology, rules, "
            "and trace engine do not migrate. Federate-only or no-go."
        ),
        profiles=frozenset({"utility"}),
    ),
    CapabilityEntry(
        key="parcel-fabric",
        label="Parcel Fabric",
        tier="no-go",
        portal_types=frozenset({"Parcel Fabric"}),
        server_types=frozenset({"ParcelFabricServer"}),
        capability_tokens=_ci({"ParcelFabric"}),
        hard_lock_in=True,
        boundary=(
            "Parcel Fabric is a hard Esri lock-in: the fabric topology and record "
            "lineage do not migrate. Parcels move as features only. Federate-only "
            "or no-go."
        ),
        profiles=frozenset({"gov"}),
    ),
    CapabilityEntry(
        key="lrs",
        label="Linear Referencing (LRS)",
        tier="no-go",
        portal_types=frozenset({"LRS Network", "Roads and Highways"}),
        server_types=frozenset({"LRServer"}),
        capability_tokens=_ci({"LRS", "LinearReferencing", "LocationReferencing"}),
        hard_lock_in=True,
        boundary=(
            "Linear Referencing System (LRS) is a hard Esri lock-in: route/measure "
            "calibration and event behaviors do not migrate. Federate-only or no-go."
        ),
        profiles=frozenset({"utility", "gov"}),
    ),
)


HARD_LOCK_IN_KEYS: frozenset[str] = frozenset(
    entry.key for entry in CAPABILITY_REGISTRY if entry.hard_lock_in
)


def matches(entry: CapabilityEntry, item: Mapping[str, Any]) -> bool:
    """Return True when ``item`` exhibits the capability described by ``entry``."""

    kind = item.get("kind")
    if kind == "portal-item":
        item_type = str(item.get("type") or "")
        if item_type in entry.portal_types:
            return True
    if kind == "server-service":
        service_type = str(item.get("serviceType") or "")
        if service_type in entry.server_types:
            return True
    if entry.capability_tokens:
        for token in _item_capability_tokens(item):
            if token in entry.capability_tokens:
                return True
    return False


def _item_capability_tokens(item: Mapping[str, Any]) -> frozenset[str]:
    raw = item.get("capabilities")
    tokens: set[str] = set()
    if isinstance(raw, str):
        tokens.update(part.strip().lower() for part in raw.split(",") if part.strip())
    elif isinstance(raw, Iterable) and not isinstance(raw, (bytes, Mapping)):
        for part in raw:
            if isinstance(part, str) and part.strip():
                tokens.add(part.strip().lower())
    return frozenset(tokens)
