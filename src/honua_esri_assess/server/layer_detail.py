"""Parse a single ArcGIS Server layer's metadata JSON into typed detail.

The layer resource (``.../<FeatureServer|MapServer>/<id>``) exposes a rich,
read-only description of a layer's schema and behavior: fields, coded/range
domains, relationship classes, subtypes, attachments, editor tracking,
renderer/labels/popup presence, definition query, and spatial reference.

This module is pure: it takes the already-fetched JSON body and returns a
:class:`~honua_esri_assess.server.models.LayerDetail`. No HTTP, no row data.
"""

from __future__ import annotations

from typing import Any

from .models import (
    AttributeRulesInfo,
    EditorTracking,
    FieldDetail,
    LayerDetail,
    RelationshipDetail,
    VersioningInfo,
)

__all__ = ["parse_layer_detail"]


def parse_layer_detail(body: dict[str, Any]) -> LayerDetail:
    """Return a :class:`LayerDetail` from a layer metadata JSON body."""

    editor_tracking = _parse_editor_tracking(body)
    tracking_fields = _editor_tracking_field_names(editor_tracking)
    return LayerDetail(
        fields=_parse_fields(body.get("fields"), tracking_fields),
        relationships=_parse_relationships(body.get("relationships")),
        subtype_count=_count_subtypes(body),
        has_attachments=_optional_bool(body.get("hasAttachments")),
        editor_tracking=editor_tracking,
        renderer_type=_renderer_type(body.get("drawingInfo")),
        has_labels=_has_labels(body.get("drawingInfo")),
        has_popups=_has_popups(body),
        definition_query=_definition_query(body),
        spatial_reference=_parse_spatial_reference(body.get("extent")),
        versioning=_parse_versioning(body),
        attribute_rules=_parse_attribute_rules(body),
    )


def _parse_fields(
    value: Any,
    tracking_fields: frozenset[str],
) -> tuple[FieldDetail, ...]:
    if not isinstance(value, list):
        return ()
    fields: list[FieldDetail] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        domain = entry.get("domain")
        domain_type: str | None = None
        domain_name: str | None = None
        if isinstance(domain, dict):
            raw_type = domain.get("type")
            domain_type = _classify_domain_type(raw_type)
            raw_name = domain.get("name")
            domain_name = raw_name if isinstance(raw_name, str) and raw_name else None
        fields.append(
            FieldDetail(
                name=name,
                type=_stringify(entry.get("type")),
                alias=_stringify(entry.get("alias")),
                nullable=_optional_bool(entry.get("nullable")),
                domain_type=domain_type,
                domain_name=domain_name,
                editor_tracking=name in tracking_fields,
            )
        )
    return tuple(fields)


def _classify_domain_type(raw_type: Any) -> str | None:
    if not isinstance(raw_type, str):
        return None
    lowered = raw_type.lower()
    if "codedvalue" in lowered:
        return "coded"
    if "range" in lowered:
        return "range"
    if "inherited" in lowered:
        return "inherited"
    return raw_type


def _parse_relationships(value: Any) -> tuple[RelationshipDetail, ...]:
    if not isinstance(value, list):
        return ()
    relationships: list[RelationshipDetail] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        relationships.append(
            RelationshipDetail(
                id=_optional_int(entry.get("id")),
                name=_stringify(entry.get("name")),
                related_table_id=_optional_int(entry.get("relatedTableId")),
                cardinality=_stringify(entry.get("cardinality")),
                role=_stringify(entry.get("role")),
            )
        )
    return tuple(relationships)


def _count_subtypes(body: dict[str, Any]) -> int:
    subtypes = body.get("subtypes")
    if isinstance(subtypes, list):
        return sum(1 for entry in subtypes if isinstance(entry, dict))
    return 0


