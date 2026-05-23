"""Licensing facet wire shape for the EsriFootprint.json 0.1.x line.

The dataclasses in :mod:`honua_esri_assess.entitlements.models` are the
canonical in-memory representation. This module is the **single point**
where they become a dict that the artifact embeds under
``portal.licensing`` / ``server.licensing``. A field rename therefore touches
this file plus the JSON Schema and schema reference docs for the active
contract line.

Field naming uses ``camelCase`` to match the rest of the v0.1 facets that
E2 owns; dataclass attributes stay ``snake_case`` to match Python style.
"""

from __future__ import annotations

from typing import Any

from ..entitlements.models import (
    ExtensionEntitlement,
    LicensingFacet,
    PortalLicensing,
    ServerLicensing,
    ServiceExtensionRecord,
    UserTypeCount,
)


def _extension_to_dict(ext: ExtensionEntitlement) -> dict[str, str]:
    return {
        "code": ext.code,
        "name": ext.name,
        "status": ext.status,
        "source": ext.source,
    }


def _user_type_to_dict(ut: UserTypeCount) -> dict[str, Any]:
    out: dict[str, Any] = {"name": ut.name}
    if ut.total is not None:
        out["total"] = ut.total
    if ut.assigned is not None:
        out["assigned"] = ut.assigned
    return out


def _service_extension_to_dict(record: ServiceExtensionRecord) -> dict[str, Any]:
    return {
        "serviceUrl": record.service_url,
        "soes": list(record.soes),
        "sois": list(record.sois),
    }


def portal_licensing_to_dict(licensing: PortalLicensing) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if licensing.tier is not None:
        out["tier"] = licensing.tier
    if licensing.subscription_type is not None:
        out["subscriptionType"] = licensing.subscription_type
    out["userTypes"] = [_user_type_to_dict(ut) for ut in licensing.user_types]
    premium: dict[str, Any] = {}
    if licensing.premium_credits_enabled is not None:
        premium["creditsEnabled"] = licensing.premium_credits_enabled
    premium["allowedAddOns"] = list(licensing.allowed_add_ons)
    out["premiumContent"] = premium
    out["extensionsObserved"] = [
        _extension_to_dict(e) for e in licensing.extensions_observed
    ]
    return out


def server_licensing_to_dict(licensing: ServerLicensing) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if licensing.product_name is not None:
        out["productName"] = licensing.product_name
    if licensing.current_version is not None:
        out["currentVersion"] = licensing.current_version
    if licensing.edition is not None:
        out["edition"] = licensing.edition
    out["extensions"] = [_extension_to_dict(e) for e in licensing.extensions]
    out["serviceExtensions"] = [
        _service_extension_to_dict(r) for r in licensing.service_extensions
    ]
    return out


def licensing_facet_to_dict(facet: LicensingFacet) -> dict[str, Any]:
    """Render a :class:`LicensingFacet` as the wire-shape fragment.

    The returned dict is meant to slot inside the v0.1 ``portal`` and
    ``server`` facets through their explicit ``licensing`` properties, so
    no top-level schema change is requested.
    """

    out: dict[str, Any] = {}
    if facet.portal is not None:
        out["portal"] = {"licensing": portal_licensing_to_dict(facet.portal)}
    if facet.server is not None:
        out["server"] = {"licensing": server_licensing_to_dict(facet.server)}
    return out
