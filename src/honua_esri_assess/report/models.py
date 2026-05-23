"""Small immutable models used by the readiness report renderer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComplexityThresholds:
    """Item and layer thresholds for prospect-facing complexity buckets."""

    small_items: int = 50
    small_layers: int = 200
    medium_items: int = 500
    medium_layers: int = 2_000
    large_items: int = 5_000
    large_layers: int = 20_000


@dataclass(frozen=True)
class ComplexityScore:
    bucket: str
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class ReviewItem:
    reason_code: str
    item_label: str
    detail: str
    sort_key: tuple[str, str, str]


@dataclass(frozen=True)
class OrderingGroup:
    rank: int
    title: str
    justification: str
    items: tuple[Mapping[str, Any], ...]
