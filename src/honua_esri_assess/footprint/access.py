"""Access facet wire shape for the EsriFootprint.json 0.2.x line.

The dataclasses in :mod:`honua_esri_assess.access.models` are the canonical
in-memory representation. This module is the **single point** where they
become a dict that the artifact embeds under ``portal.access`` /
``server.access``. A field rename therefore touches this file plus the
JSON Schema and schema reference docs for the active contract line.

Field naming uses ``camelCase`` to match the rest of the v0.x facets;
dataclass attributes stay ``snake_case`` to match Python style.
"""

from __future__ import annotations

from typing import Any

from honua_esri_assess.access.models import (
    AccessFacet,
    FacadeAccessPolicy,
    GroupDefinition,
    HonuaRoleMapping,
    ItemSharing,
    MappingRecommendation,
    OidcRoleClaimMapping,
    OrgSecurityPolicy,
    PortalAccess,
    RoleDefinition,
    ServerAccess,
    ServicePermission,
    UserPrincipal,
)
from honua_esri_assess.server._safe import credential_free_url


def _user_principal_to_dict(user: UserPrincipal) -> dict[str, Any]:
    out: dict[str, Any] = {
        "username": user.username,
        "status": user.status,
        "groupIds": list(user.group_ids),
    }
    if user.full_name is not None:
        out["fullName"] = user.full_name
    if user.role_id is not None:
        out["roleId"] = user.role_id
    if user.user_type is not None:
        out["userType"] = user.user_type
    if user.last_login is not None:
        out["lastLogin"] = user.last_login
    return out


def _role_definition_to_dict(role: RoleDefinition) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": role.id,
        "name": role.name,
        "scope": role.scope,
        "privileges": list(role.privileges),
    }
    if role.description is not None:
        out["description"] = role.description
    return out


def _group_definition_to_dict(group: GroupDefinition) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": group.id,
        "title": group.title,
        "access": group.access,
        "owner": group.owner,
        "capabilities": list(group.capabilities),
        "isInvitationOnly": group.is_invitation_only,
        "isViewOnly": group.is_view_only,
    }
    if group.member_count is not None:
        out["memberCount"] = group.member_count
    if group.shared_item_count is not None:
        out["sharedItemCount"] = group.shared_item_count
    return out


def _item_sharing_to_dict(sharing: ItemSharing) -> dict[str, Any]:
    return {
        "itemId": sharing.item_id,
        "owner": sharing.owner,
        "accessLevel": sharing.access_level,
        "sharedWithGroupIds": list(sharing.shared_with_group_ids),
    }


def _service_permission_to_dict(perm: ServicePermission) -> dict[str, Any]:
    return {
        "serviceUrl": credential_free_url(perm.service_url),
        "principal": perm.principal,
        "principalKind": perm.principal_kind,
        "capabilities": list(perm.capabilities),
    }


def _security_policy_to_dict(policy: OrgSecurityPolicy) -> dict[str, Any]:
    out: dict[str, Any] = {
        "signInMethods": list(policy.sign_in_methods),
        "allowedOrigins": list(policy.allowed_origins),
    }
    if policy.mfa_required is not None:
        out["mfaRequired"] = policy.mfa_required
    if policy.password_min_length is not None:
        out["passwordMinLength"] = policy.password_min_length
    if policy.password_complexity is not None:
        out["passwordComplexity"] = policy.password_complexity
    if policy.session_expiry_minutes is not None:
        out["sessionExpiryMinutes"] = policy.session_expiry_minutes
    return out


def _honua_role_mapping_to_dict(mapping: HonuaRoleMapping) -> dict[str, Any]:
    out: dict[str, Any] = {
        "esriRoleId": mapping.esri_role_id,
        "honuaRole": mapping.honua_role,
        "confidence": mapping.confidence,
        "rationale": mapping.rationale,
    }
    if mapping.builtin is not None:
        out["builtin"] = mapping.builtin
    return out


def _oidc_claim_to_dict(claim: OidcRoleClaimMapping) -> dict[str, Any]:
    return {
        "honuaRole": claim.honua_role,
        "claimName": claim.claim_name,
        "claimValue": claim.claim_value,
        "confidence": claim.confidence,
    }


