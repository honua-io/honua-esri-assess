"""JSON, Markdown, and shareable-URL rendering for the honua-caps crosswalk.

Performs no file, network, or logging I/O; reading/writing is the CLI
layer's job (``honua_esri_assess.commands.caps``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from honua_esri_assess.diagnostics import ReportRenderError
from honua_esri_assess.report.formatting import markdown_table, text

from .crosswalk import Crosswalk
from .mapper import CapsResult

SCHEMA_VERSION = "honua-caps.v1"

#: Base URL for the shareable capability-catalog deep link this command
#: builds. This is output *data* embedded in ``honua-caps.json`` / the
#: printed URL -- this module never issues an HTTP request to it (or to
#: anywhere else); it holds no import of ``requests`` or any HTTP client.
CATALOG_BASE_URL = "https://honua.io/capabilities.html"


def build_url(capability_keys: tuple[str, ...], units_estimate: int | None) -> str:
    """Build the shareable catalog URL for a set of Honua capability keys.

    ``units_estimate`` is omitted from the query string entirely (never
    emitted as ``units=0`` or ``units=`` empty) when no serving-unit signal
    was available in the footprint.
    """

    caps_param = quote(",".join(capability_keys), safe=",")
    url = f"{CATALOG_BASE_URL}?caps={caps_param}"
    if units_estimate is not None:
        url += f"&units={units_estimate}"
    return url


def to_json_dict(
    footprint: Mapping[str, Any],
    crosswalk: Crosswalk,
    result: CapsResult,
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Build the ``honua-caps.json`` payload for a crosswalked footprint."""

    if not isinstance(footprint, Mapping):
        raise ReportRenderError("Caps renderer expected a footprint object.")

    source = footprint.get("source")
    source_dict = source if isinstance(source, Mapping) else {}
    capability_keys = tuple(sorted(entry.key for entry in result.capabilities))
    url = build_url(capability_keys, result.units_estimate)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "source": {
            "kind": source_dict.get("kind"),
            "locator": source_dict.get("locator"),
        },
        "crosswalk": {
            "schemaVersion": crosswalk.schema_version,
            "source": crosswalk.source,
        },
        "capabilities": [
            {
                "key": entry.key,
                "assessKeys": list(entry.assess_keys),
                "matchedInventoryCount": entry.matched_inventory_count,
                "tier": entry.tier,
            }
            for entry in result.capabilities
        ],
        "unmapped": [
            {
                "assessKey": entry.assess_key,
                "matchedInventoryCount": entry.matched_inventory_count,
                "tier": entry.tier,
                "reason": entry.reason,
            }
            for entry in result.unmapped
        ],
        "diagnostics": list(_diagnostics(result)),
        "unitsEstimate": result.units_estimate,
        "url": url,
    }


def _diagnostics(result: CapsResult) -> tuple[str, ...]:
    lines = []
    if not result.detected_assess_keys:
        lines.append(
            "No esri-assess-registry capabilities were detected in this "
            "footprint's inventory."
        )
    not_supported = sorted(
        entry.assess_key for entry in result.unmapped if entry.reason == "not-supported"
    )
    if not_supported:
        lines.append(
            "Hard Esri lock-ins detected with no Honua equivalent: "
            + ", ".join(not_supported)
            + "."
        )
    unmapped_only = sorted(
        entry.assess_key for entry in result.unmapped if entry.reason == "unmapped"
    )
    if unmapped_only:
        lines.append(
            "Known assess capabilities with no capability-key mapping yet: "
            + ", ".join(unmapped_only)
            + "."
        )
    return tuple(lines)


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Render the ``honua-caps.json`` payload to a Markdown summary block.

    Styled to match the existing readiness-report / verdict Markdown
    conventions (``honua_esri_assess.report.formatting``).
    """

    parts = [
        _render_header(payload),
        _render_capabilities(payload),
        _render_unmapped(payload),
        _render_diagnostics(payload),
        _render_url(payload),
    ]
    return "\n\n".join(part.rstrip() for part in parts if part.strip()) + "\n"


def _render_header(payload: Mapping[str, Any]) -> str:
    source = payload.get("source", {})
    if not isinstance(source, Mapping):
        source = {}
    crosswalk = payload.get("crosswalk", {})
    if not isinstance(crosswalk, Mapping):
        crosswalk = {}
    rows = [
        ("Schema version", text(payload.get("schemaVersion"))),
        ("Generated at", text(payload.get("generatedAt"))),
        ("Source", text(source.get("kind"))),
        ("Source locator", text(source.get("locator"))),
        ("Crosswalk schema", text(crosswalk.get("schemaVersion"))),
        ("Crosswalk source", text(crosswalk.get("source"))),
        ("Serving-unit estimate", text(payload.get("unitsEstimate"))),
    ]
    return "# Honua Capability Crosswalk\n\n" + markdown_table(("Field", "Value"), rows)


def _render_capabilities(payload: Mapping[str, Any]) -> str:
    capabilities = payload.get("capabilities", [])
    lines = ["## Mapped Capabilities"]
    if not capabilities:
        lines.append("No detected capabilities mapped to a Honua capability key.")
        return "\n\n".join(lines)
    rows = [
        (
            entry.get("key"),
            ", ".join(entry.get("assessKeys", [])),
            entry.get("matchedInventoryCount"),
            entry.get("tier"),
        )
        for entry in capabilities
        if isinstance(entry, Mapping)
    ]
    lines.append(
        markdown_table(
            ("Honua capability key", "Assess key(s)", "Matched inventory", "Tier"),
            rows,
        )
    )
    return "\n\n".join(lines)


def _render_unmapped(payload: Mapping[str, Any]) -> str:
    unmapped = payload.get("unmapped", [])
    lines = ["## Unmapped / Not Supported"]
    if not unmapped:
        lines.append(
            "Every detected capability mapped to a Honua capability key -- "
            "nothing was dropped."
        )
        return "\n\n".join(lines)
    lines.append(
        "Nothing in the footprint's detected inventory is silently dropped: "
        "capabilities the crosswalk does not map appear here explicitly."
    )
    rows = [
        (
            entry.get("assessKey"),
            entry.get("matchedInventoryCount"),
            entry.get("tier"),
            entry.get("reason"),
        )
        for entry in unmapped
        if isinstance(entry, Mapping)
    ]
    lines.append(
        markdown_table(("Assess key", "Matched inventory", "Tier", "Reason"), rows)
    )
    return "\n\n".join(lines)


def _render_diagnostics(payload: Mapping[str, Any]) -> str:
    diagnostics = payload.get("diagnostics", [])
    if not diagnostics:
        return ""
    lines = ["## Diagnostics", "\n".join(f"- {line}" for line in diagnostics)]
    return "\n\n".join(lines)


def _render_url(payload: Mapping[str, Any]) -> str:
    return "## Shareable Catalog URL\n\n" + text(payload.get("url"))


__all__ = ["SCHEMA_VERSION", "CATALOG_BASE_URL", "build_url", "render_markdown", "to_json_dict"]
