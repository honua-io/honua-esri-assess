"""Typed scanner records before conversion to the handoff artifact."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from honua_esri_assess.diagnostics import Diagnostic


@dataclass(frozen=True)
class GroupRecord:
    id: str
    title: str | None = None
    owner: str | None = None
    access: str | None = None


@dataclass(frozen=True)
class ItemRecord:
    id: str
    title: str | None
    owner: str | None
    item_type: str | None
    type_bucket: str
    content_category: str = "unknown"
    access: str | None = None
    url: str | None = None
    created: str | None = None
    modified: str | None = None
    tags: list[str] = field(default_factory=list)
    type_keywords: list[str] = field(default_factory=list)
    layer_count: int | None = None
    extent: list[Any] | None = None
    dependencies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LayerRecord:
    id: int | str | None
    name: str | None
    layer_type: str | None = None
    geometry_type: str | None = None
    max_record_count: int | None = None


@dataclass(frozen=True)
class ServiceRecord:
    item_id: str
    url: str
    service_type: str | None
    capabilities: str | None = None
    layers: list[LayerRecord] = field(default_factory=list)
    tables: list[LayerRecord] = field(default_factory=list)


@dataclass(frozen=True)
class FederatedServer:
    """One server site federated with a Portal.

    Captures the credential-free server URL plus the assigned hosting/federated
    role and any advanced server functions (GeoEvent, GeoAnalytics, Notebook,
    Knowledge, ...) advertised by the documented ``portals/self/servers``
    federation surface. Deep per-server configuration is intentionally left to
    the per-service children — only topology + role presence lives here.
    """

    url: str
    server_role: str | None = None
    server_function: str | None = None
    is_hosted: bool | None = None
    functions: tuple[str, ...] = field(default_factory=tuple)
    advanced_roles: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FederationInfo:
    """Federation topology discovered from the Portal federation surface."""

    servers: tuple[FederatedServer, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OrgInfo:
    id: str | None
    name: str | None
    portal_url: str
    sharing_rest_url: str
    is_portal: bool | None = None
    url_key: str | None = None
    custom_base_url: str | None = None
    user_count: int | None = None
    group_count: int | None = None
    licensed_extensions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PortalScanResult:
    org: OrgInfo
    auth_mode: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    items: list[ItemRecord] = field(default_factory=list)
    groups: list[GroupRecord] = field(default_factory=list)
    services: list[ServiceRecord] = field(default_factory=list)
    federation: FederationInfo | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
