"""Static catalog mapping Esri extension license codes to human names.

The codes used here are the terse identifiers surfaced by
``/arcgis/admin/system/licenses`` and per-service ``extensions`` arrays
(e.g., ``"Spatial"``, ``"Network"``, ``"3DAnalyst"``). They are documented
in the ArcGIS REST/Admin reference. Unknown codes round-trip verbatim
with status ``"unknown"`` and an ``unknown`` resolution flag so the catalog
can be extended without losing data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtensionCatalogEntry:
    code: str
    name: str


_CATALOG: dict[str, ExtensionCatalogEntry] = {
    entry.code.lower(): entry
    for entry in (
        ExtensionCatalogEntry("Spatial", "ArcGIS Spatial Analyst"),
        ExtensionCatalogEntry("Network", "ArcGIS Network Analyst"),
        ExtensionCatalogEntry("3DAnalyst", "ArcGIS 3D Analyst"),
        ExtensionCatalogEntry("GeoStats", "ArcGIS Geostatistical Analyst"),
        ExtensionCatalogEntry("DataInteroperability", "ArcGIS Data Interoperability"),
        ExtensionCatalogEntry("DataReviewer", "ArcGIS Data Reviewer"),
        ExtensionCatalogEntry("WorkflowMgrSvr", "ArcGIS Workflow Manager Server"),
        ExtensionCatalogEntry("ImageServer", "ArcGIS Image Server"),
        ExtensionCatalogEntry("GeoEvent", "ArcGIS GeoEvent Server"),
        ExtensionCatalogEntry("Aviation", "ArcGIS Aviation"),
        ExtensionCatalogEntry("Maritime", "ArcGIS Maritime"),
        ExtensionCatalogEntry("Roads", "ArcGIS Roads and Highways"),
        ExtensionCatalogEntry("Defense", "ArcGIS Defense Mapping"),
        ExtensionCatalogEntry("Production", "ArcGIS Production Mapping"),
        ExtensionCatalogEntry("LocationReferencing", "ArcGIS Location Referencing"),
        ExtensionCatalogEntry("BusinessAnalyst", "ArcGIS Business Analyst"),
        ExtensionCatalogEntry("Tracking", "ArcGIS Tracking Server"),
        ExtensionCatalogEntry("PublisherSDS", "ArcGIS Publisher (SDS)"),
        ExtensionCatalogEntry("ImageAnalyst", "ArcGIS Image Analyst"),
        ExtensionCatalogEntry("DataReviewerSvc", "ArcGIS Data Reviewer for Server"),
        ExtensionCatalogEntry("KnowledgeServer", "ArcGIS Knowledge Server"),
        ExtensionCatalogEntry("NotebookServer", "ArcGIS Notebook Server"),
        ExtensionCatalogEntry("VelocityServer", "ArcGIS Velocity"),
    )
}


def extension_catalog() -> dict[str, ExtensionCatalogEntry]:
    """Return a shallow copy of the catalog keyed by lowercase code."""

    return dict(_CATALOG)


@dataclass(frozen=True)
class ResolvedExtension:
    code: str
    name: str
    known: bool


def resolve_extension(code: str) -> ResolvedExtension:
    """Resolve an Esri extension code to a human name.

    Unknown codes round-trip verbatim with ``known=False`` so callers can
    emit a ``partial-coverage`` diagnostic without losing the original
    identifier.
    """

    key = (code or "").strip()
    entry = _CATALOG.get(key.lower()) if key else None
    if entry is None:
        return ResolvedExtension(code=key, name=key or "unknown", known=False)
    return ResolvedExtension(code=entry.code, name=entry.name, known=True)
