"""pyogrio/GDAL FileGDB workspace scanner adapter.

This adapter wires the :mod:`honua_esri_assess.filegdb` workspace scanner
(``scan_filegdb_workspace``) to the CLI. Unlike the descriptor-backed
``filegdb`` handler, it issues read-only ``pyogrio``/GDAL metadata calls against
a local ``.gdb`` directory. It never touches the network and never mutates the
workspace; recoverable failures (including a missing ``pyogrio`` backend) are
surfaced as v0.1 ``diagnostics[]`` entries rather than raised.
"""

from __future__ import annotations

from typing import Any

from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.diagnostics import Diagnostic
from honua_esri_assess.filegdb import (
    FileGdbMetadataReader,
    FileGdbScanOptions,
    scan_filegdb_workspace,
)


def run(
    options: ScanOptions,
    *,
    reader: FileGdbMetadataReader | None = None,
) -> ScanResult:
    footprint = scan_filegdb_workspace(
        options.target,
        options=FileGdbScanOptions(force_feature_count=False),
        reader=reader,
    )
    diagnostics = _diagnostics_from_footprint(footprint)
    return ScanResult(footprint=footprint, diagnostics=diagnostics)


def _diagnostics_from_footprint(footprint: dict[str, Any]) -> tuple[Diagnostic, ...]:
    raw = footprint.get("diagnostics")
    if not isinstance(raw, list):
        return ()
    diagnostics: list[Diagnostic] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        diagnostics.append(
            Diagnostic(
                code=str(entry.get("code", "partial-coverage")),
                message=str(entry.get("message", "")),
                scope=str(entry.get("scope", "filegdb")),
                severity=str(entry.get("severity", "warn")),
                hint=entry.get("hint"),
            )
        )
    return tuple(diagnostics)
