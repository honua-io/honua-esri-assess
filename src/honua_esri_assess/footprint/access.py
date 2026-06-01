"""EsriAccessFootprint v0.2 models, builder, and schema validation.

``EsriAccessFootprint.json`` is a documented **sibling** of
``EsriFootprint.json``. It captures the identity / RBAC posture of an Esri
estate -- users, roles + privileges, groups, per-service permissions, item
sharing, and org security configuration -- read-only from documented ArcGIS
``/arcgis/admin/security`` and Portal ``admin``/``community`` endpoints.

The artifact drives Honua RBAC and the Portal facade access policies (see
:mod:`honua_esri_assess.footprint.access_mapping`).

Hard guarantees mirrored from the rest of the project:

* Read-only against Esri: nothing here issues writes.
* Prospect-safe: credentials, tokens, query strings, and URL userinfo are
  never persisted. ``serviceUrl`` is run through
  :func:`honua_esri_assess.redaction.sanitize_handoff_url`; the schema rejects
  any residual unsafe URL component.

Dataclass attributes are ``snake_case``; the emitted JSON is ``camelCase`` to
match the EsriFootprint facets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Mapping

from honua_esri_assess.diagnostics import Diagnostic, PortalSchemaError
from honua_esri_assess.footprint.artifact import installed_tool_version
from honua_esri_assess.redaction import sanitize_handoff_url

SCHEMA_VERSION = "v0.2"
TOOL_NAME = "honua-esri-assess"
SCHEMA_FILENAME = "esri-access-footprint-v0.2.json"
SCHEMA_PACKAGE = "honua_esri_assess.schemas"

SourceKind = Literal["arcgis-online", "arcgis-server"]
IdentityProvider = Literal["arcgis", "enterprise", "saml", "oidc", "unknown"]
RoleType = Literal["administrator", "publisher", "user", "viewer", "custom"]
GroupAccess = Literal["private", "org", "public"]
PrincipalType = Literal["role", "user", "group", "everyone"]
AceAccess = Literal["allow", "deny"]
SharingLevel = Literal["private", "org", "public", "shared"]


@dataclass(frozen=True)
class AccessUser:
    username: str
    role_id: str
    disabled: bool = False
    full_name: str | None = None
    group_ids: list[str] = field(default_factory=list)
    user_type: str | None = None
    provider: IdentityProvider = "unknown"


@dataclass(frozen=True)
class AccessRole:
    id: str
    name: str
    type: RoleType
    privileges: list[str] = field(default_factory=list)
    description: str | None = None


@dataclass(frozen=True)
class AccessGroup:
    id: str
    title: str
    access: GroupAccess
    member_count: int = 0
    owner: str | None = None
    role_id: str | None = None


@dataclass(frozen=True)
class ServicePermission:
    service_url: str
    principal_type: PrincipalType
    principal: str
    access: AceAccess
    operations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EffectivePermission:
    """A resolved grant collapsing every ACE for one (service, principal)."""

    service_url: str
    principal_type: PrincipalType
    principal: str
    effect: AceAccess
    operations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ItemSharing:
    item_id: str
    owner: str
    access: SharingLevel
    shared_group_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OrgSecurity:
    allowed_providers: list[IdentityProvider] = field(default_factory=list)
    multi_factor_auth_required: bool | None = None
    anonymous_access_allowed: bool | None = None
    default_role_id: str | None = None


@dataclass(frozen=True)
class AccessFootprint:
    """In-memory representation of the access-footprint artifact."""

    source_kind: SourceKind
    locator: str
    users: list[AccessUser] = field(default_factory=list)
    roles: list[AccessRole] = field(default_factory=list)
    groups: list[AccessGroup] = field(default_factory=list)
    service_permissions: list[ServicePermission] = field(default_factory=list)
    effective_permissions: list[EffectivePermission] = field(default_factory=list)
    item_sharing: list[ItemSharing] = field(default_factory=list)
    org_security: OrgSecurity = field(default_factory=OrgSecurity)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def _utc(value: datetime | None) -> str:
    moment = value or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _user_to_dict(user: AccessUser) -> dict[str, Any]:
    out: dict[str, Any] = {
        "username": user.username,
        "roleId": user.role_id,
        "disabled": bool(user.disabled),
        "provider": user.provider,
    }
    if user.full_name is not None:
        out["fullName"] = user.full_name
    if user.group_ids:
        out["groupIds"] = list(user.group_ids)
    if user.user_type is not None:
        out["userType"] = user.user_type
    return out


def _role_to_dict(role: AccessRole) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": role.id,
        "name": role.name,
        "type": role.type,
        "privileges": list(role.privileges),
    }
    if role.description is not None:
        out["description"] = role.description
    return out


def _group_to_dict(group: AccessGroup) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": group.id,
        "title": group.title,
        "access": group.access,
        "memberCount": int(group.member_count),
    }
    if group.owner is not None:
        out["owner"] = group.owner
    if group.role_id is not None:
        out["roleId"] = group.role_id
    return out


def _permission_to_dict(perm: ServicePermission) -> dict[str, Any]:
    out: dict[str, Any] = {
        "serviceUrl": sanitize_handoff_url(perm.service_url),
        "principalType": perm.principal_type,
        "principal": perm.principal,
        "access": perm.access,
    }
    if perm.operations:
        out["operations"] = list(perm.operations)
    return out


def _effective_to_dict(perm: EffectivePermission) -> dict[str, Any]:
    out: dict[str, Any] = {
        "serviceUrl": sanitize_handoff_url(perm.service_url),
        "principalType": perm.principal_type,
        "principal": perm.principal,
        "effect": perm.effect,
    }
    if perm.operations:
        out["operations"] = list(perm.operations)
    return out


def resolve_effective_permissions(
    permissions: list[ServicePermission],
) -> list[EffectivePermission]:
    """Collapse raw ACEs into one effective grant per (service, principal).

    Documented, deterministic resolution:

    * Group by ``(serviceUrl, principalType, principal)``. The ``everyone``
      principal is a group key like any other; precedence between principal
      kinds is intentionally *not* applied here -- a downstream policy engine
      decides whether a user inherits a role/group/everyone grant. This keeps
      the collapse lossless and re-derivable.
    * ``deny`` overrides ``allow``: if any ACE in a group denies, the effective
      effect is ``deny``.
    * ``operations`` is the sorted union of every operation seen across the
      collapsed ACEs, so the breakdown survives the collapse.
    * Output order is sorted by ``(serviceUrl, principalType, principal)`` so the
      artifact is byte-stable across runs.
    """

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for perm in permissions:
        url = sanitize_handoff_url(perm.service_url)
        key = (url, perm.principal_type, perm.principal)
        slot = grouped.get(key)
        if slot is None:
            slot = {"effect": "allow", "operations": set()}
            grouped[key] = slot
        if perm.access == "deny":
            slot["effect"] = "deny"
        slot["operations"].update(perm.operations)

    resolved: list[EffectivePermission] = []
    for (url, principal_type, principal), slot in grouped.items():
        resolved.append(
            EffectivePermission(
                service_url=url,
                principal_type=principal_type,  # type: ignore[arg-type]
                principal=principal,
                effect=slot["effect"],  # type: ignore[arg-type]
                operations=sorted(slot["operations"]),
            )
        )
    resolved.sort(key=lambda p: (p.service_url, p.principal_type, p.principal))
    return resolved


def _sharing_to_dict(sharing: ItemSharing) -> dict[str, Any]:
    out: dict[str, Any] = {
        "itemId": sharing.item_id,
        "owner": sharing.owner,
        "access": sharing.access,
    }
    if sharing.shared_group_ids:
        out["sharedGroupIds"] = list(sharing.shared_group_ids)
    return out


def _org_security_to_dict(org: OrgSecurity) -> dict[str, Any]:
    out: dict[str, Any] = {"allowedProviders": list(org.allowed_providers)}
    if org.multi_factor_auth_required is not None:
        out["multiFactorAuthRequired"] = org.multi_factor_auth_required
    if org.anonymous_access_allowed is not None:
        out["anonymousAccessAllowed"] = org.anonymous_access_allowed
    if org.default_role_id is not None:
        out["defaultRoleId"] = org.default_role_id
    return out


def build_access_footprint(
    footprint: AccessFootprint,
    *,
    generated_at: datetime | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Render an :class:`AccessFootprint` to the v0.2 wire shape.

    ``effectivePermissions`` is derived from ``service_permissions`` via
    :func:`resolve_effective_permissions` when the footprint does not already
    carry an explicit collapse, so the artifact always ships the resolved view
    alongside the raw ACEs.
    """

    effective = footprint.effective_permissions or resolve_effective_permissions(
        footprint.service_permissions
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _utc(generated_at),
        "tool": {"name": TOOL_NAME, "version": installed_tool_version()},
        "source": {
            "kind": footprint.source_kind,
            "locator": sanitize_handoff_url(footprint.locator),
            "capturedAt": _utc(captured_at or generated_at),
        },
        "users": [_user_to_dict(u) for u in footprint.users],
        "roles": [_role_to_dict(r) for r in footprint.roles],
        "groups": [_group_to_dict(g) for g in footprint.groups],
        "servicePermissions": [
            _permission_to_dict(p) for p in footprint.service_permissions
        ],
        "effectivePermissions": [_effective_to_dict(p) for p in effective],
        "itemSharing": [_sharing_to_dict(s) for s in footprint.item_sharing],
        "orgSecurity": _org_security_to_dict(footprint.org_security),
        "diagnostics": [d.to_dict() for d in footprint.diagnostics],
    }


