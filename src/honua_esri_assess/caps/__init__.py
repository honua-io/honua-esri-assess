"""Crosswalk EsriFootprint.json to Honua capability keys.

See :mod:`honua_esri_assess.caps.crosswalk` for the draft-fixture notice.
"""

from __future__ import annotations

from .crosswalk import Crosswalk, CrosswalkError, load_bundled_crosswalk, parse_crosswalk_text
from .mapper import CapabilityMatch, CapsResult, UnmappedCapability, evaluate
from .renderer import build_url, render_markdown, to_json_dict

__all__ = [
    "CapabilityMatch",
    "CapsResult",
    "Crosswalk",
    "CrosswalkError",
    "UnmappedCapability",
    "build_url",
    "evaluate",
    "load_bundled_crosswalk",
    "parse_crosswalk_text",
    "render_markdown",
    "to_json_dict",
]