def _facade_policy_to_dict(policy: FacadeAccessPolicy) -> dict[str, Any]:
    return {
        "policyId": policy.policy_id,
        "accessLevel": policy.access_level,
        "itemIds": list(policy.item_ids),
        "groupIds": list(policy.group_ids),
        "confidence": policy.confidence,
    }


def _mapping_recommendation_to_dict(
    recommendation: MappingRecommendation,
) -> dict[str, Any]:
    return {
        "honuaRoles": [
            _honua_role_mapping_to_dict(r) for r in recommendation.honua_roles
        ],
        "oidcRoleClaims": [
            _oidc_claim_to_dict(c) for c in recommendation.oidc_role_claims
        ],
        "facadeAccessPolicies": [
            _facade_policy_to_dict(p) for p in recommendation.facade_access_policies
        ],
    }


def portal_access_to_dict(access: PortalAccess) -> dict[str, Any]:
    out: dict[str, Any] = {
        "users": [_user_principal_to_dict(u) for u in access.users],
        "roles": [_role_definition_to_dict(r) for r in access.roles],
        "groups": [_group_definition_to_dict(g) for g in access.groups],
        "itemSharing": [_item_sharing_to_dict(s) for s in access.item_sharing],
    }
    if access.security_policy is not None:
        out["securityPolicy"] = _security_policy_to_dict(access.security_policy)
    if access.mapping_recommendation is not None:
        out["mappingRecommendation"] = _mapping_recommendation_to_dict(
            access.mapping_recommendation
        )
    return out


def server_access_to_dict(access: ServerAccess) -> dict[str, Any]:
    out: dict[str, Any] = {
        "users": [_user_principal_to_dict(u) for u in access.users],
        "roles": [_role_definition_to_dict(r) for r in access.roles],
        "servicePermissions": [
            _service_permission_to_dict(p) for p in access.service_permissions
        ],
    }
    if access.security_mode is not None:
        out["securityMode"] = access.security_mode
    if access.auth_tier is not None:
        out["authTier"] = access.auth_tier
    if access.mapping_recommendation is not None:
        out["mappingRecommendation"] = _mapping_recommendation_to_dict(
            access.mapping_recommendation
        )
    return out


def access_facet_to_dict(facet: AccessFacet) -> dict[str, Any]:
    """Render an :class:`AccessFacet` as a fragment.

    The fragment shape is ``{"portal": {"access": {...}}, "server": {"access": {...}}}``.
    The :func:`apply_access_facet` helper folds it into a v0.2 footprint.
    """

    out: dict[str, Any] = {}
    if facet.portal is not None:
        out["portal"] = {"access": portal_access_to_dict(facet.portal)}
    if facet.server is not None:
        out["server"] = {"access": server_access_to_dict(facet.server)}
    return out


def apply_access_facet(
    footprint: dict[str, Any],
    facet: AccessFacet,
) -> dict[str, Any]:
    """Embed the access facet into a v0.1 footprint, returning a v0.2 footprint.

    The input footprint is shallow-copied and ``schemaVersion`` is set to
    ``"v0.2"``. When the facet supplies an empty :class:`PortalAccess` /
    :class:`ServerAccess`, the resulting ``access`` block carries empty
    required arrays so consumers can distinguish "asked but blocked"
    from "didn't ask" (the latter omits the ``access`` key entirely).
    """

    out = dict(footprint)
    out["schemaVersion"] = SCHEMA_VERSION_V0_2
    portal_block = out.get("portal")
    if facet.portal is not None and isinstance(portal_block, dict):
        new_portal = dict(portal_block)
        new_portal["access"] = portal_access_to_dict(facet.portal)
        out["portal"] = new_portal
    server_block = out.get("server")
    if facet.server is not None and isinstance(server_block, dict):
        new_server = dict(server_block)
        new_server["access"] = server_access_to_dict(facet.server)
        out["server"] = new_server
    return out


SCHEMA_VERSION_V0_2 = "v0.2"


__all__ = [
    "SCHEMA_VERSION_V0_2",
    "access_facet_to_dict",
    "apply_access_facet",
    "portal_access_to_dict",
    "server_access_to_dict",
]
