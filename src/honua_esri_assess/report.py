"""Markdown readiness report renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

REQUIRED_HEADINGS = (
    "# Esri Footprint Readiness",
    "## Inventory Summary",
    "## Diagnostics",
)


def render(footprint: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Esri Footprint Readiness")
    lines.append("")
    source = footprint.get("source", {})
    lines.append(f"- **Source kind:** {source.get('kind', 'unknown')}")
    lines.append(f"- **Locator:** {source.get('locator', 'unknown')}")
    lines.append(f"- **Generated at:** {footprint.get('generatedAt', 'unknown')}")
    lines.append(f"- **Tool version:** {footprint.get('tool', {}).get('version', 'unknown')}")
    lines.append("")

    counts = footprint.get("counts", {})
    by_kind = counts.get("items", {}) or {}
    total = sum(value for value in by_kind.values() if isinstance(value, int))
    lines.append("## Inventory Summary")
    lines.append("")
    lines.append(f"Total inventory items: **{total}**.")
    lines.append("")
    if by_kind:
        lines.append("| Kind | Count |")
        lines.append("| --- | --- |")
        for kind in sorted(by_kind):
            lines.append(f"| {kind} | {by_kind[kind]} |")
    else:
        lines.append("_No inventory items recorded._")
    lines.append("")

    server = footprint.get("server")
    filegdb = footprint.get("filegdb")
    if server or filegdb:
        lines.append("## Backend Detail")
        lines.append("")
        if isinstance(server, dict):
            service_counts = server.get("serviceCounts", {}) or {}
            folders = server.get("folders", []) or []
            for raw_type in sorted(service_counts):
                lines.append(f"- {raw_type}: {service_counts[raw_type]}")
            if folders:
                lines.append(f"- Folders: {', '.join(folders)}")
        if isinstance(filegdb, dict):
            lines.append(f"- Feature classes: {filegdb.get('featureClassCount', 0)}")
            lines.append(f"- Path hash: {filegdb.get('pathHash', 'unknown')}")
        lines.append("")

    diagnostics: Iterable[dict[str, Any]] = footprint.get("diagnostics", []) or []
    diagnostics = list(diagnostics)
    lines.append("## Diagnostics")
    lines.append("")
    if not diagnostics:
        lines.append("No diagnostics emitted.")
    else:
        for diag in diagnostics:
            code = diag.get("code", "unknown")
            message = diag.get("message", "")
            scope = diag.get("scope")
            suffix = f" (scope: {scope})" if scope else ""
            lines.append(f"- **{code}** — {message}{suffix}")
    lines.append("")
    return "\n".join(lines)


def write(footprint: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(footprint), encoding="utf-8")
