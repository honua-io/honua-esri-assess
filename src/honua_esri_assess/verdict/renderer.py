"""Markdown renderer for the migratability verdict.

Renders a :class:`FootprintVerdict` to deterministic Markdown. Performs no file,
network, or logging I/O; reading/writing and validation are handled by the CLI.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from honua_esri_assess.diagnostics import ReportRenderError
from honua_esri_assess.report.formatting import bullet_list, markdown_table, text

from .engine import FootprintVerdict, ProfileVerdict, evaluate

_VERDICT_LABELS = {"go": "GO", "conditional": "CONDITIONAL", "no-go": "NO-GO"}


def render(footprint: Mapping[str, Any]) -> str:
    """Render an EsriFootprint v0.1 dictionary to a Markdown verdict report."""

    if not isinstance(footprint, Mapping):
        raise ReportRenderError("Verdict renderer expected a footprint object.")

    result = evaluate(footprint)
    parts = [
        _render_header(footprint),
        _render_summary(result),
        _render_hard_lock_ins(result),
        _render_profiles(result),
    ]
    return "\n\n".join(part.rstrip() for part in parts if part.strip()) + "\n"


def _render_header(footprint: Mapping[str, Any]) -> str:
    source = footprint.get("source", {})
    if not isinstance(source, Mapping):
        source = {}
    rows = [
        ("Schema version", text(footprint.get("schemaVersion"))),
        ("Generated at", text(footprint.get("generatedAt"))),
        ("Source", text(source.get("kind"))),
        ("Source locator", text(source.get("locator"))),
    ]
    return "# Honua Migratability Verdict\n\n" + markdown_table(("Field", "Value"), rows)


def _render_summary(result: FootprintVerdict) -> str:
    rows = [
        (
            verdict.profile,
            _VERDICT_LABELS.get(verdict.verdict, verdict.verdict),
            verdict.effort,
            str(len(verdict.boundaries)),
        )
        for verdict in result.profiles
    ]
    return "## Verdict by Shop Profile\n\n" + markdown_table(
        ("Shop profile", "Verdict", "Effort", "Boundaries"), rows
    )


def _render_hard_lock_ins(result: FootprintVerdict) -> str:
    lines = ["## Hard Lock-ins (explicit non-goals)"]
    if not result.hard_lock_ins:
        lines.append("No hard Esri lock-ins (Utility Network, Parcel Fabric, LRS) detected.")
        return "\n\n".join(lines)
    lines.append(
        "These Esri capabilities are explicit non-goals and force a no-go / "
        "federate-only verdict wherever they appear:"
    )
    lines.append(
        bullet_list(
            f"**{boundary.label}** - {boundary.detail}"
            for boundary in result.hard_lock_ins
        )
    )
    return "\n\n".join(lines)


def _render_profiles(result: FootprintVerdict) -> str:
    sections = ["## Profile Detail"]
    for verdict in result.profiles:
        sections.append(_render_profile(verdict))
    return "\n\n".join(sections)


def _render_profile(verdict: ProfileVerdict) -> str:
    label = _VERDICT_LABELS.get(verdict.verdict, verdict.verdict)
    lines = [
        f"### {verdict.profile}",
        f"**Verdict:** {label} | **Effort:** {verdict.effort}",
    ]
    if verdict.rationale:
        lines.append(bullet_list(verdict.rationale))
    if verdict.boundaries:
        rows = [
            (
                boundary.label,
                "hard lock-in" if boundary.hard_lock_in else boundary.tier,
                boundary.detail,
            )
            for boundary in verdict.boundaries
        ]
        lines.append("**Named boundaries:**")
        lines.append(markdown_table(("Boundary", "Type", "Detail"), rows))
    else:
        lines.append("**Named boundaries:** none.")
    return "\n\n".join(lines)
