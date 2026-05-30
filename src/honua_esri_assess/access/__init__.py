"""Authorized Esri identity/RBAC enumeration.

Public surface of the access module. Read-only against Esri systems; the
collectors only ever issue HTTP GET and never write back. Soft failures
become typed :class:`Diagnostic` records using the locked v0.1 vocabulary;
hard failures raise :class:`AccessExportError` subclasses that the CLI
translates to prospect-safe stderr.
"""

from __future__ import annotations

from .diagnostics import (
    AccessApiError,
    AccessAuthError,
    AccessConnectionError,
    AccessExportError,
    AccessForbiddenError,
    AccessNotFoundError,
    AccessRateLimitedError,
    AccessSchemaError,
)
from .mapping import build_recommendation
from .models import (
    AccessFacet,
    AccessLevel,
    FacadeAccessPolicy,
    GroupDefinition,
    HonuaBuiltinRole,
    HonuaRoleMapping,
    ItemSharing,
    MappingConfidence,
    MappingRecommendation,
    OidcRoleClaimMapping,
    OrgSecurityPolicy,
    PortalAccess,
    PrincipalKind,
    RoleDefinition,
    RoleScope,
    ServerAccess,
    ServicePermission,
    UserPrincipal,
    UserStatus,
)
from .portal import PortalAccessCollector, PortalAccessResult
from .server import ServerAccessCollector, ServerAccessResult

__all__ = [
    "AccessApiError",
    "AccessAuthError",
    "AccessConnectionError",
    "AccessExportError",
    "AccessFacet",
    "AccessForbiddenError",
    "AccessLevel",
    "AccessNotFoundError",
    "AccessRateLimitedError",
    "AccessSchemaError",
    "FacadeAccessPolicy",
    "GroupDefinition",
    "HonuaBuiltinRole",
    "HonuaRoleMapping",
    "ItemSharing",
    "MappingConfidence",
    "MappingRecommendation",
    "OidcRoleClaimMapping",
    "OrgSecurityPolicy",
    "PortalAccess",
    "PortalAccessCollector",
    "PortalAccessResult",
    "PrincipalKind",
    "RoleDefinition",
    "RoleScope",
    "ServerAccess",
    "ServerAccessCollector",
    "ServerAccessResult",
    "ServicePermission",
    "UserPrincipal",
    "UserStatus",
    "build_recommendation",
]
