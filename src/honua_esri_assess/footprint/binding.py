"""Binding-mode routing derived from Admin-API data-store registrations.

This module is *pure*: it turns already-fetched, already-redacted Admin-API
payloads (`/admin/data/items` registrations and `/admin/usagereports`
summaries) into two migration-planning facets for ``EsriFootprint.json``:

* a **usage-ranked service ordering** so migration sequencing is driven by
  real request volume rather than alphabetical or folder heuristics, and
* a **per-dataset binding-mode recommendation** (``federate`` /
  ``connect-in-place`` / ``materialize``) derived *only* from the storage
  type a data-store registration advertises.

Hard constraints honored here:

* Read-only — this module never performs I/O; it consumes payloads fetched
  by :mod:`honua_esri_assess.scanners.admin_usage`.
* Storage type is taken from the registration's declared ``type`` /
  ``provider`` fields only. We never parse ArcSDE/GDB internals or open a
  database connection to infer storage.
* No credentials are emitted: connection facets are reduced to a coarse
  ``connectionKind`` token and never carry connection strings, hosts,
  usernames, or passwords.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BindingMode = Literal["federate", "connect-in-place", "materialize"]
"""Recommended Honua binding mode for a source dataset.

* ``federate`` — keep the data where it is and federate live (enterprise
  geodatabases / relational stores that Honua can query in place at scale).
* ``connect-in-place`` — register a direct read-only connection without
  copying (cloud/object stores and file-based shares Honua can read live).
* ``materialize`` — copy/snapshot into Honua-managed storage (file
  geodatabases, shapefiles, and anything whose storage type we cannot map).
"""

ConnectionKind = Literal[
    "enterprise-geodatabase",
    "relational",
    "cloud-store",
    "file-share",
    "object-store",
    "big-data-file-share",
    "unknown",
]
"""Coarse, credential-free classification of a data-store registration."""


# Map the documented Admin-API data-item ``type`` discriminators to a coarse,
# credential-free connection kind. Detection is purely by the *declared*
# registration type — never by inspecting SDE tables or GDB internals.
_TYPE_TO_CONNECTION_KIND: dict[str, ConnectionKind] = {
    "egdb": "enterprise-geodatabase",
    "enterprisegeodatabase": "enterprise-geodatabase",
    "enterprise-geodatabase": "enterprise-geodatabase",
    "relational": "relational",
    "rdbms": "relational",
    "database": "relational",
    "cloudstore": "cloud-store",
    "cloud-store": "cloud-store",
    "cloud": "cloud-store",
    "objectstore": "object-store",
    "object-store": "object-store",
    "folder": "file-share",
    "fileshare": "file-share",
    "file-share": "file-share",
    "filegdb": "file-share",
    "filegeodatabase": "file-share",
    "shapefile": "file-share",
    "bigdatafileshare": "big-data-file-share",
    "big-data-file-share": "big-data-file-share",
    "bds": "big-data-file-share",
}

# Map a coarse connection kind to the recommended binding mode.
_CONNECTION_KIND_TO_BINDING: dict[ConnectionKind, BindingMode] = {
    "enterprise-geodatabase": "federate",
    "relational": "federate",
    "cloud-store": "connect-in-place",
    "object-store": "connect-in-place",
    "big-data-file-share": "connect-in-place",
    "file-share": "materialize",
    "unknown": "materialize",
}


@dataclass(frozen=True)
class DatastoreRegistration:
    """A single ``/admin/data/items`` registration, already redacted.

    ``connection_kind`` is derived from the registration's declared type only.
    No connection string, host, user, or password is ever retained.
    """

    item_id: str
    type: str
    connection_kind: ConnectionKind


@dataclass(frozen=True)
class DatasetBinding:
    """Per-dataset binding-mode recommendation for the handoff artifact."""

    dataset_id: str
    storage_type: str
    connection_kind: ConnectionKind
    binding_mode: BindingMode

    def to_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "storageType": self.storage_type,
            "connectionKind": self.connection_kind,
            "bindingMode": self.binding_mode,
        }


@dataclass(frozen=True)
class UsageRankedService:
    """A service with its observed request volume and migration rank."""

    service: str
    requests: int
    rank: int

    def to_dict(self) -> dict[str, Any]:
        return {"service": self.service, "requests": self.requests, "rank": self.rank}


@dataclass(frozen=True)
class BindingPlan:
    """Combined usage-ranking + binding-mode planning facet."""

    usage_ranked_services: list[UsageRankedService] = field(default_factory=list)
    dataset_bindings: list[DatasetBinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "usageRankedServices": [s.to_dict() for s in self.usage_ranked_services],
            "datasetBindings": [b.to_dict() for b in self.dataset_bindings],
        }


def connection_kind_for_type(storage_type: str) -> ConnectionKind:
    """Classify a registration ``type`` into a coarse connection kind.

    Detection is by the declared type token only; unknown tokens fall back to
    ``"unknown"`` (which routes to ``materialize``).
    """

    normalized = storage_type.strip().lower().replace("_", "").replace(" ", "")
    return _TYPE_TO_CONNECTION_KIND.get(normalized, "unknown")


def binding_mode_for_connection(connection_kind: ConnectionKind) -> BindingMode:
    """Recommend a binding mode for a coarse connection kind."""

    return _CONNECTION_KIND_TO_BINDING.get(connection_kind, "materialize")


def recommend_binding(registration: DatastoreRegistration) -> DatasetBinding:
    """Recommend a binding mode for a single data-store registration."""

    return DatasetBinding(
        dataset_id=registration.item_id,
        storage_type=registration.type,
        connection_kind=registration.connection_kind,
        binding_mode=binding_mode_for_connection(registration.connection_kind),
    )


def rank_services_by_usage(usage: dict[str, int]) -> list[UsageRankedService]:
    """Rank services by descending observed request volume.

    Ties break alphabetically so ordering is deterministic. The returned list
    is what drives usage-driven migration sequencing, replacing any heuristic
    ordering. ``rank`` is 1-based.
    """

    ordered = sorted(usage.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        UsageRankedService(service=service, requests=requests, rank=index + 1)
        for index, (service, requests) in enumerate(ordered)
    ]


def build_binding_plan(
    *,
    usage: dict[str, int],
    registrations: list[DatastoreRegistration],
) -> BindingPlan:
    """Assemble the combined usage-ranking + binding-mode planning facet."""

    return BindingPlan(
        usage_ranked_services=rank_services_by_usage(usage),
        dataset_bindings=[recommend_binding(reg) for reg in registrations],
    )


__all__ = [
    "BindingMode",
    "BindingPlan",
    "ConnectionKind",
    "DatasetBinding",
    "DatastoreRegistration",
    "UsageRankedService",
    "binding_mode_for_connection",
    "build_binding_plan",
    "connection_kind_for_type",
    "rank_services_by_usage",
    "recommend_binding",
]
