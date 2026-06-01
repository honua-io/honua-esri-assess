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
class FieldDetail:
    """One attribute field on a layer/table.

    ``domain_type`` is ``coded``/``range`` when the field carries a domain,
    else ``None``. ``editor_tracking`` flags the field as an editor-tracking
    column (created/edited user/date) when the layer advertises it.
    """

    name: str
    type: str | None = None
    alias: str | None = None
    nullable: bool | None = None
    domain_type: str | None = None
    domain_name: str | None = None
    editor_tracking: bool = False


@dataclass(frozen=True)
class RelationshipDetail:
    """One relationship class advertised on a layer."""

    id: int | None = None
    name: str | None = None
    related_table_id: int | None = None
    cardinality: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class EditorTracking:
    """Editor-tracking configuration observed on a layer."""

    enabled: bool = False
    creator_field: str | None = None
    creation_date_field: str | None = None
    editor_field: str | None = None
    edit_date_field: str | None = None


@dataclass(frozen=True)
class LayerDetail:
    """Schema and behavior detail read from a single layer's JSON.

    Populated only when the scanner runs with layer-detail enabled and the
    per-layer resource was fetched successfully. Every value is sourced from
    the documented read-only layer metadata; no row/feature data is read.
    """

    fields: tuple[FieldDetail, ...] = ()
    relationships: tuple[RelationshipDetail, ...] = ()
    subtype_count: int = 0
    has_attachments: bool | None = None
    editor_tracking: EditorTracking | None = None
    renderer_type: str | None = None
    has_labels: bool | None = None
    has_popups: bool | None = None
    definition_query: str | None = None
    spatial_reference: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LayerRecord:
    """Layer summary captured during a deep scan of a FeatureServer/MapServer."""

    id: int
    name: str
    type: str | None = None
    geometry_type: str | None = None
    detail: LayerDetail | None = None


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
    "EditorTracking",
    "FieldDetail",
    "FolderRecord",
    "LayerDetail",
    "LayerRecord",
    "RelationshipDetail",
    "ScanDiagnostic",
    "ServerInfo",
    "ServerScanResult",
    "ServiceRecord",
]
