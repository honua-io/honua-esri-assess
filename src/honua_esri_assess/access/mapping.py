"""Pure-function mapper from collected Esri access data → Honua suggestions.

The mapper has no network or filesystem I/O. Inputs are
:class:`PortalAccess` / :class:`ServerAccess`; output is a
:class:`MappingRecommendation` that downstream consumers (separate
tickets) materialize into Honua RBAC, OIDC role-claim mappings, and
Portal-facade access policies without re-querying Esri.
"""

from __future__ import annotations

from typing import Iterable

from .models import (
    AccessLevel,
    FacadeAccessPolicy,
    HonuaBuiltinRole,
    HonuaRoleMapping,
    ItemSharing,
    MappingConfidence,
    MappingRecommendation,
    OidcRoleClaimMapping,
    PortalAccess,
    RoleDefinition,
    RoleScope,
    ServerAccess,
)


_BUILTIN_BY_SCOPE: dict[RoleScope, HonuaBuiltinRole] = {
    "admin": "admin",
    "publisher": "editor",
    "user": "viewer",
}

_PRIVILEGE_HONUA_HINTS: tuple[tuple[str, HonuaBuiltinRole], ...] = (
    ("admin", "admin"),
    ("manage", "admin"),
    ("update", "editor"),
    ("create", "editor"),
    ("publish", "editor"),
    ("edit", "editor"),
    ("view", "viewer"),
    ("read", "viewer"),
)

_DEFAULT_CLAIM_NAME = "roles"


def build_recommendation(
    *,
    portal: PortalAccess | None = None,
    server: ServerAccess | None = None,
    claim_name: str = _DEFAULT_CLAIM_NAME,
) -> MappingRecommendation:
    """Project ``portal`` / ``server`` access data into a recommendation."""

    role_inputs: list[RoleDefinition] = []
    if portal is not None:
        role_inputs.extend(portal.roles)
    if server is not None:
        role_inputs.extend(server.roles)

    honua_roles = _honua_role_mappings(role_inputs)
    oidc_claims = _oidc_role_claims(honua_roles, claim_name=claim_name)
    facade_policies = _facade_policies(
        portal.item_sharing if portal is not None else (),
    )
    return MappingRecommendation(
        honua_roles=honua_roles,
        oidc_role_claims=oidc_claims,
        facade_access_policies=facade_policies,
    )


def _honua_role_mappings(
    roles: Iterable[RoleDefinition],
) -> tuple[HonuaRoleMapping, ...]:
    seen: set[str] = set()
    out: list[HonuaRoleMapping] = []
    for role in sorted(roles, key=lambda r: (r.scope, r.id)):
        if role.id in seen:
            continue
        seen.add(role.id)
        if role.scope in _BUILTIN_BY_SCOPE:
            builtin = _BUILTIN_BY_SCOPE[role.scope]
            out.append(
                HonuaRoleMapping(
                    esri_role_id=role.id,
                    honua_role=builtin,
                    builtin=builtin,
                    confidence="high",
                    rationale=(
                        f"Esri scope {role.scope!r} maps directly to Honua "
                        f"{builtin!r}."
                    ),
                )
            )
            continue
        # Custom role — derive a privilege-based hint plus a stable name.
        hinted = _privilege_hint(role.privileges)
        honua_role = f"custom:{role.id}"
        if hinted is None:
            out.append(
                HonuaRoleMapping(
                    esri_role_id=role.id,
                    honua_role=honua_role,
                    builtin=None,
                    confidence="low",
                    rationale=(
                        "Custom Esri role; reviewer should map to a Honua "
                        "role manually."
                    ),
                )
            )
            continue
        out.append(
            HonuaRoleMapping(
                esri_role_id=role.id,
                honua_role=honua_role,
                builtin=hinted,
                confidence="medium",
                rationale=(
                    f"Custom Esri role; privileges resemble Honua "
                    f"{hinted!r}. Confirm before applying."
                ),
            )
        )
    return tuple(out)


def _privilege_hint(privileges: Iterable[str]) -> HonuaBuiltinRole | None:
    text = " ".join(p.lower() for p in privileges)
    if not text:
        return None
    for needle, builtin in _PRIVILEGE_HONUA_HINTS:
        if needle in text:
            return builtin
    return None


def _oidc_role_claims(
    role_mappings: Iterable[HonuaRoleMapping],
    *,
    claim_name: str,
) -> tuple[OidcRoleClaimMapping, ...]:
    seen: set[str] = set()
    out: list[OidcRoleClaimMapping] = []
    for mapping in role_mappings:
        if mapping.honua_role in seen:
            continue
        seen.add(mapping.honua_role)
        confidence: MappingConfidence = (
            "high" if mapping.builtin is not None and mapping.confidence == "high"
            else mapping.confidence
        )
        out.append(
            OidcRoleClaimMapping(
                honua_role=mapping.honua_role,
                claim_name=claim_name,
                claim_value=mapping.honua_role,
                confidence=confidence,
            )
        )
    return tuple(out)


def _facade_policies(
    item_sharing: Iterable[ItemSharing],
) -> tuple[FacadeAccessPolicy, ...]:
    buckets: dict[tuple[AccessLevel, tuple[str, ...]], list[str]] = {}
    for record in item_sharing:
        key = (record.access_level, tuple(sorted(record.shared_with_group_ids)))
        buckets.setdefault(key, []).append(record.item_id)
    policies: list[FacadeAccessPolicy] = []
    for (access_level, group_ids), item_ids in sorted(
        buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])
    ):
        # Stable policy id so downstream consumers can dedupe across runs.
        suffix = "-".join(group_ids) if group_ids else "no-groups"
        policy_id = f"facade:{access_level}:{suffix}"
        confidence: MappingConfidence = (
            "high" if access_level in {"private", "org"} else "medium"
        )
        policies.append(
            FacadeAccessPolicy(
                policy_id=policy_id,
                access_level=access_level,
                item_ids=tuple(sorted(set(item_ids))),
                group_ids=group_ids,
                confidence=confidence,
            )
        )
    return tuple(policies)


__all__ = ["build_recommendation"]
