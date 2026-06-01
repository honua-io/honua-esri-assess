"""Functional content-type classification for Portal Sharing items.

Portal items expose a coarse Esri ``type`` (e.g. ``Web Mapping Application``)
plus a ``typeKeywords`` list that disambiguates the functional product behind a
given type (Web AppBuilder vs. Experience Builder vs. an Instant App all share
the ``Web Mapping Application`` type, for example). This module maps that pair
onto a small, stable vocabulary of *functional categories* so the footprint can
report what a shop actually runs rather than the raw Esri type label.

The mapping is intentionally shallow: it only consumes ``type`` and
``typeKeywords`` already returned by ``search`` / ``content/items/<id>`` and
never fetches or parses per-app configuration. Anything that does not match a
known category is reported as ``unknown`` so unrecognized content is recorded
explicitly rather than silently dropped.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Stable functional-category vocabulary surfaced in the footprint. Keys are
#: prospect-safe display-label tokens accepted by the schema EsriTypeCountMap.
CATEGORY_WEB_MAP = "web-map"
CATEGORY_WEB_SCENE = "web-scene"
CATEGORY_DASHBOARD = "dashboard"
CATEGORY_STORYMAP = "storymap"
CATEGORY_EXPERIENCE_BUILDER = "experience-builder"
CATEGORY_INSTANT_APP = "instant-app"
CATEGORY_WEB_APPBUILDER = "web-appbuilder"
CATEGORY_WEB_APP = "web-app"
CATEGORY_SURVEY123_FORM = "survey123-form"
CATEGORY_FIELD_MAPS = "field-maps"
CATEGORY_WORKFORCE = "workforce"
CATEGORY_QUICKCAPTURE = "quickcapture"
CATEGORY_NOTEBOOK = "notebook"
CATEGORY_HOSTED_FEATURE_LAYER = "hosted-feature-layer"
CATEGORY_REFERENCED_FEATURE_LAYER = "referenced-feature-layer"
CATEGORY_HOSTED_TILE_LAYER = "hosted-tile-layer"
CATEGORY_TILE_LAYER = "tile-layer"
CATEGORY_VECTOR_TILE_LAYER = "vector-tile-layer"
CATEGORY_IMAGE_LAYER = "image-layer"
CATEGORY_SCENE_LAYER = "scene-layer"
CATEGORY_MAP_SERVICE = "map-service"
CATEGORY_UNKNOWN = "unknown"

_HOSTED_KEYWORD = "hosted service"
_SURVEY2_KEYWORDS = {"survey123", "form"}


def _normalize_keywords(type_keywords: Iterable[str] | None) -> set[str]:
    if not type_keywords:
        return set()
    return {str(keyword).strip().lower() for keyword in type_keywords if keyword}


def classify_item(
    item_type: str | None,
    type_keywords: Iterable[str] | None = None,
) -> str:
    """Return the functional category for a Portal item.

    Classification consumes only the Esri ``type`` and ``typeKeywords`` already
    present on a scanned item. Unrecognized combinations return
    :data:`CATEGORY_UNKNOWN` so unknown content is recorded explicitly.
    """

    normalized_type = (item_type or "").strip().lower()
    keywords = _normalize_keywords(type_keywords)

    if not normalized_type:
        return CATEGORY_UNKNOWN

    if normalized_type == "web map":
        return CATEGORY_WEB_MAP
    if normalized_type == "web scene":
        return CATEGORY_WEB_SCENE
    if normalized_type == "notebook":
        return CATEGORY_NOTEBOOK
    if normalized_type == "quickcapture project":
        return CATEGORY_QUICKCAPTURE
    if normalized_type == "workforce project":
        return CATEGORY_WORKFORCE

    if normalized_type in {"dashboard", "arcgis dashboard"}:
        return CATEGORY_DASHBOARD

    if normalized_type == "storymap" or "storymap" in keywords:
        return CATEGORY_STORYMAP

    if normalized_type == "form":
        # Survey123 forms surface as the "Form" item type.
        return CATEGORY_SURVEY123_FORM

    # Field Maps, Workforce, and other product-specific apps surface under the
    # generic "Web Mapping Application" / "Application" types and are only
    # distinguishable via typeKeywords.
    if normalized_type in {"web mapping application", "application"}:
        if "experiencebuilder" in keywords or "experience builder" in keywords:
            return CATEGORY_EXPERIENCE_BUILDER
        if any(keyword.startswith("instantappsjson") for keyword in keywords) or (
            "instant apps" in keywords
        ):
            return CATEGORY_INSTANT_APP
        if "storymap" in keywords:
            return CATEGORY_STORYMAP
        if "web appbuilder" in keywords or "webappbuilder" in keywords:
            return CATEGORY_WEB_APPBUILDER
        if "workforce project" in keywords or "workforce" in keywords:
            return CATEGORY_WORKFORCE
        if "fieldmaps" in keywords or "field maps" in keywords:
            return CATEGORY_FIELD_MAPS
        return CATEGORY_WEB_APP

    if normalized_type == "feature service":
        if _HOSTED_KEYWORD in keywords:
            return CATEGORY_HOSTED_FEATURE_LAYER
        return CATEGORY_REFERENCED_FEATURE_LAYER

    if normalized_type in {"feature collection"}:
        return CATEGORY_HOSTED_FEATURE_LAYER

    if normalized_type in {"tile package", "compact tile package"} or (
        normalized_type == "map service" and _HOSTED_KEYWORD in keywords
    ):
        return CATEGORY_HOSTED_TILE_LAYER

    if normalized_type == "map service":
        return CATEGORY_MAP_SERVICE

    if normalized_type == "vector tile service":
        return CATEGORY_VECTOR_TILE_LAYER

    if normalized_type == "image service":
        return CATEGORY_IMAGE_LAYER

    if normalized_type == "scene service":
        return CATEGORY_SCENE_LAYER

    return CATEGORY_UNKNOWN


__all__ = [
    "CATEGORY_WEB_MAP",
    "CATEGORY_WEB_SCENE",
    "CATEGORY_DASHBOARD",
    "CATEGORY_STORYMAP",
    "CATEGORY_EXPERIENCE_BUILDER",
    "CATEGORY_INSTANT_APP",
    "CATEGORY_WEB_APPBUILDER",
    "CATEGORY_WEB_APP",
    "CATEGORY_SURVEY123_FORM",
    "CATEGORY_FIELD_MAPS",
    "CATEGORY_WORKFORCE",
    "CATEGORY_QUICKCAPTURE",
    "CATEGORY_NOTEBOOK",
    "CATEGORY_HOSTED_FEATURE_LAYER",
    "CATEGORY_REFERENCED_FEATURE_LAYER",
    "CATEGORY_HOSTED_TILE_LAYER",
    "CATEGORY_TILE_LAYER",
    "CATEGORY_VECTOR_TILE_LAYER",
    "CATEGORY_IMAGE_LAYER",
    "CATEGORY_SCENE_LAYER",
    "CATEGORY_MAP_SERVICE",
    "CATEGORY_UNKNOWN",
    "classify_item",
]
