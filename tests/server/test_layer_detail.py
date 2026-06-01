"""Pure parsing of a single layer's metadata JSON into LayerDetail."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.server.layer_detail import parse_layer_detail

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parses_fields_domains_and_editor_tracking() -> None:
    detail = parse_layer_detail(_load("featureserver-watersheds-layer-0.json"))

    by_name = {f.name: f for f in detail.fields}
    assert by_name["STATUS"].domain_type == "coded"
    assert by_name["STATUS"].domain_name == "StatusDomain"
    assert by_name["AREA"].domain_type == "range"
    assert by_name["NAME"].domain_type is None
    assert by_name["OBJECTID"].nullable is False

    # Editor-tracking fields are flagged and the config block is captured.
    assert detail.editor_tracking is not None
    assert detail.editor_tracking.enabled is True
    assert detail.editor_tracking.creator_field == "created_user"
    assert by_name["created_user"].editor_tracking is True
    assert by_name["NAME"].editor_tracking is False


def test_parses_relationships_attachments_subtypes_and_symbology() -> None:
    detail = parse_layer_detail(_load("featureserver-watersheds-layer-0.json"))

    assert detail.has_attachments is True
    assert detail.subtype_count == 2
    assert detail.definition_query == "STATUS = 'active'"
    assert detail.renderer_type == "uniqueValue"
    assert detail.has_labels is True
    assert detail.has_popups is True
    assert detail.spatial_reference == {"wkid": 4326, "latestWkid": 4326}

    assert len(detail.relationships) == 1
    rel = detail.relationships[0]
    assert rel.id == 3
    assert rel.name == "WatershedToOutlets"
    assert rel.related_table_id == 1
    assert rel.cardinality == "esriRelCardinalityOneToMany"
    assert rel.role == "esriRelRoleOrigin"


def test_minimal_layer_has_no_optional_signals() -> None:
    detail = parse_layer_detail(_load("featureserver-watersheds-layer-1.json"))

    assert detail.has_attachments is False
    assert detail.relationships == ()
    assert detail.subtype_count == 0
    assert detail.editor_tracking is None
    assert detail.renderer_type == "simple"
    assert detail.has_labels is None
    assert detail.has_popups is None
    assert detail.definition_query is None
    assert detail.spatial_reference == {"wkid": 3857}


def test_empty_body_yields_empty_detail() -> None:
    detail = parse_layer_detail({})
    assert detail.fields == ()
    assert detail.relationships == ()
    assert detail.has_attachments is None
    assert detail.editor_tracking is None
    assert detail.spatial_reference == {}


def test_html_popup_none_marks_popups_disabled() -> None:
    detail = parse_layer_detail({"htmlPopupType": "esriServerHTMLPopupTypeNone"})
    assert detail.has_popups is False
