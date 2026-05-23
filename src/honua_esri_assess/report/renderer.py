"""Markdown readiness report renderer for EsriFootprint v0.1 dictionaries."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from honua_esri_assess.diagnostics import ReportRenderError

from .formatting import bullet_list, count, markdown_table, plural, text
from .heuristics import (
    diagnostics,
    item_kind_label,
    item_label,
    item_sort_key,
    item_source_label,
    item_type_label,
    inventory_items,
    manual_review_items,
    recommended_order,
    score_complexity,
    source_label,
    total_feature_class_count,
    total_inventory_count,
    total_layer_count,
)
from .models import ComplexityThresholds


@dataclass(frozen=True)
class RenderOptions:
    include_diagnostics: bool = True
    max_inventory_rows: int | None = None
    complexity_thresholds: ComplexityThresholds = field(default_factory=ComplexityThresholds)
    schema_warnings: tuple[str, ...] = ()


def render(footprint: Mapping[str, Any], *, options: RenderOptions | None = None) -> str:
    """Render an EsriFootprint v0.1 dictionary to deterministic Markdown.

    The renderer performs no file, network, or logging I/O. Validation and
    reading/writing are intentionally handled by the CLI layer.
    """

    if not isinstance(footprint, Mapping):
        raise ReportRenderError("Report renderer expected a footprint object.")

    options = options or RenderOptions()
    parts = [
        _render_header(footprint),
        _render_schema_warnings(options.schema_warnings),
        _render_inventory(footprint, options),
        _render_layer_count(footprint),
        _render_complexity(footprint, options),
        _render_manual_review(footprint),
        _render_migration_ordering(footprint),
    ]
    if options.include_diagnostics:
        parts.append(_render_diagnostics_summary(footprint))
    return "\n\n".join(part.rstrip() for part in parts if part.strip()) + "\n"


def _render_header(footprint: Mapping[str, Any]) -> str:
    source = footprint.get("source", {})
    if not isinstance(source, Mapping):
        source = {}
    tool = footprint.get("tool", {})
    if not isinstance(tool, Mapping):
        tool = {}

    rows = [
        ("Schema version", text(footprint.get("schemaVersion"))),
        ("Generated at", text(footprint.get("generatedAt"))),
        ("Source", source_label(source.get("kind"))),
        ("Source locator", text(source.get("locator"))),
        ("Source captured at", text(source.get("capturedAt"))),
        ("Scanner", f"{text(tool.get('name'))} {text(tool.get('version'))}"),
    ]
    return "# Honua Esri Readiness Report\n\n" + markdown_table(("Field", "Value"), rows)


def _render_schema_warnings(warnings: Sequence[str]) -> str:
    if not warnings:
        return ""
    return "## Schema Warnings\n\n" + bullet_list(sorted(warnings))


def _render_inventory(footprint: Mapping[str, Any], options: RenderOptions) -> str:
    items = sorted(inventory_items(footprint), key=item_sort_key)
    total = len(items)
    if options.max_inventory_rows is not None:
        visible_items = items[: max(options.max_inventory_rows, 0)]
    else:
        visible_items = items
    hidden = total - len(visible_items)

    lines = ["## Service Inventory"]
    if not items:
        return "\n\n".join([*lines, "No inventory entries were captured."])

    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for item in visible_items:
        grouped[(item_source_label(item, footprint), item_kind_label(item))].append(item)

    for (source, kind), group_items in sorted(grouped.items()):
        lines.append(f"### {source} / {kind}")
        lines.append(_inventory_table(kind, group_items))

    if hidden > 0:
        lines.append(
            f"{plural(hidden, 'inventory record')} hidden by the report row limit; "
            "see `EsriFootprint.json` for the full inventory."
        )
    return "\n\n".join(lines)


def _inventory_table(kind: str, items: Sequence[Mapping[str, Any]]) -> str:
    if kind == "portal-item":
        rows = [
            (
                item_label(item),
                item.get("type"),
                item.get("owner"),
                item.get("sharing"),
                item.get("modified"),
            )
            for item in items
        ]
        return markdown_table(("Item", "Type", "Owner", "Sharing", "Modified"), rows)
    if kind == "server-service":
        rows = [
            (
                item_label(item),
                item.get("serviceType"),
                item.get("folder", ""),
                count(item.get("layerCount")),
                _spatial_reference_label(item.get("sr")),
            )
            for item in items
        ]
        return markdown_table(("Service", "Type", "Folder", "Layers", "Spatial reference"), rows)
    if kind == "filegdb-feature-class":
        rows = [
            (
                item_label(item),
                item.get("geometryType"),
                count(item.get("featureCount")),
                _spatial_reference_label(item.get("sr")),
                _field_count(item.get("fields")),
            )
            for item in items
        ]
        return markdown_table(
            ("Feature class", "Geometry", "Features", "Spatial reference", "Fields"),
            rows,
        )

    rows = [
        (item_label(item), item.get("kind"), item_type_label(item), _item_detail(item))
        for item in items
    ]
    return markdown_table(("Item", "Kind", "Type", "Details"), rows)


def _render_layer_count(footprint: Mapping[str, Any]) -> str:
    rows = _layer_breakdown_rows(footprint)
    lines = [
        "## Layer Count",
        bullet_list(
            (
                f"Inventory records: **{total_inventory_count(footprint)}**.",
                f"Server service layers: **{total_layer_count(footprint)}**.",
                f"FileGDB feature classes: **{total_feature_class_count(footprint)}**.",
            )
        ),
    ]
    if rows:
        lines.append(markdown_table(("Source", "Type", "Records", "Layers"), rows))
    else:
        lines.append("No source or service-type breakdown was available.")
    return "\n\n".join(lines)


def _layer_breakdown_rows(footprint: Mapping[str, Any]) -> list[tuple[Any, Any, Any, Any]]:
    rows: list[tuple[Any, Any, Any, Any]] = []
    portal = footprint.get("portal")
    if isinstance(portal, Mapping):
        item_counts = portal.get("itemCounts")
        if isinstance(item_counts, Mapping):
            for item_type, value in sorted(item_counts.items(), key=lambda entry: str(entry[0])):
                rows.append(("ArcGIS Online", item_type, count(value), "-"))

    server = footprint.get("server")
    if isinstance(server, Mapping):
        service_counts = server.get("serviceCounts")
        layer_counts: Counter[str] = Counter()
        for item in inventory_items(footprint):
            if item.get("kind") == "server-service":
                layer_counts[str(item.get("serviceType") or "Unknown")] += count(
                    item.get("layerCount")
                )
        if isinstance(service_counts, Mapping):
            for service_type, value in sorted(service_counts.items(), key=lambda entry: str(entry[0])):
                rows.append(
                    (
                        "ArcGIS Server",
                        service_type,
                        count(value),
                        layer_counts[str(service_type)],
                    )
                )
        elif layer_counts:
            service_totals = Counter(
                str(item.get("serviceType") or "Unknown")
                for item in inventory_items(footprint)
                if item.get("kind") == "server-service"
            )
            for service_type in sorted(service_totals):
                rows.append(
                    (
                        "ArcGIS Server",
                        service_type,
                        service_totals[service_type],
                        layer_counts[service_type],
                    )
                )

    filegdb = footprint.get("filegdb")
    if isinstance(filegdb, Mapping):
        rows.append(
            (
                "FileGDB",
                "Feature class",
                count(filegdb.get("featureClassCount")),
                "-",
            )
        )

    if not rows:
        derived_counts = Counter(
            (item_source_label(item, footprint), item_type_label(item))
            for item in inventory_items(footprint)
        )
        for (source, item_type), value in sorted(derived_counts.items()):
            rows.append((source, item_type, value, "-"))
    return rows


def _render_complexity(footprint: Mapping[str, Any], options: RenderOptions) -> str:
    score = score_complexity(footprint, options.complexity_thresholds)
    return (
        "## Complexity Estimate\n\n"
        f"**Bucket:** {score.bucket}\n\n"
        + bullet_list(score.rationale)
    )


def _render_manual_review(footprint: Mapping[str, Any]) -> str:
    review_items = manual_review_items(footprint)
    lines = ["## Manual Review Items"]
    if not review_items:
        lines.append("No inventory entries were flagged by the v0.1 review heuristics.")
        return "\n\n".join(lines)
    rows = [
        (entry.reason_code, entry.item_label, entry.detail)
        for entry in sorted(review_items, key=lambda item: item.sort_key)
    ]
    lines.append(markdown_table(("Reason code", "Item", "Details"), rows))
    return "\n\n".join(lines)


def _render_migration_ordering(footprint: Mapping[str, Any]) -> str:
    groups = recommended_order(footprint)
    lines = ["## Migration Ordering"]
    if not groups:
        lines.append("No migration steps could be derived from the inventory.")
        return "\n\n".join(lines)

    for index, group in enumerate(groups, start=1):
        lines.append(f"{index}. **{group.title}** - {group.justification}")
        lines.extend(f"   - {item_label(item)}" for item in group.items)
    return "\n".join(lines)


def _render_diagnostics_summary(footprint: Mapping[str, Any]) -> str:
    entries = diagnostics(footprint)
    lines = ["## Diagnostics Summary"]
    if not entries:
        lines.append("No diagnostics were captured.")
        return "\n\n".join(lines)

    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for entry in entries:
        grouped[(str(entry.get("severity") or "info"), str(entry.get("code") or "unknown"))].append(
            entry
        )

    rows = []
    for (severity, code_value), grouped_entries in sorted(
        grouped.items(), key=lambda entry: (_severity_rank(entry[0][0]), entry[0][1])
    ):
        scopes = sorted({str(entry.get("scope") or "-") for entry in grouped_entries})
        rows.append((severity, code_value, len(grouped_entries), ", ".join(scopes)))
    lines.append(markdown_table(("Severity", "Code", "Count", "Scopes"), rows))

    detail_lines = []
    for entry in sorted(entries, key=lambda item: (_severity_rank(str(item.get("severity"))), str(item.get("code")), str(item.get("scope")))):
        hint = entry.get("hint")
        detail = (
            f"- {text(entry.get('severity'))} / {text(entry.get('code'))} "
            f"({text(entry.get('scope'))}): {text(entry.get('message'))}"
        )
        if hint:
            detail += f" Hint: {text(hint)}"
        detail_lines.append(detail)
    lines.append("Details:\n" + "\n".join(detail_lines))
    return "\n\n".join(lines)


def _spatial_reference_label(sr: Any) -> str:
    if not isinstance(sr, Mapping):
        return "-"
    if sr.get("wkid") not in (None, ""):
        return f"WKID {sr['wkid']}"
    if sr.get("latestWkid") not in (None, ""):
        return f"Latest WKID {sr['latestWkid']}"
    if sr.get("wkt"):
        return "WKT"
    return "-"


def _item_detail(item: Mapping[str, Any]) -> str:
    for key in ("id", "serviceUrl", "name"):
        if item.get(key):
            return str(item[key])
    return "-"


def _field_count(fields: Any) -> int:
    if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
        return len(fields)
    return 0


def _severity_rank(severity: str) -> int:
    return {"error": 0, "warn": 1, "info": 2}.get(severity, 9)
