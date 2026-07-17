"""Crosswalk footprint-detected assess-registry capabilities to Honua keys.

Reuses the same deterministic, heuristic detection the migratability verdict
engine uses (:mod:`honua_esri_assess.verdict.registry`): it matches on portal
item ``type``, server ``serviceType``, and per-service ``capabilities``
tokens already present in ``EsriFootprint.json``. No network calls are made;
this module performs no file, network, or logging I/O.

Honesty invariant (issue #84): every esri-assess-registry key the footprint's
inventory triggers ends up in exactly one place in :class:`CapsResult` --
either aggregated into a mapped :class:`CapabilityMatch`, or listed in
``unmapped`` with a reason of ``"unmapped"`` (crosswalk maps it to an empty
list -- known, not yet mapped) or ``"not-supported"`` (crosswalk maps it to
``null``). A registry key detected in the footprint can never simply vanish.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from honua_esri_assess.report.heuristics import inventory_items
from honua_esri_assess.verdict.registry import CAPABILITY_REGISTRY, TIER_RANK, matches

from .crosswalk import Crosswalk


@dataclass(frozen=True)
class CapabilityMatch:
    """One Honua capability key mapped from one or more assess-registry keys."""

    key: str
    assess_keys: tuple[str, ...]
    matched_inventory_count: int
    tier: str


@dataclass(frozen=True)
class UnmappedCapability:
    """An assess-registry key the crosswalk does not map to a capability key."""

    assess_key: str
    matched_inventory_count: int
    tier: str
    reason: str  # "unmapped" | "not-supported"


@dataclass(frozen=True)
class CapsResult:
    """The full crosswalk result for a footprint."""

    capabilities: tuple[CapabilityMatch, ...]
    unmapped: tuple[UnmappedCapability, ...]
    units_estimate: int | None
    detected_assess_keys: tuple[str, ...]


def _detected_counts_and_tiers(
    footprint: Mapping[str, Any],
) -> tuple[dict[str, int], dict[str, str]]:
    items = inventory_items(footprint)
    counts: dict[str, int] = {}
    tiers: dict[str, str] = {}
    for entry in CAPABILITY_REGISTRY:
        matched_count = sum(1 for item in items if matches(entry, item))
        if matched_count:
            counts[entry.key] = matched_count
            tiers[entry.key] = entry.tier
    return counts, tiers


def _units_estimate(footprint: Mapping[str, Any]) -> int | None:
    """Serving-unit estimate derived from the server facet, where available.

    Prefers the federation topology's server count (``portal.federation.
    servers``, each a distinct host/instance) when present -- this is the
    most direct "host/instance count" the footprint carries. Falls back to
    ``1`` when the footprint itself is a direct ArcGIS Server scan (a single
    host was scanned). Returns ``None`` (omitted from the URL and JSON, never
    reported as zero) when neither signal is present.
    """

    portal = footprint.get("portal")
    if isinstance(portal, Mapping):
        federation = portal.get("federation")
        if isinstance(federation, Mapping):
            servers = federation.get("servers")
            if isinstance(servers, (list, tuple)):
                server_count = sum(1 for server in servers if isinstance(server, Mapping))
                if server_count:
                    return server_count

    source = footprint.get("source")
    if isinstance(source, Mapping) and source.get("kind") == "arcgis-server":
        return 1

    return None


def evaluate(footprint: Mapping[str, Any], crosswalk: Crosswalk) -> CapsResult:
    """Crosswalk a footprint's detected capabilities to Honua capability keys."""

    counts, tiers = _detected_counts_and_tiers(footprint)

    accum: dict[str, dict[str, Any]] = {}
    unmapped: list[UnmappedCapability] = []
    for assess_key in sorted(counts):
        mapped = crosswalk.capability_keys_for(assess_key)
        count = counts[assess_key]
        tier = tiers[assess_key]
        if mapped is None:
            unmapped.append(
                UnmappedCapability(
                    assess_key=assess_key,
                    matched_inventory_count=count,
                    tier=tier,
                    reason="not-supported",
                )
            )
            continue
        if len(mapped) == 0:
            unmapped.append(
                UnmappedCapability(
                    assess_key=assess_key,
                    matched_inventory_count=count,
                    tier=tier,
                    reason="unmapped",
                )
            )
            continue
        for capability_key in mapped:
            bucket = accum.setdefault(
                capability_key,
                {"assess_keys": set(), "count": 0, "tier": "go"},
            )
            bucket["assess_keys"].add(assess_key)
            bucket["count"] += count
            if TIER_RANK[tier] > TIER_RANK[bucket["tier"]]:
                bucket["tier"] = tier

    capabilities = tuple(
        CapabilityMatch(
            key=capability_key,
            assess_keys=tuple(sorted(bucket["assess_keys"])),
            matched_inventory_count=bucket["count"],
            tier=bucket["tier"],
        )
        for capability_key, bucket in sorted(accum.items())
    )

    return CapsResult(
        capabilities=capabilities,
        unmapped=tuple(unmapped),
        units_estimate=_units_estimate(footprint),
        detected_assess_keys=tuple(sorted(counts)),
    )


__all__ = [
    "CapabilityMatch",
    "CapsResult",
    "UnmappedCapability",
    "evaluate",
]
