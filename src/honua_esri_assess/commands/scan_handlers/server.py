"""ArcGIS Server REST scanner adapter."""

from __future__ import annotations

from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.diagnostics import DiagnosticError
from honua_esri_assess.footprint import build_footprint
from honua_esri_assess.scanners import server as server_scanner


def run(options: ScanOptions) -> ScanResult:
    try:
        result = server_scanner.scan(
            options.target,
            token=options.token,
            user_agent=options.user_agent,
            max_retries=options.max_retries,
            timeout=options.timeout,
        )
    except Exception as exc:
        raise DiagnosticError(
            "ArcGIS Server scan failed before producing an inventory.",
            code="scanner-error",
            scope="server",
        ) from exc
    footprint = build_footprint(
        source_kind="arcgis-server",
        target=options.target,
        inventory=result["inventory"],
        diagnostics=result["diagnostics"],
        server=result["server"],
    )
    return ScanResult(
        footprint=footprint,
        diagnostics=tuple(result["diagnostics"]),
    )
