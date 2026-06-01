from __future__ import annotations

import pytest

from honua_esri_assess.portal.classification import (
    CATEGORY_DASHBOARD,
    CATEGORY_EXPERIENCE_BUILDER,
    CATEGORY_FIELD_MAPS,
    CATEGORY_HOSTED_FEATURE_LAYER,
    CATEGORY_IMAGE_LAYER,
    CATEGORY_INSTANT_APP,
    CATEGORY_NOTEBOOK,
    CATEGORY_REFERENCED_FEATURE_LAYER,
    CATEGORY_STORYMAP,
    CATEGORY_SURVEY123_FORM,
    CATEGORY_UNKNOWN,
    CATEGORY_VECTOR_TILE_LAYER,
    CATEGORY_WEB_APP,
    CATEGORY_WEB_APPBUILDER,
    CATEGORY_WEB_MAP,
    CATEGORY_WORKFORCE,
    classify_item,
)


@pytest.mark.parametrize(
    ("item_type", "type_keywords", "expected"),
    [
        ("Web Map", ["Web Map"], CATEGORY_WEB_MAP),
        ("Dashboard", ["Dashboard"], CATEGORY_DASHBOARD),
        ("Notebook", ["Notebook"], CATEGORY_NOTEBOOK),
        ("Form", ["Survey123", "Form"], CATEGORY_SURVEY123_FORM),
        ("Workforce Project", ["Workforce Project"], CATEGORY_WORKFORCE),
        ("Image Service", ["Image Service"], CATEGORY_IMAGE_LAYER),
        ("Vector Tile Service", ["Vector Tile Service"], CATEGORY_VECTOR_TILE_LAYER),
        (
            "Web Mapping Application",
            ["Web Mapping Application", "ExperienceBuilder"],
            CATEGORY_EXPERIENCE_BUILDER,
        ),
        (
            "Web Mapping Application",
            ["Web Mapping Application", "instantappsJson"],
            CATEGORY_INSTANT_APP,
        ),
        (
            "Web Mapping Application",
            ["Web Mapping Application", "Web AppBuilder"],
            CATEGORY_WEB_APPBUILDER,
        ),
        (
            "Web Mapping Application",
            ["Web Mapping Application", "FieldMaps"],
            CATEGORY_FIELD_MAPS,
        ),
        (
            "Web Mapping Application",
            ["Web Mapping Application", "Story Map", "storymap"],
            CATEGORY_STORYMAP,
        ),
        (
            "Web Mapping Application",
            ["Web Mapping Application"],
            CATEGORY_WEB_APP,
        ),
        (
            "Feature Service",
            ["Feature Service", "Hosted Service"],
            CATEGORY_HOSTED_FEATURE_LAYER,
        ),
        (
            "Feature Service",
            ["Feature Service"],
            CATEGORY_REFERENCED_FEATURE_LAYER,
        ),
        ("StoryMap", [], CATEGORY_STORYMAP),
        ("CityEngine Web Scene", ["CityEngine Web Scene"], CATEGORY_UNKNOWN),
        (None, None, CATEGORY_UNKNOWN),
        ("", [], CATEGORY_UNKNOWN),
    ],
)
def test_classify_item(
    item_type: str | None,
    type_keywords: list[str] | None,
    expected: str,
) -> None:
    assert classify_item(item_type, type_keywords) == expected


def test_classification_is_case_insensitive_on_keywords() -> None:
    assert (
        classify_item("Web Mapping Application", ["WEB MAPPING APPLICATION", "EXPERIENCEBUILDER"])
        == CATEGORY_EXPERIENCE_BUILDER
    )


def test_unknown_type_is_recorded_explicitly() -> None:
    # An unrecognized but well-formed item must be classified, not dropped.
    assert classify_item("Insights Workbook", ["Insights"]) == CATEGORY_UNKNOWN
