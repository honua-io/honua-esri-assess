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


def test_parses_versioning_and_attribute_rules() -> None:
    detail = parse_layer_detail(_load("featureserver-watersheds-layer-0.json"))

    # Branch versioning wins over traditional when both are advertised.
    assert detail.versioning is not None
    assert detail.versioning.mode == "branch"
    assert detail.versioning.archived is True

    # hasAttributeRules flag plus an inlined read-only rules array.
    assert detail.attribute_rules is not None
    assert detail.attribute_rules.present is True
    assert detail.attribute_rules.count == 2


def test_traditional_versioning_and_explicit_no_rules() -> None:
    detail = parse_layer_detail(
        {"isDataVersioned": True, "hasAttributeRules": False}
    )
    assert detail.versioning is not None
    assert detail.versioning.mode == "traditional"
    assert detail.versioning.archived is None
    assert detail.attribute_rules is not None
    assert detail.attribute_rules.present is False
    assert detail.attribute_rules.count is None


def test_explicit_unversioned_is_recorded_as_none_mode() -> None:
    detail = parse_layer_detail({"isDataVersioned": False})
    assert detail.versioning is not None
    assert detail.versioning.mode == "none"


def test_attribute_rules_count_implies_presence() -> None:
    detail = parse_layer_detail({"attributeRules": [{"id": 1}, {"id": 2}]})
    assert detail.attribute_rules is not None
    assert detail.attribute_rules.present is True
    assert detail.attribute_rules.count == 2


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
    # No versioning/attribute-rule hints -> not determinable, blocks omitted.
    assert detail.versioning is None
    assert detail.attribute_rules is None


def test_empty_body_yields_empty_detail() -> None:
    detail = parse_layer_detail({})
    assert detail.fields == ()
    assert detail.relationships == ()
    assert detail.has_attachments is None
    assert detail.editor_tracking is None
    assert detail.spatial_reference == {}
    assert detail.versioning is None
    assert detail.attribute_rules is None


def test_html_popup_none_marks_popups_disabled() -> None:
    detail = parse_layer_detail({"htmlPopupType": "esriServerHTMLPopupTypeNone"})
    assert detail.has_popups is False
