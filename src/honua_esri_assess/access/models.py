"""Dataclasses that describe the access facet.

The wire shape under ``portal.access`` / ``server.access`` is produced by
:mod:`honua_esri_assess.footprint.access`. Keep this module free of wire-
serialization concerns so that schema renames stay a one-file change.

Fields that could carry secrets (email, password hash, MFA seed, OAuth
client secret, session token) are intentionally absent from every
dataclass. Adding such a field requires a schema bump plus a redaction
test extension.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


UserStatus = Literal["active", "disabled", "unknown"]
RoleScope = Literal["admin", "publisher", "user", "custom"]
AccessLevel = Literal["private", "org", "public", "shared"]
PrincipalKind = Literal["user", "role", "group"]
MappingConfidence = Literal["high", "medium", "low"]
HonuaBuiltinRole = Literal["admin", "editor", "viewer"]


@dataclass(frozen=True)
class UserPrincipal:
    """One user account observed during the access enumeration.

    ``username`` is carried verbatim because the round-trip Honua RBAC
    mapping needs it. ``full_name`` is dropped when it looks like an
    email address. ``email``, ``password_hash``, MFA seeds, OAuth client
    secrets, and session tokens are intentionally absent.
    """

    username: str
    full_name: str | None = None
    role_id: str | None = None
    user_type: str | None = None
    status: UserStatus = "unknown"
    last_login: str | None = None
    group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoleDefinition:
    """One Esri role definition with its associated privilege names."""

    id: str
    name: str
    scope: RoleScope
    privileges: tuple[str, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class GroupDefinition:
    """One Esri group observed during the access enumeration."""

    id: str
    title: str
    access: AccessLevel
    owner: str
    capabilities: tuple[str, ...] = ()
    is_invitation_only: bool = False
    is_view_only: bool = False
    member_count: int | None = None
    shared_item_count: int | None = None


@dataclass(frozen=True)
class ItemSharing:
    """Sharing state of a single Portal item."""

    item_id: str
    owner: str
    access_level: AccessLevel
    shared_with_group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServicePermission:
    """Per-service ArcGIS Server permission record."""

    service_url: str
    principal: str
    principal_kind: PrincipalKind
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class OrgSecurityPolicy:
    """Org-wide security configuration summary.

    Every field is optional: producers default to ``None`` when the source
    endpoint does not expose the value for the calling token's scope.
    """

    mfa_required: bool | None = None
    sign_in_methods: tuple[str, ...] = ()
    password_min_length: int | None = None
    password_complexity: bool | None = None
    allowed_origins: tuple[str, ...] = ()
    session_expiry_minutes: int | None = None


@dataclass(frozen=True)
class HonuaRoleMapping:
    """One suggested Esri role → Honua role mapping."""

    esri_role_id: str
    honua_role: str
    builtin: HonuaBuiltinRole | None
    confidence: MappingConfidence
    rationale: str


@dataclass(frozen=True)
class OidcRoleClaimMapping:
    """One suggested OIDC role-claim assignment for a Honua role."""

    honua_role: str
    claim_name: str
    claim_value: str
    confidence: MappingConfidence


@dataclass(frozen=True)
class FacadeAccessPolicy:
    """One suggested Portal-facade access-policy stub."""

    policy_id: str
    access_level: AccessLevel
    item_ids: tuple[str, ...]
    group_ids: tuple[str, ...]
    confidence: MappingConfidence


@dataclass(frozen=True)
class MappingRecommendation:
    """Round-trippable mapping suggestion bundle."""

    honua_roles: tuple[HonuaRoleMapping, ...] = ()
    oidc_role_claims: tuple[OidcRoleClaimMapping, ...] = ()
    facade_access_policies: tuple[FacadeAccessPolicy, ...] = ()


@dataclass(frozen=True)
class PortalAccess:
    """Portal / ArcGIS Online access enumeration result."""

    users: tuple[UserPrincipal, ...] = ()
    roles: tuple[RoleDefinition, ...] = ()
    groups: tuple[GroupDefinition, ...] = ()
    item_sharing: tuple[ItemSharing, ...] = ()
    security_policy: OrgSecurityPolicy | None = None
    mapping_recommendation: MappingRecommendation | None = None


@dataclass(frozen=True)
class ServerAccess:
    """ArcGIS Server access enumeration result."""

    users: tuple[UserPrincipal, ...] = ()
    roles: tuple[RoleDefinition, ...] = ()
    service_permissions: tuple[ServicePermission, ...] = ()
    security_mode: str | None = None
    auth_tier: str | None = None
    mapping_recommendation: MappingRecommendation | None = None


@dataclass(frozen=True)
class AccessFacet:
    """Top-level container for the access export.

    Either side may be ``None`` when its enumeration was not requested or
    was not applicable to the target.
    """

    portal: PortalAccess | None = None
    server: ServerAccess | None = None


__all__ = [
    "AccessFacet",
    "AccessLevel",
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
    "PrincipalKind",
    "RoleDefinition",
    "RoleScope",
    "ServerAccess",
    "ServicePermission",
    "UserPrincipal",
    "UserStatus",
]


def _verify_no_field_collisions() -> None:
    """Trip an import-time assertion if a forbidden field sneaks into a model."""

    forbidden = {
        "email",
        "password_hash",
        "password",
        "mfa_seed",
        "client_secret",
        "token",
    }
    for cls in (
        UserPrincipal,
        RoleDefinition,
        GroupDefinition,
        ItemSharing,
        ServicePermission,
        OrgSecurityPolicy,
    ):
        names = set(cls.__dataclass_fields__)
        leaked = names & forbidden
        if leaked:
            raise AssertionError(
                f"{cls.__name__} declares forbidden field(s): {sorted(leaked)}"
            )


_verify_no_field_collisions()
