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

# Service-types that have a per-service body with layers/tables worth probing
# during a deep scan.
DEEP_PROBE_TYPES: frozenset[str] = frozenset(
    {"MapServer", "FeatureServer", "ImageServer", "SceneServer", "StreamServer"}
)

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


__all__ = [
    "DEEP_PROBE_TYPES",
    "GEOMETRY_TYPE_TO_KIND",
    "SERVICE_TYPE_TO_KIND",
    "UNKNOWN_KIND",
    "classify_geometry",
    "classify_service",
]
