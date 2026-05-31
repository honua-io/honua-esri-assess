"""Pure-function mapper from collected Esri access data → Honua suggestions.

The mapper has no network or filesystem I/O. Inputs are
:class:`PortalAccess` / :class:`ServerAccess`; output is a
:class:`MappingRecommendation` that downstream consumers (separate
tickets) materialize into Honua RBAC, OIDC role-claim mappings, and
Portal-facade access policies without re-querying Esri.
"""

from __future__ import annotations

import hashlib
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

# v0.2 schema caps for the mapper's derived ids.
_HONUA_ROLE_MAX = 128
_POLICY_ID_MAX = 256
# Reserved suffix budget for deterministic disambiguation: ``.`` separator
# plus 8 hex chars of SHA-1(full body). The ``.`` is in both ``HonuaRoleMapping.honuaRole``
# (unrestricted) and ``FacadeAccessPolicy.policyId`` (pattern allows ``.``).
_HASH_HEX_LEN = 8
_HASH_SEP = "."


def _bounded_id(prefix: str, body: str, *, max_total: int) -> str:
    """Return ``prefix + body`` if it fits ``max_total`` chars.

    When it doesn't, returns ``prefix + truncated_body + "." + hash8`` where
    ``hash8`` is the first 8 hex characters of SHA-1(full body). This keeps
    the resulting identifier deterministic across runs (so the closed
    product can dedupe), bounded to ``max_total``, and shaped to fit both
    the unrestricted ``HonuaRoleMapping.honuaRole`` and the
    ``FacadeAccessPolicy.policyId`` pattern ``^[A-Za-z0-9._:-]{1,256}$``.
    """

    candidate = prefix + body
    if len(candidate) <= max_total:
        return candidate
    remaining = max_total - len(prefix) - _HASH_HEX_LEN - len(_HASH_SEP)
    if remaining <= 0:
        # Prefix alone exhausts the budget; fall back to hash-only suffix.
        digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:_HASH_HEX_LEN]
        return f"{prefix}{_HASH_SEP}{digest}"[:max_total]
    truncated = body[:remaining]
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:_HASH_HEX_LEN]
    return f"{prefix}{truncated}{_HASH_SEP}{digest}"


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
        # Bound the rendered name to the v0.2 ``HonuaRoleMapping.honuaRole``
        # 128-char cap; long Esri role ids get deterministically truncated
        # plus a short hash suffix so consumers can still dedupe.
        hinted = _privilege_hint(role.privileges)
        honua_role = _bounded_id("custom:", role.id, max_total=_HONUA_ROLE_MAX)
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
        # An item with ``access_level == "shared"`` but no concrete group ids
        # cannot anchor a reliable facade-policy stub — emitting one would
        # imply org-wide sharing when the source actually had a group
        # boundary the v0.1 inventory could not capture. The portal
        # collector emits a ``partial-coverage`` diagnostic for this case
        # via ``_normalize_item_sharing``; the mapper just drops them so
        # the recommendation does not overstate confidence.
        if record.access_level == "shared" and not record.shared_with_group_ids:
            continue
        key = (record.access_level, tuple(sorted(record.shared_with_group_ids)))
        buckets.setdefault(key, []).append(record.item_id)
    policies: list[FacadeAccessPolicy] = []
    for (access_level, group_ids), item_ids in sorted(
        buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])
    ):
        # Stable policy id so downstream consumers can dedupe across runs.
        # Two schema-valid 128-char group ids would otherwise overflow the
        # v0.2 ``FacadeAccessPolicy.policyId`` 256-char cap, so route the
        # full suffix through the bounded-id helper.
        suffix = "-".join(group_ids) if group_ids else "no-groups"
        policy_id = _bounded_id(
            f"facade:{access_level}:", suffix, max_total=_POLICY_ID_MAX
        )
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