def access_footprint_to_json(footprint: Mapping[str, Any]) -> str:
    """Serialize with stable, human-readable formatting."""

    return json.dumps(footprint, indent=2, sort_keys=True) + "\n"


def write_access_footprint(footprint: Mapping[str, Any], output: Path) -> None:
    """Write an ``EsriAccessFootprint.json`` artifact."""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(access_footprint_to_json(footprint), encoding="utf-8")


def load_access_schema() -> dict[str, Any]:
    """Return the bundled EsriAccessFootprint v0.1 JSON Schema."""

    try:
        traversable = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_FILENAME)
        raw = traversable.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise PortalSchemaError(
            "The EsriAccessFootprint.json schema is not bundled with the package.",
            context={"schema": SCHEMA_FILENAME},
        ) from exc
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise PortalSchemaError(
            "The EsriAccessFootprint.json schema is not a JSON object.",
            context={"schema": SCHEMA_FILENAME},
        )
    return payload


def validate_access_footprint(footprint: Mapping[str, Any]) -> bool:
    """Validate *footprint* against the bundled access-footprint schema."""

    schema = load_access_schema()
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dev dependency present in CI
        raise PortalSchemaError(
            "The jsonschema package is required to validate EsriAccessFootprint.json."
        ) from exc

    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    try:
        validator.validate(dict(footprint))
    except jsonschema.ValidationError as exc:
        field_path = ".".join(str(part) for part in exc.absolute_path)
        context = {"field": field_path} if field_path else {}
        raise PortalSchemaError(
            "Generated EsriAccessFootprint.json does not match the v0.2 schema.",
            context=context,
        ) from exc
    return True


__all__ = [
    "AccessFootprint",
    "AccessGroup",
    "AccessRole",
    "AccessUser",
    "EffectivePermission",
    "ItemSharing",
    "OrgSecurity",
    "SCHEMA_FILENAME",
    "SCHEMA_PACKAGE",
    "SCHEMA_VERSION",
    "ServicePermission",
    "TOOL_NAME",
    "access_footprint_to_json",
    "build_access_footprint",
    "load_access_schema",
    "resolve_effective_permissions",
    "validate_access_footprint",
    "write_access_footprint",
]