def _parse_editor_tracking(body: dict[str, Any]) -> EditorTracking | None:
    info = body.get("editFieldsInfo")
    if not isinstance(info, dict):
        # Some layers advertise the toggle without the field block.
        enabled = body.get("editorTrackingEnabled")
        if isinstance(enabled, bool):
            return EditorTracking(enabled=enabled)
        return None
    return EditorTracking(
        enabled=True,
        creator_field=_stringify(info.get("creatorField")),
        creation_date_field=_stringify(info.get("creationDateField")),
        editor_field=_stringify(info.get("editorField")),
        edit_date_field=_stringify(info.get("editDateField")),
    )


def _editor_tracking_field_names(
    editor_tracking: EditorTracking | None,
) -> frozenset[str]:
    if editor_tracking is None:
        return frozenset()
    names = {
        editor_tracking.creator_field,
        editor_tracking.creation_date_field,
        editor_tracking.editor_field,
        editor_tracking.edit_date_field,
    }
    return frozenset(name for name in names if name)


def _renderer_type(drawing_info: Any) -> str | None:
    if not isinstance(drawing_info, dict):
        return None
    renderer = drawing_info.get("renderer")
    if not isinstance(renderer, dict):
        return None
    return _stringify(renderer.get("type"))


def _has_labels(drawing_info: Any) -> bool | None:
    if not isinstance(drawing_info, dict):
        return None
    label_info = drawing_info.get("labelingInfo")
    if isinstance(label_info, list):
        return len(label_info) > 0
    return None


def _has_popups(body: dict[str, Any]) -> bool | None:
    popup = body.get("popupInfo") or body.get("htmlPopupType")
    if popup is None:
        return None
    if isinstance(popup, str):
        # esriServerHTMLPopupTypeNone means popups are disabled.
        return "none" not in popup.lower()
    return bool(popup)


def _definition_query(body: dict[str, Any]) -> str | None:
    for key in ("definitionExpression", "definitionQuery"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _parse_versioning(body: dict[str, Any]) -> VersioningInfo | None:
    """Normalize traditional/branch versioning hints from layer metadata.

    Reads only documented, read-only layer fields (``isDataBranchVersioned``,
    ``isDataVersioned``, ``isDataArchived``). No version-management/admin
    endpoints are consulted. Branch versioning wins over traditional when both
    are advertised. Returns ``None`` when no versioning hint is present so the
    additive block is omitted entirely.
    """

    branch = _optional_bool(body.get("isDataBranchVersioned"))
    traditional = _optional_bool(body.get("isDataVersioned"))
    archived = _optional_bool(body.get("isDataArchived"))

    mode: str | None = None
    if branch:
        mode = "branch"
    elif traditional:
        mode = "traditional"
    elif branch is False or traditional is False:
        # The layer explicitly advertises that its data is not versioned.
        mode = "none"

    if mode is None and archived is None:
        return None
    return VersioningInfo(mode=mode, archived=archived)


def _parse_attribute_rules(body: dict[str, Any]) -> AttributeRulesInfo | None:
    """Summarize attribute-rule presence from read-only layer metadata.

    The layer resource may advertise a ``hasAttributeRules`` flag and, on some
    servers, inline the rules read-only as an ``attributeRules`` array. When
    neither is present, presence is *not determinable* without admin endpoints
    (which this tool does not call), so the block is omitted rather than
    asserting absence.
    """

    rules = body.get("attributeRules")
    count: int | None = None
    if isinstance(rules, list):
        count = sum(1 for entry in rules if isinstance(entry, dict))

    present = _optional_bool(body.get("hasAttributeRules"))
    if present is None and count is not None:
        present = count > 0

    if present is None and count is None:
        return None
    return AttributeRulesInfo(present=present, count=count)


def _parse_spatial_reference(extent: Any) -> dict[str, Any]:
    if not isinstance(extent, dict):
        return {}
    sr = extent.get("spatialReference")
    if not isinstance(sr, dict):
        return {}
    result: dict[str, Any] = {}
    wkid = sr.get("wkid")
    if isinstance(wkid, int):
        result["wkid"] = wkid
    latest = sr.get("latestWkid")
    if isinstance(latest, int):
        result["latestWkid"] = latest
    wkt = sr.get("wkt")
    if isinstance(wkt, str) and wkt:
        result["wkt"] = wkt
    return result


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
