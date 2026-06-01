"""Dataclass shapes returned by the ArcGIS Server scanner.

These types are the in-Python data model. The wire-format mapping into
``EsriFootprint.json`` lives in :mod:`honua_esri_assess.footprint.v0_1`;
deliberately decoupled so a future schema bump only touches the emitter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScanDiagnostic:
    """Per-scan or per-service diagnostic captured during a walk.

    ``code`` is a stable dotted identifier; ``severity`` is one of
    ``info|warning|error``. ``field`` is an optional JSON-pointer-ish
    breadcrumb so the readiness report (E8) can attach the diagnostic to
    a specific service.
    """

    code: str
    severity: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class LayerRecord:
    """Layer summary captured during a deep scan of a FeatureServer/MapServer."""

    id: int
    name: str
    type: str | None = None
    geometry_type: str | None = None


@dataclass(frozen=True)
class ServiceRecord:
    """One service entry from the catalog walk.

    ``service_type`` is the raw Esri type string (``FeatureServer``,
    ``MapServer``, ...); ``kind`` is the coarse migration bucket from
    :mod:`honua_esri_assess.server.catalog`. ``deep_scanned`` flips true
    when the per-service body was fetched and parsed.
    """

    name: str
    folder: str | None
    service_type: str
    kind: str
    url: str
    description: str | None = None
    capabilities: tuple[str, ...] = ()
    ogc_capabilities: tuple[str, ...] = ()
    layers: tuple[LayerRecord, ...] = ()
    tables: tuple[LayerRecord, ...] = ()
    service_data_type: str | None = None
    single_fused_map_cache: bool | None = None
    deep_scanned: bool = False


@dataclass(frozen=True)
class FolderRecord:
    """A folder in the catalog."""

    name: str
    service_count: int = 0


@dataclass(frozen=True)
class ServerInfo:
    """Top-level identity captured from ``/info`` and ``/rest/info``."""

    url: str
    current_version: str | None = None
    full_version: str | None = None
    auth_info: dict[str, Any] = field(default_factory=dict)
    software_authorization: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ServerScanResult:
    """Aggregate result of one :class:`ServerScanner.scan` invocation."""

    info: ServerInfo
    auth_mode: str
    deep: bool
    folders: tuple[FolderRecord, ...]
    services: tuple[ServiceRecord, ...]
    diagnostics: tuple[ScanDiagnostic, ...]


__all__ = [
    "FolderRecord",
    "LayerRecord",
    "ScanDiagnostic",
    "ServerInfo",
    "ServerScanResult",
    "ServiceRecord",
]
