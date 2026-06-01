"""Per-shop-profile migratability verdict over EsriFootprint.json."""

from __future__ import annotations

from .engine import (
    Boundary,
    FootprintVerdict,
    LockInExtent,
    ProfileVerdict,
    evaluate,
)
from .registry import CAPABILITY_REGISTRY, HARD_LOCK_IN_KEYS, SHOP_PROFILES
from .renderer import render

__all__ = [
    "Boundary",
    "CAPABILITY_REGISTRY",
    "FootprintVerdict",
    "HARD_LOCK_IN_KEYS",
    "LockInExtent",
    "ProfileVerdict",
    "SHOP_PROFILES",
    "evaluate",
    "render",
]
