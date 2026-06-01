"""Deterministic migratability verdict engine.

Maps an ``EsriFootprint.json`` dictionary plus the capability registry to a
per-shop-profile verdict (``go`` / ``conditional`` / ``no-go``), an effort band,
and an explicit list of named migration boundaries. Hard Esri lock-ins
(Utility Network, Parcel Fabric, LRS) are always surfaced as explicit
boundaries and force a ``no-go`` for any profile that touches them.

The engine performs no file, network, or logging I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .registry import (
    CAPABILITY_REGISTRY,
    SHOP_PROFILES,
    TIER_RANK,
    CapabilityEntry,
    Tier,
    matches,
)

# Effort bands, ordered low to high.
EFFORT_BANDS = ("Low", "Moderate", "High", "Very High")


@dataclass(frozen=True)
class LockInExtent:
    """Aggregated extent of one hard lock-in across the footprint inventory.

    Counts are summed over every service that carries the lock-in. ``services``
    is the number of services exhibiting it. Each count is ``None`` when no
    service advertised that signal, so a missing count is never reported as
    zero extent.
    """

    services: int = 0
    feature_class_count: int | None = None
    domain_network_count: int | None = None
    rule_count: int | None = None
    network_count: int | None = None


@dataclass(frozen=True)
class Boundary:
    """A named migration boundary surfaced on a verdict."""

    key: str
    label: str
    tier: Tier
    hard_lock_in: bool
    detail: str
    extent: LockInExtent | None = None


@dataclass(frozen=True)
class ProfileVerdict:
    """The verdict for a single shop profile."""

    profile: str
    verdict: Tier
    effort: str
    boundaries: tuple[Boundary, ...]
    matched_capabilities: tuple[str, ...]
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class FootprintVerdict:
    """The full verdict across all shop profiles."""

    profiles: tuple[ProfileVerdict, ...]
    hard_lock_ins: tuple[Boundary, ...]


def _inventory_items(footprint: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    inventory = footprint.get("inventory", ())
    if isinstance(inventory, (str, bytes)) or not hasattr(inventory, "__iter__"):
        return ()
    return tuple(item for item in inventory if isinstance(item, Mapping))


def _detected_entries(
    footprint: Mapping[str, Any],
) -> tuple[CapabilityEntry, ...]:
    """Return registry entries the footprint exhibits, in registry order."""

    items = _inventory_items(footprint)
    detected: list[CapabilityEntry] = []
    seen: set[str] = set()
    for entry in CAPABILITY_REGISTRY:
        if entry.key in seen:
            continue
        if any(matches(entry, item) for item in items):
            detected.append(entry)
            seen.add(entry.key)
    return tuple(detected)


def _lock_in_extents(
    footprint: Mapping[str, Any],
) -> dict[str, LockInExtent]:
    """Aggregate enumerated hard lock-in extent (#46) keyed by registry key.

    Reads the additive ``lockIns`` block emitted on server-service inventory
    items. Counts are summed across every service that carries the lock-in;
    a count stays ``None`` until at least one service advertises it.
    """

    accumulators: dict[str, dict[str, Any]] = {}
    for item in _inventory_items(footprint):
        lock_ins = item.get("lockIns")
        if not isinstance(lock_ins, (list, tuple)):
            continue
        for lock_in in lock_ins:
            if not isinstance(lock_in, Mapping):
                continue
            key = lock_in.get("type")
            if not isinstance(key, str) or not key:
                continue
            acc = accumulators.setdefault(key, {"services": 0})
            acc["services"] += 1
            for src, dst in (
                ("featureClassCount", "feature_class_count"),
                ("domainNetworkCount", "domain_network_count"),
                ("ruleCount", "rule_count"),
                ("networkCount", "network_count"),
            ):
                value = lock_in.get(src)
                if isinstance(value, int) and not isinstance(value, bool):
                    acc[dst] = acc.get(dst, 0) + value
    return {
        key: LockInExtent(
            services=acc["services"],
            feature_class_count=acc.get("feature_class_count"),
            domain_network_count=acc.get("domain_network_count"),
            rule_count=acc.get("rule_count"),
            network_count=acc.get("network_count"),
        )
        for key, acc in accumulators.items()
    }


def _format_extent(key: str, extent: LockInExtent) -> str:
    """Render an enumerated lock-in extent as a single appended sentence."""

    parts: list[str] = []
    if key == "lrs":
        if extent.network_count is not None:
            parts.append(f"{extent.network_count} network(s)")
    else:
        if extent.feature_class_count is not None:
            parts.append(f"{extent.feature_class_count} feature class(es)")
        if extent.domain_network_count is not None:
            parts.append(f"{extent.domain_network_count} domain network(s)")
        if extent.rule_count is not None:
            parts.append(f"{extent.rule_count} rule(s)")
    if not parts:
        parts.append(f"{extent.services} service(s)")
    elif extent.services > 1:
        parts.append(f"across {extent.services} services")
    return "Enumerated extent: " + ", ".join(parts) + "."


def _enriched_detail(entry: CapabilityEntry, extent: LockInExtent | None) -> str:
    if extent is None:
        return entry.boundary
    appended = _format_extent(entry.key, extent)
    if not entry.boundary:
        return appended
    return f"{entry.boundary} {appended}"


def _entries_for_profile(
    profile: str,
    detected: tuple[CapabilityEntry, ...],
) -> tuple[CapabilityEntry, ...]:
    """Entries relevant to a profile: profile-scoped plus all hard lock-ins.

    Hard lock-ins are always in scope for every profile so they can never be
    silently dropped, even when a lock-in capability nominally belongs to a
    different profile.
    """

    relevant: list[CapabilityEntry] = []
    for entry in detected:
        scoped = (not entry.profiles) or (profile in entry.profiles)
        if scoped or entry.hard_lock_in:
            relevant.append(entry)
    return tuple(relevant)


def _effort_band(profile_entries: tuple[CapabilityEntry, ...], verdict: Tier) -> str:
    """Derive an effort band from the detected capabilities and the verdict."""

    if verdict == "no-go":
        # A no-go means the lock-in surface dominates the effort story.
        return "Very High"
    conditional_count = sum(1 for entry in profile_entries if entry.tier == "conditional")
    if conditional_count == 0:
        return "Low"
    if conditional_count <= 2:
        return "Moderate"
    return "High"


def _verdict_for_entries(profile_entries: tuple[CapabilityEntry, ...]) -> Tier:
    if not profile_entries:
        return "go"
    worst = max(profile_entries, key=lambda entry: TIER_RANK[entry.tier])
    return worst.tier


def _boundaries(
    profile_entries: tuple[CapabilityEntry, ...],
    extents: Mapping[str, LockInExtent],
) -> tuple[Boundary, ...]:
    boundaries = [
        Boundary(
            key=entry.key,
            label=entry.label,
            tier=entry.tier,
            hard_lock_in=entry.hard_lock_in,
            detail=_enriched_detail(entry, extents.get(entry.key)),
            extent=extents.get(entry.key),
        )
        for entry in profile_entries
        if entry.tier != "go" and entry.boundary
    ]
    # Hard lock-ins first, then by tier severity, then by label for stability.
    boundaries.sort(
        key=lambda boundary: (
            0 if boundary.hard_lock_in else 1,
            -TIER_RANK[boundary.tier],
            boundary.label.lower(),
        )
    )
    return tuple(boundaries)


def _rationale(
    profile: str,
    verdict: Tier,
    profile_entries: tuple[CapabilityEntry, ...],
) -> tuple[str, ...]:
    lock_ins = [entry for entry in profile_entries if entry.hard_lock_in]
    go = [entry for entry in profile_entries if entry.tier == "go"]
    conditional = [entry for entry in profile_entries if entry.tier == "conditional"]

    lines: list[str] = []
    if verdict == "go":
        lines.append(
            "All detected capabilities for this profile are first-class supported."
        )
    elif verdict == "conditional":
        lines.append(
            "Migratable with caveats; one or more capabilities have partial fidelity."
        )
    else:
        lines.append(
            "Blocked by a hard Esri lock-in; federate-only or no-go for this profile."
        )
    if lock_ins:
        names = ", ".join(entry.label for entry in lock_ins)
        lines.append(f"Hard lock-ins present: {names}.")
    if go:
        lines.append("Supported: " + ", ".join(entry.label for entry in go) + ".")
    if conditional:
        lines.append(
            "Conditional fidelity: " + ", ".join(entry.label for entry in conditional) + "."
        )
    if not profile_entries:
        lines.append("No capabilities for this profile were detected in the footprint.")
    return tuple(lines)


def evaluate(footprint: Mapping[str, Any]) -> FootprintVerdict:
    """Produce the per-profile migratability verdict for a footprint."""

    detected = _detected_entries(footprint)
    extents = _lock_in_extents(footprint)

    profile_verdicts: list[ProfileVerdict] = []
    for profile in SHOP_PROFILES:
        profile_entries = _entries_for_profile(profile, detected)
        verdict = _verdict_for_entries(profile_entries)
        effort = _effort_band(profile_entries, verdict)
        boundaries = _boundaries(profile_entries, extents)
        matched = tuple(entry.key for entry in profile_entries)
        rationale = _rationale(profile, verdict, profile_entries)
        profile_verdicts.append(
            ProfileVerdict(
                profile=profile,
                verdict=verdict,
                effort=effort,
                boundaries=boundaries,
                matched_capabilities=matched,
                rationale=rationale,
            )
        )

    hard_lock_ins = tuple(
        Boundary(
            key=entry.key,
            label=entry.label,
            tier=entry.tier,
            hard_lock_in=True,
            detail=_enriched_detail(entry, extents.get(entry.key)),
            extent=extents.get(entry.key),
        )
        for entry in detected
        if entry.hard_lock_in
    )

    return FootprintVerdict(
        profiles=tuple(profile_verdicts),
        hard_lock_ins=hard_lock_ins,
    )
