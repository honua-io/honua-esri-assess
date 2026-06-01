"""Read-only RBAC / access-footprint scanner.

Collects an Esri estate's identity / RBAC posture from documented endpoints
and models it into an
:class:`~honua_esri_assess.footprint.access.AccessFootprint`. It is strictly
GET-only and never writes back to the source.

Documented endpoints consumed (all read-only):

* Portal (ArcGIS Online / Enterprise):
  ``/sharing/rest/portals/self`` (org security config),
  ``/sharing/rest/portals/self/users`` (users),
  ``/sharing/rest/portals/self/roles`` (custom roles),
  ``/sharing/rest/portals/self/roles/<id>/privileges`` (role privileges),
  ``/sharing/rest/community/groups`` (groups).
* ArcGIS Server admin (``/arcgis/admin/*``):
  ``/arcgis/admin/security/roles/getRoles`` (roles),
  ``/arcgis/admin/security/users/getUsers`` (users),
  ``/arcgis/admin/services`` and ``/arcgis/admin/services/<folder>``
  (service catalog, root plus one level of sub-folders),
  ``/arcgis/admin/services/<service>/permissions`` (per-service ACEs, crawled
  across the whole catalog and collapsed into effective grants).

Soft failures (a token without admin scope, a denied endpoint) become typed
:class:`~honua_esri_assess.diagnostics.Diagnostic` records so a partial export
still produces a valid artifact. Credentials and tokens never enter the
artifact: the scanner only copies modeled identity facts, runs URLs through
:func:`honua_esri_assess.redaction.sanitize_handoff_url`, and uses
:func:`honua_esri_assess.entitlements.http.safe_url` for any logged URL.

The scanner depends only on the
:class:`~honua_esri_assess.entitlements.http.HttpClient` protocol, so the
fixture-driven tests stub it with no live Portal required.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urljoin

from honua_esri_assess.diagnostics import Diagnostic
from honua_esri_assess.entitlements.http import HttpClient, HttpResponse, safe_url
from honua_esri_assess.footprint.access import (
    AccessFootprint,
    AccessGroup,
    AccessRole,
    AccessUser,
    GroupAccess,
    IdentityProvider,
    ItemSharing,
    OrgSecurity,
    ServicePermission,
    resolve_effective_permissions,
)
from honua_esri_assess.redaction import sanitize_handoff_url

_PROVIDER_ALIASES: dict[str, IdentityProvider] = {
    "arcgis": "arcgis",
    "enterprise": "enterprise",
    "saml": "saml",
    "oidc": "oidc",
    "openid": "oidc",
}

_GROUP_ACCESS: frozenset[str] = frozenset({"private", "org", "public"})


def scan_portal_rbac(
    target: str,
    client: HttpClient,
    *,
    timeout: float | None = None,
) -> AccessFootprint:
    """Scan an ArcGIS Online / Enterprise Portal target for RBAC posture."""

    base = target.rstrip("/") + "/"
    diagnostics: list[Diagnostic] = []

    portal_self = _get(client, urljoin(base, "portals/self"), "portal.self", diagnostics, timeout)
    org_security = _org_security(portal_self if isinstance(portal_self, dict) else {})

    users_payload = _get(
        client, urljoin(base, "portals/self/users"), "portal.users", diagnostics, timeout
    )
    users = _portal_users(users_payload)

    roles_payload = _get(
        client, urljoin(base, "portals/self/roles"), "portal.roles", diagnostics, timeout
    )
    roles = _portal_roles(base, client, roles_payload, diagnostics, timeout)

    groups_payload = _get(
        client, urljoin(base, "community/groups"), "portal.groups", diagnostics, timeout
    )
    groups = _portal_groups(groups_payload)

    return AccessFootprint(
        source_kind="arcgis-online",
        locator=_portal_locator(target, portal_self),
        users=users,
        roles=roles,
        groups=groups,
        org_security=org_security,
        diagnostics=diagnostics,
    )


def scan_server_rbac(
    target: str,
    client: HttpClient,
    *,
    timeout: float | None = None,
) -> AccessFootprint:
    """Scan an ArcGIS Server admin target for RBAC posture.

    Reads documented ``/arcgis/admin/security`` endpoints. The provided
    ``target`` is the admin base (e.g. ``https://host/arcgis/admin``).
    """

    base = target.rstrip("/") + "/"
    diagnostics: list[Diagnostic] = []

    roles_payload = _get(
        client, urljoin(base, "security/roles/getRoles"), "server.security.roles", diagnostics, timeout
    )
    roles = _server_roles(roles_payload)

    users_payload = _get(
        client, urljoin(base, "security/users/getUsers"), "server.security.users", diagnostics, timeout
    )
    users = _server_users(users_payload)

    service_permissions = _crawl_service_permissions(
        base, target, client, diagnostics, timeout
    )
    effective_permissions = resolve_effective_permissions(service_permissions)

    return AccessFootprint(
        source_kind="arcgis-server",
        locator=sanitize_handoff_url(target),
        users=users,
        roles=roles,
        service_permissions=service_permissions,
        effective_permissions=effective_permissions,
        diagnostics=diagnostics,
    )


# Esri's admin services permission response names the "everyone" principal with
# this reserved id. We model it as the schema's ``everyone`` principal type so
# downstream policy mapping can recognise anonymous access uniformly.
_EVERYONE_PRINCIPAL = "esriEveryone"


def _crawl_service_permissions(
    base: str,
    target: str,
    client: HttpClient,
    diagnostics: list[Diagnostic],
    timeout: float | None,
) -> list[ServicePermission]:
    """Crawl ``/arcgis/admin/services`` and read each service's ACEs.

    Read-only: lists the service catalog (root folder plus one level of
    sub-folders, the documented admin layout) and issues a GET against
    ``services/<service>/permissions`` for every discovered service. Any soft
    failure (denied, missing, rate limited, unreachable) for a single service
    becomes a typed diagnostic and is skipped -- the crawl never aborts.
    """

    services = _list_services(base, client, diagnostics, timeout)
    permissions: list[ServicePermission] = []
    for service in services:
        scope = f"server.services.{service}.permissions"
        payload = _get(
            client,
            urljoin(base, f"services/{service}/permissions"),
            scope,
            diagnostics,
            timeout,
        )
        if not isinstance(payload, dict):
            continue
        service_url = _service_admin_url(target, service)
        permissions.extend(_service_aces(service_url, payload))
    return permissions


def _list_services(
    base: str,
    client: HttpClient,
    diagnostics: list[Diagnostic],
    timeout: float | None,
) -> list[str]:
    """Return fully-qualified service names (``Folder/Name.Type`` or ``Name.Type``)."""

    root = _get(client, urljoin(base, "services"), "server.services", diagnostics, timeout)
    if not isinstance(root, dict):
        return []
    names: list[str] = _services_in_folder(root, prefix="")
    for folder in root.get("folders", []) or []:
        if not isinstance(folder, str) or folder in ("", "/"):
            continue
        scope = f"server.services.{folder}"
        sub = _get(client, urljoin(base, f"services/{folder}"), scope, diagnostics, timeout)
        if isinstance(sub, dict):
            names.extend(_services_in_folder(sub, prefix=f"{folder}/"))
    return names


def _services_in_folder(payload: Mapping[str, Any], *, prefix: str) -> list[str]:
    out: list[str] = []
    for svc in payload.get("services", []) or []:
        if not isinstance(svc, dict):
            continue
        name = svc.get("serviceName") or svc.get("name")
        svc_type = svc.get("type")
        if not isinstance(name, str) or not isinstance(svc_type, str):
            continue
        out.append(f"{prefix}{name}.{svc_type}")
    return out


def _service_admin_url(target: str, service: str) -> str:
    base = sanitize_handoff_url(target).rstrip("/")
    return f"{base}/services/{service}"


def _service_aces(service_url: str, payload: Mapping[str, Any]) -> list[ServicePermission]:
    aces: list[ServicePermission] = []
    for raw in payload.get("permissions", []) or []:
        if not isinstance(raw, dict):
            continue
        principal_raw = raw.get("principal")
        if not isinstance(principal_raw, str) or not principal_raw:
            continue
        permission = raw.get("permission")
        permission = permission if isinstance(permission, dict) else {}
        is_allowed = permission.get("isAllowed")
        access = "allow" if is_allowed else "deny"
        if principal_raw == _EVERYONE_PRINCIPAL:
            principal_type = "everyone"
            principal = "*"
        else:
            principal_type = "role"
            principal = principal_raw
        operations = [
            str(op) for op in permission.get("operations", []) or [] if op
        ]
        aces.append(
            ServicePermission(
                service_url=service_url,
                principal_type=principal_type,  # type: ignore[arg-type]
                principal=principal,
                access=access,  # type: ignore[arg-type]
                operations=operations,
            )
        )
    return aces


def _get(
    client: HttpClient,
    url: str,
    scope: str,
    diagnostics: list[Diagnostic],
    timeout: float | None,
) -> Any:
    try:
        response = client.get_json(url, timeout=timeout)
    except ConnectionError:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Could not reach {scope}; RBAC export may be incomplete.",
                scope=scope,
            )
        )
        return None
    except ValueError:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Non-JSON response from {scope}.",
                scope=scope,
            )
        )
        return None
    return _decode(response, scope, diagnostics)


def _decode(
    response: HttpResponse, scope: str, diagnostics: list[Diagnostic]
) -> Any:
    status = response.status_code
    if status in (401, 403):
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                message=f"Access denied while reading {scope}.",
                scope=scope,
                hint="Re-run with a token that holds the org/server admin role.",
            )
        )
        return None
    if status == 429:
        diagnostics.append(
            Diagnostic(
                code="rate-limited",
                message=f"Rate limited while reading {scope}.",
                scope=scope,
                severity="info",
            )
        )
        return None
    if status >= 400:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Upstream returned HTTP {status} for {scope}.",
                scope=scope,
            )
        )
        return None
    body = response.body
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Esri returned an error envelope for {scope}.",
                scope=scope,
            )
        )
        return None
    return body


def _portal_locator(target: str, portal_self: Any) -> str:
    safe = safe_url(sanitize_handoff_url(target))
    from urllib.parse import urlsplit

    host = urlsplit(safe).netloc or "unknown.local"
    org_id = ""
    if isinstance(portal_self, dict):
        org_id = str(portal_self.get("id") or "")
    return f"{host}/{org_id}" if org_id else host


def _org_security(portal_self: Mapping[str, Any]) -> OrgSecurity:
    providers: list[IdentityProvider] = ["arcgis"]
    if portal_self.get("samlEnabled") or portal_self.get("canSignInIDP"):
        providers.append("saml")
    if portal_self.get("openIdConnectEnabled") or portal_self.get("oidcEnabled"):
        providers.append("oidc")
    deduped: list[IdentityProvider] = list(dict.fromkeys(providers))
    mfa = portal_self.get("mfaEnabled")
    anon = portal_self.get("access")
    default_role = portal_self.get("defaultRoleForUser") or portal_self.get("defaultRole")
    return OrgSecurity(
        allowed_providers=deduped,
        multi_factor_auth_required=bool(mfa) if mfa is not None else None,
        anonymous_access_allowed=(anon == "public") if anon is not None else None,
        default_role_id=str(default_role) if default_role else None,
    )


def _portal_users(payload: Any) -> list[AccessUser]:
    if not isinstance(payload, dict):
        return []
    users: list[AccessUser] = []
    for raw in payload.get("users", []) or []:
        if not isinstance(raw, dict):
            continue
        username = raw.get("username")
        if not isinstance(username, str):
            continue
        users.append(
            AccessUser(
                username=username,
                role_id=str(raw.get("roleId") or raw.get("role") or "org_user"),
                disabled=bool(raw.get("disabled", False)),
                full_name=_opt_str(raw.get("fullName")),
                group_ids=[str(g) for g in raw.get("groups", []) or [] if g],
                user_type=_opt_str(raw.get("userType")),
                provider=_provider(raw.get("provider")),
            )
        )
    return users


def _portal_roles(
    base: str,
    client: HttpClient,
    payload: Any,
    diagnostics: list[Diagnostic],
    timeout: float | None,
) -> list[AccessRole]:
    roles = _builtin_portal_roles()
    if not isinstance(payload, dict):
        return roles
    for raw in payload.get("roles", []) or []:
        if not isinstance(raw, dict):
            continue
        role_id = raw.get("id")
        if not isinstance(role_id, str):
            continue
        privileges = [str(p) for p in raw.get("privileges", []) or []]
        if not privileges:
            priv_payload = _get(
                client,
                urljoin(base, f"portals/self/roles/{role_id}/privileges"),
                f"portal.roles.{role_id}.privileges",
                diagnostics,
                timeout,
            )
            if isinstance(priv_payload, dict):
                privileges = [
                    str(p) for p in priv_payload.get("privileges", []) or []
                ]
        roles.append(
            AccessRole(
                id=role_id,
                name=str(raw.get("name", role_id)),
                type="custom",
                privileges=privileges,
                description=_opt_str(raw.get("description")),
            )
        )
    return roles


def _builtin_portal_roles() -> list[AccessRole]:
    return [
        AccessRole(
            id="org_admin",
            name="Administrator",
            type="administrator",
            privileges=[
                "portal:admin:manageUsers",
                "portal:admin:manageRoles",
                "portal:admin:manageSecurity",
            ],
        ),
        AccessRole(
            id="org_publisher",
            name="Publisher",
            type="publisher",
            privileges=[
                "portal:user:createItem",
                "portal:publisher:publishFeatures",
            ],
        ),
        AccessRole(
            id="org_user",
            name="User",
            type="user",
            privileges=["portal:user:createItem", "portal:user:viewOrgItems"],
        ),
        AccessRole(
            id="org_viewer",
            name="Viewer",
            type="viewer",
            privileges=["portal:user:viewOrgItems"],
        ),
    ]


def _portal_groups(payload: Any) -> list[AccessGroup]:
    if not isinstance(payload, dict):
        return []
    groups: list[AccessGroup] = []
    raw_groups = payload.get("results") or payload.get("groups") or []
    for raw in raw_groups:
        if not isinstance(raw, dict):
            continue
        group_id = raw.get("id")
        if not isinstance(group_id, str):
            continue
        access = raw.get("access")
        access_level: GroupAccess = access if access in _GROUP_ACCESS else "private"
        groups.append(
            AccessGroup(
                id=group_id,
                title=str(raw.get("title", group_id)),
                access=access_level,
                member_count=int(raw.get("memberCount", 0) or 0),
                owner=_opt_str(raw.get("owner")),
            )
        )
    return groups


def _server_roles(payload: Any) -> list[AccessRole]:
    if not isinstance(payload, dict):
        return []
    roles: list[AccessRole] = []
    for raw in payload.get("roles", []) or []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("rolename") or raw.get("name")
        if not isinstance(name, str):
            continue
        roles.append(
            AccessRole(
                id=name,
                name=name,
                type="custom",
                privileges=[],
                description=_opt_str(raw.get("description")),
            )
        )
    return roles


def _server_users(payload: Any) -> list[AccessUser]:
    if not isinstance(payload, dict):
        return []
    users: list[AccessUser] = []
    for raw in payload.get("users", []) or []:
        if not isinstance(raw, dict):
            continue
        username = raw.get("username")
        if not isinstance(username, str):
            continue
        roles = raw.get("roles") or []
        role_id = str(roles[0]) if roles else "user"
        users.append(
            AccessUser(
                username=username,
                role_id=role_id,
                disabled=bool(raw.get("disabled", False)),
                full_name=_opt_str(raw.get("fullname") or raw.get("fullName")),
                provider="enterprise",
            )
        )
    return users


def _provider(value: Any) -> IdentityProvider:
    return _PROVIDER_ALIASES.get(str(value).lower(), "unknown")


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def model_service_permission(
    service_url: str,
    principal_type: str,
    principal: str,
    access: str,
) -> ServicePermission:
    """Build a redaction-safe :class:`ServicePermission` from raw observations."""

    pt = principal_type if principal_type in ("role", "user", "group", "everyone") else "everyone"
    eff = access if access in ("allow", "deny") else "deny"
    return ServicePermission(
        service_url=sanitize_handoff_url(service_url),
        principal_type=pt,  # type: ignore[arg-type]
        principal=principal,
        access=eff,  # type: ignore[arg-type]
    )


def model_item_sharing(item_id: str, owner: str, access: str) -> ItemSharing:
    level = access if access in ("private", "org", "public", "shared") else "private"
    return ItemSharing(item_id=item_id, owner=owner, access=level)  # type: ignore[arg-type]


__all__ = [
    "model_item_sharing",
    "model_service_permission",
    "scan_portal_rbac",
    "scan_server_rbac",
]
