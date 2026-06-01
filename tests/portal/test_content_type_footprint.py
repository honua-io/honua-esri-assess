from __future__ import annotations

from typing import Any, Callable

import responses

from honua_esri_assess import __version__
from honua_esri_assess.footprint.schema import validate_footprint
from honua_esri_assess.footprint.v0_1 import to_footprint_v0_1
from honua_esri_assess.portal import AnonymousCredential, PortalClient, PortalScanner


def _register_content_type_scan(
    responses_module: Any, fixture_json: Callable[[str], dict[str, Any]]
) -> None:
    base = "https://demo.maps.arcgis.com/sharing/rest"
    responses_module.add(
        responses_module.GET,
        f"{base}/portals/self",
        json=fixture_json("portal_self.json"),
        status=200,
    )
    responses_module.add(
        responses_module.GET,
        f"{base}/community/groups",
        json=fixture_json("groups_page_1.json"),
        status=200,
    )
    responses_module.add(
        responses_module.GET,
        f"{base}/search",
        json=fixture_json("search_content_types.json"),
        status=200,
    )


@responses.activate
def test_scanner_classifies_items_by_functional_category(
    fixture_json: Callable[[str], dict[str, Any]],
) -> None:
    _register_content_type_scan(responses, fixture_json)

    client = PortalClient("https://demo.maps.arcgis.com", AnonymousCredential())
    result = PortalScanner(client).scan()

    categories = {item.id: item.content_category for item in result.items}
    assert categories["item-webmap"] == "web-map"
    assert categories["item-dashboard"] == "dashboard"
    assert categories["item-experience"] == "experience-builder"
    assert categories["item-instant"] == "instant-app"
    assert categories["item-wab"] == "web-appbuilder"
    assert categories["item-survey"] == "survey123-form"
    assert categories["item-notebook"] == "notebook"
    assert categories["item-hosted-fl"] == "hosted-feature-layer"
    assert categories["item-referenced-fl"] == "referenced-feature-layer"
    assert categories["item-fieldmaps"] == "field-maps"
    # An item type the classifier does not recognize is recorded explicitly.
    assert categories["item-mystery"] == "unknown"


@responses.activate
def test_footprint_emits_content_type_counts_and_validates(
    fixture_json: Callable[[str], dict[str, Any]],
) -> None:
    _register_content_type_scan(responses, fixture_json)

    client = PortalClient("https://demo.maps.arcgis.com", AnonymousCredential())
    result = PortalScanner(client).scan()

    footprint = to_footprint_v0_1(result, tool_version=__version__)
    validate_footprint(footprint)

    content_type_counts = footprint["portal"]["contentTypeCounts"]
    assert content_type_counts["web-map"] == 1
    assert content_type_counts["experience-builder"] == 1
    assert content_type_counts["survey123-form"] == 1
    assert content_type_counts["hosted-feature-layer"] == 1
    assert content_type_counts["referenced-feature-layer"] == 1
    assert content_type_counts["unknown"] == 1
    # Counts cover every scanned item.
    assert sum(content_type_counts.values()) == len(result.items)

    by_id = {item["id"]: item for item in footprint["inventory"]}
    assert by_id["item-mystery"]["contentCategory"] == "unknown"
    assert by_id["item-survey"]["contentCategory"] == "survey123-form"
    # Additive: the legacy raw item-type breakdown still ships.
    assert footprint["portal"]["itemCounts"]["Web Map"] == 1
