"""FileGDB inventory scanner adapter."""

from __future__ import annotations

from pathlib import Path

from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.diagnostics import DiagnosticError
from honua_esri_assess.footprint import build_footprint
from honua_esri_assess.scanners import filegdb as filegdb_scanner


def run(options: ScanOptions) -> ScanResult:
    try:
        result = filegdb_scanner.scan(options.target)
    except Exception as exc:
        raise DiagnosticError(
            "FileGDB scan failed before producing an inventory.",
            code="scanner-error",
            scope="filegdb",
        ) from exc
    footprint = build_footprint(
        source_kind="filegdb",
        target=Path(options.target).name,
        inventory=result["inventory"],
        diagnostics=result["diagnostics"],
        filegdb=result["filegdb"],
    )
    return ScanResult(
        footprint=footprint,
        diagnostics=tuple(result["diagnostics"]),
    )
