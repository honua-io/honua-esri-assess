"""Esri license entitlement enumeration.

Public surface of the entitlements module. Read-only against Esri systems;
the collectors only ever issue HTTP GET and never write back. Soft failures
become typed ``Diagnostic`` records; hard failures raise
``EntitlementsError`` subclasses.
"""

from __future__ import annotations

from .diagnostics import (
    AssessmentError,
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    EntitlementsApiError,
    EntitlementsAuthError,
    EntitlementsConnectionError,
    EntitlementsError,
    EntitlementsForbiddenError,
    EntitlementsNotFoundError,
    EntitlementsRateLimitedError,
    EntitlementsSchemaError,
)
from .extensions import (
    ExtensionCatalogEntry,
    extension_catalog,
    resolve_extension,
)
from .http import HttpClient, RequestsHttpClient, safe_url
from .models import (
    ExtensionEntitlement,
    LicensingFacet,
    PortalLicensing,
    ServerLicensing,
    ServiceExtensionRecord,
    UserTypeCount,
)
from .portal import PortalEntitlementsCollector, PortalEntitlementsResult
from .server import (
    ServerEntitlementsCollector,
    ServerEntitlementsResult,
    ServiceRef,
)

__all__ = [
    "AssessmentError",
    "Diagnostic",
    "DiagnosticCode",
    "DiagnosticSeverity",
    "EntitlementsApiError",
    "EntitlementsAuthError",
    "EntitlementsConnectionError",
    "EntitlementsError",
    "EntitlementsForbiddenError",
    "EntitlementsNotFoundError",
    "EntitlementsRateLimitedError",
    "EntitlementsSchemaError",
    "ExtensionCatalogEntry",
    "ExtensionEntitlement",
    "HttpClient",
    "LicensingFacet",
    "PortalEntitlementsCollector",
    "PortalEntitlementsResult",
    "PortalLicensing",
    "RequestsHttpClient",
    "ServerEntitlementsCollector",
    "ServerEntitlementsResult",
    "ServerLicensing",
    "ServiceExtensionRecord",
    "ServiceRef",
    "UserTypeCount",
    "extension_catalog",
    "resolve_extension",
    "safe_url",
]
