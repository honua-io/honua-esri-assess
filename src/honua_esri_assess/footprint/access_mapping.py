"""Map an EsriAccessFootprint to Honua RBAC + Portal-facade access policies.

This is the auth-mapping transform half of the RBAC export. It is a pure,
in-memory function over an :class:`~honua_esri_assess.footprint.access.AccessFootprint`
(or its serialized dict) and emits a typed mapping target:

* ``honuaRoles``        -- Honua roles, one per Esri role, carrying the Honua
  permission verbs the role's Esri privileges imply.
* ``oidcRoleClaims``    -- OIDC ``roles`` claim values -> Honua role id, so the
  IdP can drive role assignment after migration.
* ``accessPolicies``    -- Portal-facade access policies, one per observed
  service permission and per item-sharing record, expressed as
  allow/deny rules over Honua principals.

It is intentionally a *first* mapping: the privilege->verb table covers the
common Esri built-ins and degrades unknown privileges to ``unmapped`` rather
than guessing. No credentials flow through here -- the input artifact is
already prospect-safe.
"""

from __future__ import annotations

from typing import Any, Mapping

from honua_esri_assess.footprint.access import (
    AccessFootprint,
    build_access_footprint,
)

# Esri privilege id -> Honua permission verb. A documented, conservative first
# table; unknown privileges are surfaced as ``unmapped`` so the migration
# product can review them rather than silently dropping access.
_PRIVILEGE_TO_VERB: dict[str, str] = {
    "portal:user:createItem": "content:create",
    "portal:user:shareToGroup": "content:share",
    "portal:user:shareToOrg": "content:share",
    "portal:user:shareToPublic": "content:publish",
    "portal:user:viewOrgItems": "content:read",
    "portal:user:viewOrgUsers": "identity:read",
    "portal:user:viewOrgGroups": "group:read",
    "portal:publisher:publishFeatures": "service:publish",
    "portal:publisher:publishTiles": "service:publish",
    "portal:admin:manageRoles": "rbac:manage",
    "portal:admin:manageUsers": "identity:manage",
    "portal:admin:manageSecurity": "security:manage",
    "portal:admin:viewUsers": "identity:read",
}

# Esri built-in role family -> Honua role id stem.
_ROLE_TYPE_TO_HONUA: dict[str, str] = {
    "administrator": "honua.admin",
    "publisher": "honua.editor",
    "user": "honua.member",
    "viewer": "honua.viewer",
    "custom": "honua.custom",
}


def _as_footprint_dict(
    footprint: AccessFootprint | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(footprint, AccessFootprint):
        return build_access_footprint(footprint)
    return dict(footprint)


def _honua_role_id(role: Mapping[str, Any]) -> str:
    stem = _ROLE_TYPE_TO_HONUA.get(str(role.get("type", "custom")), "honua.custom")
    if stem == "honua.custom":
        return f"{stem}.{role.get('id', 'unknown')}"
    return stem


def _verbs_for(privileges: list[Any]) -> tuple[list[str], list[str]]:
    verbs: list[str] = []
    unmapped: list[str] = []
    for priv in privileges:
        priv_id = str(priv)
        verb = _PRIVILEGE_TO_VERB.get(priv_id)
        if verb is None:
            unmapped.append(priv_id)
        elif verb not in verbs:
            verbs.append(verb)
    return verbs, unmapped


def map_to_honua_rbac(
    footprint: AccessFootprint | Mapping[str, Any],
) -> dict[str, Any]:
    """Transform an access footprint into a Honua RBAC + facade mapping."""

    data = _as_footprint_dict(footprint)
    roles = data.get("roles", []) or []

    role_id_index: dict[str, str] = {}
    honua_roles: list[dict[str, Any]] = []
    oidc_role_claims: list[dict[str, str]] = []

    for role in roles:
        if not isinstance(role, Mapping):
            continue
        esri_id = str(role.get("id", "unknown"))
        honua_id = _honua_role_id(role)
        role_id_index[esri_id] = honua_id
        verbs, unmapped = _verbs_for(list(role.get("privileges", []) or []))
        honua_roles.append(
            {
                "honuaRoleId": honua_id,
                "sourceRoleId": esri_id,
                "sourceRoleName": str(role.get("name", esri_id)),
                "permissions": verbs,
                "unmappedPrivileges": unmapped,
            }
        )
        # OIDC: an IdP role-claim value that should resolve to the Honua role.
        oidc_role_claims.append(
            {
                "claim": "roles",
                "value": str(role.get("name", esri_id)),
                "honuaRoleId": honua_id,
            }
        )

    access_policies = _facade_policies(data, role_id_index)

    return {
        "honuaRoles": honua_roles,
        "oidcRoleClaims": oidc_role_claims,
        "accessPolicies": access_policies,
    }


def _facade_policies(
    data: Mapping[str, Any],
    role_id_index: Mapping[str, str],
) -> list[dict[str, Any]]:
    policies: list[dict[str, Any]] = []

    for perm in data.get("servicePermissions", []) or []:
        if not isinstance(perm, Mapping):
            continue
        principal_type = str(perm.get("principalType", "everyone"))
        principal = str(perm.get("principal", "*"))
        if principal_type == "role":
            principal = role_id_index.get(principal, principal)
        policies.append(
            {
                "resource": str(perm.get("serviceUrl", "")),
                "resourceType": "service",
                "principalType": principal_type,
                "principal": principal,
                "effect": str(perm.get("access", "deny")),
            }
        )

    for sharing in data.get("itemSharing", []) or []:
        if not isinstance(sharing, Mapping):
            continue
        access = str(sharing.get("access", "private"))
        policies.append(
            {
                "resource": str(sharing.get("itemId", "")),
                "resourceType": "item",
                "principalType": _sharing_principal_type(access),
                "principal": _sharing_principal(access, sharing),
                "effect": "allow" if access != "private" else "deny",
            }
        )

    return policies


def _sharing_principal_type(access: str) -> str:
    if access == "public":
        return "everyone"
    if access == "shared":
        return "group"
    return "org"


def _sharing_principal(access: str, sharing: Mapping[str, Any]) -> str:
    if access == "public":
        return "*"
    if access == "shared":
        group_ids = sharing.get("sharedGroupIds") or []
        return ",".join(str(g) for g in group_ids) if group_ids else "shared"
    return "org"


__all__ = ["map_to_honua_rbac"]
