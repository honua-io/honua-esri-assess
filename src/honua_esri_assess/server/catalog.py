"""Service-type and geometry-type taxonomy for ArcGIS Server REST.

Single source of truth for mapping raw Esri type strings to coarse
migration buckets used by scanner diagnostics and future emitters. The
published v0.1 footprint persists the raw ``serviceType`` only. Adding a
new service type is one constant-table edit and one test fixture.
"""

from __future__ import annotations

# Raw Esri service-type string -> coarse migration bucket used inside scan results.
SERVICE_TYPE_TO_KIND: dict[str, str] = {
    "MapServer": "mapService",
    "FeatureServer": "featureService",
    "ImageServer": "imageService",
    "VectorTileServer": "vectorTileService",
    "GPServer": "geoprocessingService",
    "GeocodeServer": "geocodeService",
    "NAServer": "networkAnalysisService",
    "GeometryServer": "geometryService",
    "SceneServer": "sceneService",
    "StreamServer": "streamService",
    "GlobeServer": "globeService",
    "MobileServer": "mobileService",
}

UNKNOWN_KIND = "other"

# Service-types that have a per-service body worth probing during a deep scan
# (layers/tables for map/feature/image/scene/stream; the ``tasks`` array for
# GPServer, used only to record cross-repo migration-handoff task names).
DEEP_PROBE_TYPES: frozenset[str] = frozenset(
    {"MapServer", "FeatureServer", "ImageServer", "SceneServer", "StreamServer", "GPServer"}
)

# Raw Esri supported-extension string -> normalized OGC capability flag. ArcGIS
# advertises OGC interfaces (and a few well-known SOEs) on each catalog entry via
# the per-service ``supportedExtensions`` field; this maps the documented
# interface extensions to a stable, prospect-safe flag without a deep probe.
SUPPORTED_EXTENSION_TO_OGC: dict[str, str] = {
    "WMSServer": "WMS",
    "WFSServer": "WFS",
    "WCSServer": "WCS",
}

# Esri geometry-type string -> coarse bucket used for layer summaries.
GEOMETRY_TYPE_TO_KIND: dict[str, str] = {
    "esriGeometryPoint": "point",
    "esriGeometryMultipoint": "multipoint",
    "esriGeometryPolyline": "polyline",
    "esriGeometryPolygon": "polygon",
    "esriGeometryEnvelope": "envelope",
    "esriGeometryMultiPatch": "multipatch",
}


def classify_service(raw_type: str) -> str:
    """Return the coarse bucket for *raw_type*, or :data:`UNKNOWN_KIND`."""

    return SERVICE_TYPE_TO_KIND.get(raw_type, UNKNOWN_KIND)


def classify_geometry(raw_geometry: str | None) -> str | None:
    """Map an Esri ``esriGeometryX`` string to a coarse bucket."""

    if raw_geometry is None:
        return None
    return GEOMETRY_TYPE_TO_KIND.get(raw_geometry, raw_geometry)


def is_known_service_type(raw_type: str) -> bool:
    """Return whether *raw_type* maps to a recognized migration bucket."""

    return raw_type in SERVICE_TYPE_TO_KIND


def classify_ogc_capabilities(supported_extensions: str | None) -> tuple[str, ...]:
    """Map a service's ``supportedExtensions`` string to OGC capability flags.

    ArcGIS Server advertises OGC interfaces (``WMSServer``, ``WFSServer``,
    ``WCSServer``) and SOEs through a comma-separated ``supportedExtensions``
    field on each catalog entry. Only the documented OGC interfaces are
    normalized here; everything else is ignored so unknown SOEs never become
    capability flags. The result is sorted and de-duplicated for determinism.
    """

    if not isinstance(supported_extensions, str):
        return ()
    flags: set[str] = set()
    for part in supported_extensions.split(","):
        token = part.strip()
        ogc = SUPPORTED_EXTENSION_TO_OGC.get(token)
        if ogc is not None:
            flags.add(ogc)
    return tuple(sorted(flags))


__all__ = [
    "DEEP_PROBE_TYPES",
    "GEOMETRY_TYPE_TO_KIND",
    "SERVICE_TYPE_TO_KIND",
    "SUPPORTED_EXTENSION_TO_OGC",
    "UNKNOWN_KIND",
    "classify_geometry",
    "classify_ogc_capabilities",
    "classify_service",
    "is_known_service_type",
]
