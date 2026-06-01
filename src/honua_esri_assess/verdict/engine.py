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

from honua_esri_assess.report.heuristics import dependency_order

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

# serviceKind buckets (#43) that are first-class feature/map surface. Any other
# serviceKind is "non-feature/map breadth" that widens the migration story.
_FEATURE_MAP_SERVICE_KINDS = frozenset(
    {"featureService", "mapService", "vectorTileService"}
)

# Advanced server roles (#54) whose mere presence changes the migration story.
# Mapped to a one-line migration note surfaced in the rationale.
_ADVANCED_ROLE_NOTES: dict[str, str] = {
    "geoevent": "GeoEvent real-time ingestion has no drop-in Honua equivalent.",
    "geoanalytics": "GeoAnalytics distributed processing must be re-platformed.",
    "notebook": "Notebook Server automation is re-authored, not transferred.",
    "knowledge": "Knowledge Server graph stores need a bespoke migration path.",
}


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
class MigrationStep:
    """One step in the recommended migration order.

    ``rank`` is 1-based. ``requests`` is the observed request volume when the
    step is usage-ranked (#31), and ``None`` when the step came from the
    dependency graph (#42 ``dependencyEdges``) with no usage signal.
    """

    rank: int
    identifier: str
    source: str  # "usage" or "dependency"
    requests: int | None = None


@dataclass(frozen=True)
class SignalSummary:
    """Enriched footprint signals the verdict factors in beyond capability tiers.

    Captures non-feature/map service-type breadth (#43), federated advanced
    server roles (#54), and whether a usage ranking (#31) was available, so the
    renderer and tests can assert the verdict consumed them.
    """

    non_feature_map_service_kinds: tuple[str, ...] = ()
    advanced_roles: tuple[str, ...] = ()
    usage_ranked: bool = False


@dataclass(frozen=True)
class FootprintVerdict:
    """The full verdict across all shop profiles."""

    profiles: tuple[ProfileVerdict, ...]
    hard_lock_ins: tuple[Boundary, ...]
    signals: SignalSummary = SignalSummary()
    migration_order: tuple[MigrationStep, ...] = ()


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


def _non_feature_map_service_kinds(
    footprint: Mapping[str, Any],
) -> tuple[str, ...]:
    """Distinct non-feature/map ``serviceKind`` values present (#43).

    Reads the per-service ``serviceKind`` coarse bucket emitted on server
    inventory items. Feature/map/vector-tile services are excluded; everything
    else (image, geocode, geoprocessing, scene, stream, network-analysis, ...)
    widens the migration story and is returned sorted for stable output.
    """

    kinds: set[str] = set()
    for item in _inventory_items(footprint):
        if item.get("kind") != "server-service":
            continue
        kind = item.get("serviceKind")
        if (
            isinstance(kind, str)
            and kind
            and kind not in _FEATURE_MAP_SERVICE_KINDS
        ):
            kinds.add(kind)
    return tuple(sorted(kinds))


def _advanced_roles(footprint: Mapping[str, Any]) -> tuple[str, ...]:
    """Federated advanced server roles present (#54), sorted and de-duplicated.

    Prefers the rolled-up ``portal.federation.advancedRoles`` union; falls back
    to unioning each federated server's ``advancedRoles`` so an older footprint
    that omits the roll-up still surfaces the signal.
    """

    portal = footprint.get("portal")
    if not isinstance(portal, Mapping):
        return ()
    federation = portal.get("federation")
    if not isinstance(federation, Mapping):
        return ()

    roles: set[str] = set()
    rolled_up = federation.get("advancedRoles")
    if isinstance(rolled_up, (list, tuple)):
        roles.update(role for role in rolled_up if isinstance(role, str) and role)

    servers = federation.get("servers")
    if isinstance(servers, (list, tuple)):
        for server in servers:
            if not isinstance(server, Mapping):
                continue
            server_roles = server.get("advancedRoles")
            if isinstance(server_roles, (list, tuple)):
                roles.update(
                    role for role in server_roles if isinstance(role, str) and role
                )
    return tuple(sorted(roles))


