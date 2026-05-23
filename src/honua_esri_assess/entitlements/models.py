"""Dataclasses that describe the licensing facet.

The wire shape under ``portal.licensing`` / ``server.licensing`` is produced
by :mod:`honua_esri_assess.footprint.v0_1`. Keep this module free of wire-
serialization concerns so that schema renames stay a one-file change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ExtensionStatus = Literal["licensed", "evaluation", "expired", "unknown"]
ExtensionSource = Literal[
    "server-admin-licenses",
    "service-extensions",
    "portal-subscription",
]


@dataclass(frozen=True)
class ExtensionEntitlement:
    """One Esri extension observed during enumeration."""

    code: str
    name: str
    status: ExtensionStatus
    source: ExtensionSource


@dataclass(frozen=True)
class UserTypeCount:
    """Per-user-type license count.

    ``total`` is the seat count granted to the org; ``assigned`` is how many
    are currently provisioned. Either may be ``None`` when the endpoint
    does not expose the field for the calling token's scope.
    """

    name: str
    total: int | None = None
    assigned: int | None = None


@dataclass(frozen=True)
class PortalLicensing:
    """Licensing facet for an AGOL / Enterprise Portal target."""

    tier: str | None = None
    subscription_type: str | None = None
    user_types: list[UserTypeCount] = field(default_factory=list)
    premium_credits_enabled: bool | None = None
    allowed_add_ons: list[str] = field(default_factory=list)
    extensions_observed: list[ExtensionEntitlement] = field(default_factory=list)


@dataclass(frozen=True)
class ServiceExtensionRecord:
    """SOEs and SOIs enabled on a single ArcGIS Server service."""

    service_url: str
    soes: list[str] = field(default_factory=list)
    sois: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ServerLicensing:
    """Licensing facet for an ArcGIS Server target."""

    product_name: str | None = None
    current_version: str | None = None
    edition: str | None = None
    extensions: list[ExtensionEntitlement] = field(default_factory=list)
    service_extensions: list[ServiceExtensionRecord] = field(default_factory=list)


@dataclass(frozen=True)
class LicensingFacet:
    """Top-level container.

    Either side may be ``None`` when its enumeration was not requested or
    was not applicable to the target (e.g., AGOL-only scans leave
    ``server`` unset).
    """

    portal: PortalLicensing | None = None
    server: ServerLicensing | None = None
