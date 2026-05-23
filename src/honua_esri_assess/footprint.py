"""EsriFootprint v0.1 builder utilities."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .diagnostics import Diagnostic
from .redaction import sanitize_handoff_url

SCHEMA_VERSION = "0.1.0"
PRODUCER_NAME = "honua-esri-assess"


def build_footprint(
    *,
    source_kind: str,
    target: str,
    inventory: Iterable[dict[str, Any]],
    diagnostics: Iterable[Diagnostic],
    portal_name: str | None = None,
    server: dict[str, Any] | None = None,
    filegdb: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    items = list(inventory)
    by_kind: Counter[str] = Counter(item["kind"] for item in items)
    source: dict[str, Any] = {"kind": source_kind, "target": sanitize_handoff_url(target)}
    if portal_name is not None:
        source["portalName"] = portal_name

    now = generated_at or datetime.now(timezone.utc)
    footprint: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "producer": {"name": PRODUCER_NAME, "version": __version__},
        "source": source,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inventory": items,
        "counts": {"total": len(items), "byKind": dict(by_kind)},
        "diagnostics": [d.to_dict() for d in diagnostics],
    }
    if server is not None:
        footprint["server"] = server
    if filegdb is not None:
        footprint["filegdb"] = filegdb
    return footprint


def write_footprint(footprint: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(footprint, indent=2, sort_keys=True) + "\n", encoding="utf-8")
