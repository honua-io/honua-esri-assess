"""Read-only FileGDB inventory scanner.

This minimum-viable scanner reads an inventory descriptor written by a
license-compatible driver. The descriptor format mirrors what a real
``pyogrio``/``fiona`` walk would produce: a list of feature classes with
geometry type and (optional) feature count. The driver-vs-fixture choice is
deliberately deferred — for now we look for ``<path>/_inventory.json`` when the
path is a directory, or treat the path itself as the descriptor when it is a
file. Either way the scanner is fully read-only and never touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..diagnostics import Diagnostic

_GEOMETRY_NORMALIZATION = {
    "point": "point",
    "multipoint": "multipoint",
    "line": "line",
    "polyline": "line",
    "polygon": "polygon",
}


def scan(target: str | Path) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    inventory: list[dict[str, Any]] = []
    path = Path(target)
    descriptor_path = _resolve_descriptor(path)
    if descriptor_path is None:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message="No FileGDB inventory descriptor found at the supplied path.",
                field=str(path.name),
            )
        )
        return {
            "inventory": inventory,
            "diagnostics": diagnostics,
            "filegdb": {"featureClassCount": 0, "path": path.name},
        }

    try:
        payload = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message="FileGDB inventory descriptor could not be parsed.",
                field=descriptor_path.name,
            )
        )
        return {
            "inventory": inventory,
            "diagnostics": diagnostics,
            "filegdb": {"featureClassCount": 0, "path": path.name},
        }

    feature_classes = payload.get("featureClasses") if isinstance(payload, dict) else None
    if not isinstance(feature_classes, list):
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message="FileGDB inventory descriptor missing 'featureClasses'.",
                field=descriptor_path.name,
            )
        )
        feature_classes = []

    for fc in feature_classes:
        if not isinstance(fc, dict):
            continue
        record = _to_record(fc, diagnostics)
        if record is not None:
            inventory.append(record)

    return {
        "inventory": inventory,
        "diagnostics": diagnostics,
        "filegdb": {"featureClassCount": len(inventory), "path": path.name},
    }


def _resolve_descriptor(path: Path) -> Path | None:
    if path.is_dir():
        candidate = path / "_inventory.json"
        return candidate if candidate.is_file() else None
    return path if path.is_file() else None


def _to_record(fc: dict[str, Any], diagnostics: list[Diagnostic]) -> dict[str, Any] | None:
    name = fc.get("name")
    if not isinstance(name, str) or not name:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message="Feature class missing a name; skipped.",
            )
        )
        return None
    record: dict[str, Any] = {"kind": "feature-class", "name": name}
    geom = fc.get("geometryType")
    if isinstance(geom, str):
        normalized = _GEOMETRY_NORMALIZATION.get(geom.lower())
        if normalized is None:
            diagnostics.append(
                Diagnostic(
                    code="unsupported-item-type",
                    message=f"Unrecognized geometry type {geom!r}; recorded as-is.",
                    field=name,
                )
            )
            normalized = geom
        record["geometryType"] = normalized
    count = fc.get("featureCount")
    if isinstance(count, int) and count >= 0:
        record["featureCount"] = count
    return record
