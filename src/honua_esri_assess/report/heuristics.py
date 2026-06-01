"""Deterministic v0.1 readiness heuristics."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .formatting import count
from .models import ComplexityScore, ComplexityThresholds, OrderingGroup, ReviewItem

COMPLEXITY_BUCKETS = ("Small", "Medium", "Large", "Very Large")

COMPLEX_PORTAL_TYPES = frozenset(
    {
        "Experience",
        "Geocoding Service",
        "Geoprocessing Service",
        "Insights Workbook",
        "Notebook",
        "Solution",
        "Survey123 Form",
        "Workforce Project",
    }
)
MANUAL_REVIEW_PORTAL_TYPES = COMPLEX_PORTAL_TYPES | frozenset({"Locator Package"})
UNKNOWN_PORTAL_TYPES = frozenset({"Other", "Unknown", "Unsupported", "Unsupported Item Type"})
SUPPORTED_SERVER_SERVICE_TYPES = frozenset(
    {"FeatureServer", "ImageServer", "MapServer", "VectorTileServer"}
)
LEGACY_SRS_WKIDS = frozenset({26711, 32040, 102671})

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


def inventory_items(footprint: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    inventory = footprint.get("inventory", ())
    if not isinstance(inventory, Iterable) or isinstance(inventory, (str, bytes)):
        return ()
    return tuple(item for item in inventory if isinstance(item, Mapping))


def diagnostics(footprint: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    entries = footprint.get("diagnostics", ())
    if not isinstance(entries, Iterable) or isinstance(entries, (str, bytes)):
        return ()
    return tuple(entry for entry in entries if isinstance(entry, Mapping))


def dependency_edges(footprint: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return the v0.2 dependency edges, ignored gracefully on v0.1 artifacts."""

    edges = footprint.get("dependencyEdges", ())
    if not isinstance(edges, Iterable) or isinstance(edges, (str, bytes)):
        return ()
    valid: list[Mapping[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = edge.get("from")
        target = edge.get("to")
        if isinstance(source, str) and isinstance(target, str) and source and target:
            valid.append(edge)
    return tuple(valid)


def dependency_order(footprint: Mapping[str, Any]) -> tuple[str, ...]:
    """Return dependency-graph node ids ordered so dependencies migrate first.

    Consumes the v0.2 ``dependencyEdges`` (``from`` depends on ``to``) and runs a
    deterministic Kahn topological sort: every ``to`` node is ordered before the
    ``from`` node that references it. Ties are broken by node id for stable
    output, and any cycle is appended in sorted order rather than dropped so the
    result always covers every referenced node.
    """

    edges = dependency_edges(footprint)
    if not edges:
        return ()

    dependents: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = defaultdict(int)
    nodes: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()
    for edge in edges:
        source = str(edge["from"])
        target = str(edge["to"])
        nodes.add(source)
        nodes.add(target)
        if source == target or (source, target) in seen_edges:
            continue
        seen_edges.add((source, target))
        # "source" depends on "target" -> target must come first.
        dependents[target].add(source)
        indegree[source] += 1

    ready = sorted(node for node in nodes if indegree.get(node, 0) == 0)
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for dependent in sorted(dependents.get(node, ())):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort()

    if len(ordered) < len(nodes):
        ordered.extend(sorted(nodes - set(ordered)))
    return tuple(ordered)


def total_inventory_count(footprint: Mapping[str, Any]) -> int:
    counts_obj = footprint.get("counts", {})
    item_counts = counts_obj.get("items", {}) if isinstance(counts_obj, Mapping) else {}
    if isinstance(item_counts, Mapping):
        counted = sum(count(value) for value in item_counts.values())
        if counted:
            return counted
    return len(inventory_items(footprint))


def total_layer_count(footprint: Mapping[str, Any]) -> int:
    counts = footprint.get("counts", {})
    if isinstance(counts, Mapping):
        return count(counts.get("layers"))
    return 0


def total_feature_class_count(footprint: Mapping[str, Any]) -> int:
    counts = footprint.get("counts", {})
    if isinstance(counts, Mapping):
        counted = count(counts.get("featureClasses"))
        if counted:
            return counted
    return sum(1 for item in inventory_items(footprint) if item.get("kind") == "filegdb-feature-class")


def source_label(source_kind: Any) -> str:
    return {
        "arcgis-online": "ArcGIS Online",
        "arcgis-server": "ArcGIS Server",
        "filegdb": "FileGDB",
    }.get(source_kind, "Unknown source")


def item_source_label(item: Mapping[str, Any], footprint: Mapping[str, Any] | None = None) -> str:
    kind = item.get("kind")
    if kind == "portal-item":
        return "ArcGIS Online"
    if kind == "server-service":
        return "ArcGIS Server"
    if kind == "filegdb-feature-class":
        return "FileGDB"
    if footprint:
        source = footprint.get("source", {})
        if isinstance(source, Mapping):
            return source_label(source.get("kind"))
    return "Unknown source"


def item_kind_label(item: Mapping[str, Any]) -> str:
    return str(item.get("kind") or "unknown-item")


def item_type_label(item: Mapping[str, Any]) -> str:
    kind = item.get("kind")
    if kind == "portal-item":
        return str(item.get("type") or "Unknown")
    if kind == "server-service":
        return str(item.get("serviceType") or "Unknown")
    if kind == "filegdb-feature-class":
        return "Feature class"
    return str(item.get("type") or item.get("serviceType") or "Unknown")


def item_label(item: Mapping[str, Any]) -> str:
    kind = item.get("kind")
    if kind == "portal-item":
        title = str(item.get("title") or item.get("id") or "Untitled item")
        item_id = str(item.get("id") or "").strip()
        if item_id:
            return f"{title} (`{item_id[:8]}`)"
        return title
    if kind == "server-service":
        url = str(item.get("serviceUrl") or "Unnamed service")
        return _service_name_from_url(url)
    if kind == "filegdb-feature-class":
        return str(item.get("name") or "Unnamed feature class")
    return str(item.get("title") or item.get("name") or item.get("id") or "Unnamed item")


def item_sort_key(item: Mapping[str, Any]) -> tuple[str, str, str, str]:
    source_rank = {
        "FileGDB": "0",
        "ArcGIS Server": "1",
        "ArcGIS Online": "2",
    }.get(item_source_label(item), "9")
    kind_rank = {
        "filegdb-feature-class": "0",
        "server-service": "1",
        "portal-item": "2",
    }.get(str(item.get("kind")), "9")
    return (
        source_rank,
        kind_rank,
        item_type_label(item).lower(),
        item_label(item).lower(),
    )


def score_complexity(
    footprint: Mapping[str, Any],
    thresholds: ComplexityThresholds | None = None,
) -> ComplexityScore:
    thresholds = thresholds or ComplexityThresholds()
    items = total_inventory_count(footprint)
    layers = total_layer_count(footprint)
    feature_classes = total_feature_class_count(footprint)
    item_bucket = _bucket_for_value(
        items,
        (
            thresholds.small_items,
            thresholds.medium_items,
            thresholds.large_items,
        ),
    )
    layer_bucket = _bucket_for_value(
        layers,
        (
            thresholds.small_layers,
            thresholds.medium_layers,
            thresholds.large_layers,
        ),
    )
    bucket = max((item_bucket, layer_bucket), key=COMPLEXITY_BUCKETS.index)

    diag_entries = diagnostics(footprint)
    severity_counts = Counter(str(entry.get("severity") or "info") for entry in diag_entries)
    complex_type_set: set[str] = set()
    for item in inventory_items(footprint):
        if item.get("kind") == "portal-item":
            item_type = item_type_label(item)
            if item_type in COMPLEX_PORTAL_TYPES:
                complex_type_set.add(item_type)
    complex_types = sorted(complex_type_set)
    detected_sources = sorted({item_source_label(item) for item in inventory_items(footprint)})

    rationale = [
        f"{items} inventory records fall in the {item_bucket} item-count band.",
        f"{layers} server layers fall in the {layer_bucket} layer-count band.",
        f"{feature_classes} FileGDB feature classes are represented in the inventory roll-up.",
    ]
    if complex_types:
        rationale.append("Complex portal item types present: " + ", ".join(complex_types) + ".")
    if len(detected_sources) >= 2:
        rationale.append("Multiple source families detected: " + ", ".join(detected_sources) + ".")
    if diag_entries:
        ordered_counts = [
            f"{severity_counts[level]} {level}"
            for level in ("error", "warn", "info")
            if severity_counts[level]
        ]
        rationale.append(
            f"{len(diag_entries)} diagnostics captured ({', '.join(ordered_counts)})."
        )
    else:
        rationale.append("No diagnostics were captured.")
    if len(diag_entries) >= 25:
        rationale.append("Diagnostic volume is high enough to warrant extra migration review.")

    return ComplexityScore(bucket=bucket, rationale=tuple(rationale))


def manual_review_items(footprint: Mapping[str, Any]) -> tuple[ReviewItem, ...]:
    scoped_diagnostics = _warn_error_diagnostics_by_scope(footprint)
    review: list[ReviewItem] = []
    seen: set[tuple[str, str, str]] = set()

    for item in inventory_items(footprint):
        label = item_label(item)

        for entry in _diagnostics_for_item(item, scoped_diagnostics):
            code = str(entry.get("code") or "diagnostic")
            severity = str(entry.get("severity") or "warn")
            _add_review_item(
                review,
                seen,
                "flagged-by-diagnostic",
                label,
                f"Diagnostic `{code}` ({severity}) applies to this item.",
            )

        if item.get("kind") == "portal-item":
            item_type = str(item.get("type") or "")
            if item_type in MANUAL_REVIEW_PORTAL_TYPES:
                _add_review_item(
                    review,
                    seen,
                    "complex-item-type",
                    label,
                    f"`{item_type}` usually needs migration planning beyond bulk copy.",
                )
            if item_type in UNKNOWN_PORTAL_TYPES:
                _add_review_item(
                    review,
                    seen,
                    "unknown-item-type",
                    label,
                    "Portal item type was classified as unknown or unsupported.",
                )

        if item.get("kind") == "filegdb-feature-class":
            sr = item.get("sr")
            if not _has_spatial_reference_identifier(sr):
                _add_review_item(
                    review,
                    seen,
                    "missing-spatial-reference",
                    label,
                    "Feature class spatial reference is missing or incomplete.",
                )
            else:
                wkid = _spatial_reference_wkid(sr)
                if wkid in LEGACY_SRS_WKIDS:
                    _add_review_item(
                        review,
                        seen,
                        "legacy-spatial-reference",
                        label,
                        f"Spatial reference WKID `{wkid}` is on the v0.1 legacy watchlist.",
                    )

        if item.get("kind") == "server-service":
            service_type = str(item.get("serviceType") or "Unknown")
            if service_type not in SUPPORTED_SERVER_SERVICE_TYPES:
                _add_review_item(
                    review,
                    seen,
                    "unsupported-service-type",
                    label,
                    f"`{service_type}` is outside the v0.1 supported service set.",
                )

    return tuple(sorted(review, key=lambda item: item.sort_key))


def recommended_order(footprint: Mapping[str, Any]) -> tuple[OrderingGroup, ...]:
    buckets: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for item in inventory_items(footprint):
        buckets[_ordering_rank(item)].append(item)

    groups: list[OrderingGroup] = []
    for rank, title, justification in ORDERING_DEFINITIONS:
        items = tuple(sorted(buckets.get(rank, ()), key=item_sort_key))
        if items:
            groups.append(
                OrderingGroup(
                    rank=rank,
                    title=title,
                    justification=justification,
                    items=items,
                )
            )
    return tuple(groups)


ORDERING_DEFINITIONS = (
    (10, "FileGDB feature classes", "Stage cold data first before dependent services."),
    (20, "ArcGIS Server feature services", "Move authoritative service-backed feature data early."),
    (
        30,
        "ArcGIS Server map and image services",
        "Migrate read-side services after their data sources are staged.",
    ),
    (40, "AGOL hosted feature services", "Move cloud-side authoritative feature services next."),
    (
        50,
        "AGOL hosted tile and vector tile services",
        "Rebuild derived rendering layers after feature services are available.",
    ),
    (60, "AGOL web maps", "Web maps should follow the services they reference."),
    (
        70,
        "AGOL web apps, dashboards, and experiences",
        "Apps and dashboards should follow their web maps and service dependencies.",
    ),
    (
        80,
        "AGOL notebooks, solutions, workforce, survey, and insights",
        "Specialized portal content should be handled late with human review.",
    ),
    (90, "Other or unknown item types", "Triage unknown types before assigning a final sequence."),
)


def _bucket_for_value(value: int, thresholds: tuple[int, int, int]) -> str:
    if value <= thresholds[0]:
        return "Small"
    if value <= thresholds[1]:
        return "Medium"
    if value <= thresholds[2]:
        return "Large"
    return "Very Large"


def _service_name_from_url(url: str) -> str:
    parts = [part for part in url.rstrip("/").split("/") if part]
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return url


def _warn_error_diagnostics_by_scope(
    footprint: Mapping[str, Any],
) -> dict[str, list[Mapping[str, Any]]]:
    scoped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for entry in diagnostics(footprint):
        severity = str(entry.get("severity") or "")
        scope = str(entry.get("scope") or "")
        if severity in {"warn", "error"} and scope:
            scoped[scope].append(entry)
    return scoped


def _diagnostics_for_item(
    item: Mapping[str, Any],
    scoped_diagnostics: Mapping[str, list[Mapping[str, Any]]],
) -> tuple[Mapping[str, Any], ...]:
    matches: list[Mapping[str, Any]] = []
    for scope in _item_scopes(item):
        matches.extend(scoped_diagnostics.get(scope, ()))
    return tuple(sorted(matches, key=_diagnostic_sort_key))


def _item_scopes(item: Mapping[str, Any]) -> tuple[str, ...]:
    values = (
        item.get("id"),
        item.get("title"),
        item.get("serviceUrl"),
        item.get("name"),
    )
    return tuple(str(value) for value in values if value)


def _diagnostic_sort_key(entry: Mapping[str, Any]) -> tuple[int, str, str]:
    return (
        SEVERITY_ORDER.get(str(entry.get("severity") or "info"), 9),
        str(entry.get("code") or ""),
        str(entry.get("scope") or ""),
    )


def _add_review_item(
    review: list[ReviewItem],
    seen: set[tuple[str, str, str]],
    reason_code: str,
    label: str,
    detail: str,
) -> None:
    key = (reason_code, label, detail)
    if key in seen:
        return
    seen.add(key)
    review.append(
        ReviewItem(
            reason_code=reason_code,
            item_label=label,
            detail=detail,
            sort_key=(reason_code, label.lower(), detail.lower()),
        )
    )


def _has_spatial_reference_identifier(sr: Any) -> bool:
    if not isinstance(sr, Mapping):
        return False
    return any(sr.get(key) not in (None, "") for key in ("wkid", "latestWkid", "wkt"))


def _spatial_reference_wkid(sr: Any) -> int | None:
    if not isinstance(sr, Mapping):
        return None
    for key in ("wkid", "latestWkid"):
        value = sr.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _ordering_rank(item: Mapping[str, Any]) -> int:
    kind = item.get("kind")
    if kind == "filegdb-feature-class":
        return 10
    if kind == "server-service":
        service_type = str(item.get("serviceType") or "")
        if service_type == "FeatureServer":
            return 20
        if service_type in {"MapServer", "ImageServer"}:
            return 30
        return 90
    if kind == "portal-item":
        item_type = str(item.get("type") or "")
        if item_type == "Feature Service":
            return 40
        if item_type in {"Tile Service", "Vector Tile Service"}:
            return 50
        if item_type == "Web Map":
            return 60
        if item_type in {"Dashboard", "Experience", "Web Mapping Application"}:
            return 70
        if item_type in MANUAL_REVIEW_PORTAL_TYPES:
            return 80
        return 90
    return 90
