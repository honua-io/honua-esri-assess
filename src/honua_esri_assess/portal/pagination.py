"""Pagination helpers for Portal Sharing search endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from honua_esri_assess.portal.client import PortalClient


def iter_paginated(
    client: PortalClient,
    path: str,
    *,
    result_key: str = "results",
    params: dict[str, Any] | None = None,
    page_size: int = 100,
) -> Iterator[dict[str, Any]]:
    """Yield result records from an ArcGIS search-style paginated resource."""

    start = 1
    while start != -1:
        page_params = {"num": page_size, "start": start, **(params or {})}
        payload = client.get_json(path, page_params)
        results = payload.get(result_key, [])
        if isinstance(results, list):
            for record in results:
                if isinstance(record, dict):
                    yield record

        next_start = payload.get("nextStart", -1)
        if not isinstance(next_start, int) or next_start <= start:
            break
        start = next_start