def _usage_ranked_steps(footprint: Mapping[str, Any]) -> tuple[MigrationStep, ...]:
    """Usage-ranked migration steps from ``server.bindingPlan`` (#31).

    Honours the producer's 1-based ``rank``; re-sorts defensively by
    (rank, service) so output is deterministic even if the array arrives
    unsorted. Returns an empty tuple when no usage ranking is present.
    """

    server = footprint.get("server")
    if not isinstance(server, Mapping):
        return ()
    binding_plan = server.get("bindingPlan")
    if not isinstance(binding_plan, Mapping):
        return ()
    ranked = binding_plan.get("usageRankedServices")
    if not isinstance(ranked, (list, tuple)):
        return ()

    rows: list[tuple[int, str, int | None]] = []
    for entry in ranked:
        if not isinstance(entry, Mapping):
            continue
        service = entry.get("service")
        rank = entry.get("rank")
        if not isinstance(service, str) or not service:
            continue
        if not isinstance(rank, int) or isinstance(rank, bool):
            continue
        requests = entry.get("requests")
        if not isinstance(requests, int) or isinstance(requests, bool):
            requests = None
        rows.append((rank, service, requests))

    rows.sort(key=lambda row: (row[0], row[1]))
    return tuple(
        MigrationStep(rank=rank, identifier=service, source="usage", requests=requests)
        for rank, service, requests in rows
    )


def _migration_order(footprint: Mapping[str, Any]) -> tuple[MigrationStep, ...]:
    """Usage-/dependency-driven migration order.

    Prefers usage ranking (#31) when present; otherwise consumes the dependency
    graph (``heuristics.dependency_order``) so dependencies migrate first. The
    two are kept distinct via ``MigrationStep.source`` so callers can tell which
    signal drove the sequence.
    """

    usage = _usage_ranked_steps(footprint)
    if usage:
        return usage

    ordered = dependency_order(footprint)
    return tuple(
        MigrationStep(rank=index + 1, identifier=identifier, source="dependency")
        for index, identifier in enumerate(ordered)
    )


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


def _effort_band(
    profile_entries: tuple[CapabilityEntry, ...],
    verdict: Tier,
    signals: SignalSummary,
) -> str:
    """Derive an effort band from capabilities, the verdict, and enriched signals.

    Beyond the capability-tier count, non-feature/map service-type breadth (#43)
    and federated advanced roles (#54) each lift the band by one step (capped at
    "Very High"), since both widen the migration surface a tier alone misses.
    """

    if verdict == "no-go":
        # A no-go means the lock-in surface dominates the effort story.
        return "Very High"
    conditional_count = sum(1 for entry in profile_entries if entry.tier == "conditional")
    if conditional_count == 0:
        base = "Low"
    elif conditional_count <= 2:
        base = "Moderate"
    else:
        base = "High"

    lift = 0
    if signals.non_feature_map_service_kinds:
        lift += 1
    if signals.advanced_roles:
        lift += 1

    index = min(EFFORT_BANDS.index(base) + lift, len(EFFORT_BANDS) - 1)
    return EFFORT_BANDS[index]


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
    signals: SignalSummary,
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
    if signals.non_feature_map_service_kinds:
        lines.append(
            "Non-feature/map service breadth detected: "
            + ", ".join(signals.non_feature_map_service_kinds)
            + " (widens migration effort beyond capability tiers)."
        )
    if signals.advanced_roles:
        notes = [
            _ADVANCED_ROLE_NOTES.get(role, f"{role} role changes the migration story.")
            for role in signals.advanced_roles
        ]
        lines.append(
            "Federated advanced server roles present: "
            + ", ".join(signals.advanced_roles)
            + ". "
            + " ".join(notes)
        )
    return tuple(lines)


def evaluate(footprint: Mapping[str, Any]) -> FootprintVerdict:
    """Produce the per-profile migratability verdict for a footprint."""

    detected = _detected_entries(footprint)
    extents = _lock_in_extents(footprint)
    migration_order = _migration_order(footprint)
    signals = SignalSummary(
        non_feature_map_service_kinds=_non_feature_map_service_kinds(footprint),
        advanced_roles=_advanced_roles(footprint),
        usage_ranked=any(step.source == "usage" for step in migration_order),
    )

    profile_verdicts: list[ProfileVerdict] = []
    for profile in SHOP_PROFILES:
        profile_entries = _entries_for_profile(profile, detected)
        verdict = _verdict_for_entries(profile_entries)
        effort = _effort_band(profile_entries, verdict, signals)
        boundaries = _boundaries(profile_entries, extents)
        matched = tuple(entry.key for entry in profile_entries)
        rationale = _rationale(profile, verdict, profile_entries, signals)
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
        signals=signals,
        migration_order=migration_order,
    )
