"""ArcGIS Server access collector.

Reads documented admin endpoints (``/arcgis/admin/security/config``,
``/arcgis/admin/security/users/search``, ``/arcgis/admin/security/roles/search``,
and per-service ``/permissions``). Per-service permission probes are bounded
by the inventory list supplied by the caller so the collector does not
re-enumerate folders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import quote, urljoin
import logging
import re

from honua_esri_assess.diagnostics import redact as _redact_secrets
from honua_esri_assess.entitlements.diagnostics import Diagnostic
from honua_esri_assess.entitlements.http import HttpClient, HttpResponse, safe_url
from honua_esri_assess.server._safe import credential_free_url

from .diagnostics import (
    AccessApiError,
    AccessAuthError,
    AccessConnectionError,
    AccessForbiddenError,
    AccessNotFoundError,
    AccessRateLimitedError,
    AccessSchemaError,
    envelope_code,
    is_safe_principal_name,
)
from .models import (
    PrincipalKind,
    RoleDefinition,
    RoleScope,
    ServerAccess,
    ServicePermission,
    UserPrincipal,
    UserStatus,
)


_LOG = logging.getLogger(__name__)


# Mirror the v0.2 Identifier pattern length cap (was 64, schema allows 128).
# Principal-name checks live in ``access.diagnostics.is_safe_principal_name``
# so they stay in lockstep with the v0.2 ``PrincipalName.not`` schema clause.
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SAFE_FOLDER_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SAFE_SERVICE_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SAFE_TYPE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class ServiceRef:
    """Pointer into an ArcGIS Server service for permission probing."""

    folder: str
    name: str
    type: str


@dataclass(frozen=True)
class ServerAccessResult:
    access: ServerAccess
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)


class ServerAccessCollector:
    """Enumerate ArcGIS Server identity/RBAC and per-service permissions."""

    def __init__(
        self,
        base_url: str,
        client: HttpClient,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._client = client

    def collect(
        self,
        services: Iterable[ServiceRef] = (),
    ) -> ServerAccessResult:
        diagnostics: list[Diagnostic] = []
        security_mode, auth_tier = self._collect_security_config(diagnostics)
        users = self._collect_users(diagnostics)
        roles = self._collect_roles(diagnostics)
        permissions = self._collect_permissions(services, diagnostics)
        access = ServerAccess(
            users=users,
            roles=roles,
            service_permissions=permissions,
            security_mode=security_mode,
            auth_tier=auth_tier,
        )
        return ServerAccessResult(access=access, diagnostics=tuple(diagnostics))

    def _collect_security_config(
        self, diagnostics: list[Diagnostic]
    ) -> tuple[str | None, str | None]:
        payload = self._get(
            "admin/security/config",
            scope="server.access.securityConfig",
            diagnostics=diagnostics,
            soft_auth_failure=True,
        )
        if not isinstance(payload, dict):
            return None, None
        security_mode = payload.get("securityMode") or payload.get("authenticationMode")
        auth_tier = payload.get("authenticationTier") or payload.get("authTier")
        return (
            str(security_mode) if isinstance(security_mode, str) and security_mode else None,
            str(auth_tier) if isinstance(auth_tier, str) and auth_tier else None,
        )

    def _collect_users(
        self, diagnostics: list[Diagnostic]
    ) -> tuple[UserPrincipal, ...]:
        payloads = self._paginate(
            "admin/security/users/search",
            scope="server.access.users",
            diagnostics=diagnostics,
            page_key="users",
        )
        users: list[UserPrincipal] = []
        seen: set[str] = set()
        for entry in payloads:
            if not isinstance(entry, dict):
                continue
            username = entry.get("username") or entry.get("name")
            if not is_safe_principal_name(username):
                if isinstance(username, str) and username:
                    diagnostics.append(
                        Diagnostic(
                            code="redacted-field",
                            severity="info",
                            message=(
                                "Server user record omitted: username is email-shaped "
                                "or fails the PrincipalName pattern."
                            ),
                            scope="server.access.users",
                        )
                    )
                continue
            if username in seen:
                continue
            seen.add(username)
            full_name = entry.get("fullname") or entry.get("fullName")
            if isinstance(full_name, str) and "@" in full_name:
                full_name = None
            elif isinstance(full_name, str) and full_name:
                full_name = _sanitize_text(full_name)
            else:
                full_name = None
            role_id = entry.get("role") or entry.get("roleId")
            if not isinstance(role_id, str) or not _ID_RE.fullmatch(role_id):
                role_id = None
            status: UserStatus = "active" if entry.get("disabled") is False else (
                "disabled" if entry.get("disabled") is True else "unknown"
            )
            users.append(
                UserPrincipal(
                    username=username,
                    full_name=full_name,
                    role_id=role_id,
                    user_type=None,
                    status=status,
                )
            )
        return tuple(users)

    def _collect_roles(
        self, diagnostics: list[Diagnostic]
    ) -> tuple[RoleDefinition, ...]:
        payloads = self._paginate(
            "admin/security/roles/search",
            scope="server.access.roles",
            diagnostics=diagnostics,
            page_key="roles",
        )
        roles: list[RoleDefinition] = []
        seen: set[str] = set()
        for entry in payloads:
            if not isinstance(entry, dict):
                continue
            role_id = entry.get("rolename") or entry.get("name") or entry.get("id")
            if not isinstance(role_id, str) or not _ID_RE.fullmatch(role_id):
                continue
            if role_id in seen:
                continue
            seen.add(role_id)
            description = entry.get("description")
            if isinstance(description, str) and description:
                description = _sanitize_text(description)
            else:
                description = None
            privileges = tuple(
                str(p)
                for p in entry.get("privileges", [])
                if isinstance(p, str)
            )
            scope = _server_role_scope(role_id, privileges)
            roles.append(
                RoleDefinition(
                    id=role_id,
                    name=role_id,
                    scope=scope,
                    privileges=privileges,
                    description=description,
                )
            )
        return tuple(roles)

    def _collect_permissions(
        self,
        services: Iterable[ServiceRef],
        diagnostics: list[Diagnostic],
    ) -> tuple[ServicePermission, ...]:
        permissions: list[ServicePermission] = []
        for ref in services:
            if not _ref_is_safe(ref):
                continue
            scope = _service_scope(ref)
            payload = self._get(
                _permissions_path(ref),
                scope=scope,
                diagnostics=diagnostics,
                soft_auth_failure=True,
            )
            if not isinstance(payload, dict):
                continue
            permission_records = payload.get("permissions")
            if not isinstance(permission_records, list):
                continue
            service_url = _service_url(self._base_url, ref)
            for record in permission_records:
                permission = _parse_permission_record(
                    record,
                    service_url,
                    diagnostics=diagnostics,
                    scope=scope,
                )
                if permission is None:
                    continue
                permissions.append(permission)
        return tuple(permissions)

    def _paginate(
        self,
        path: str,
        *,
        scope: str,
        diagnostics: list[Diagnostic],
        page_key: str,
    ) -> list[Any]:
        out: list[Any] = []
        start = 0
        for _ in range(100):
            payload = self._get(
                path,
                scope=scope,
                diagnostics=diagnostics,
                soft_auth_failure=True,
                params={"size": "100", "start": str(start)},
            )
            if not isinstance(payload, dict):
                break
            page = payload.get(page_key)
            if isinstance(page, list):
                out.extend(page)
            has_more = payload.get("hasMore") or payload.get("hasNext")
            if not has_more:
                break
            next_start = payload.get("nextStart")
            if isinstance(next_start, int) and next_start > start:
                start = next_start
            else:
                start += 100
        return out

    def _get(
        self,
        path: str,
        *,
        scope: str,
        diagnostics: list[Diagnostic],
        soft_auth_failure: bool,
        params: dict[str, str] | None = None,
    ) -> Any:
        url = urljoin(self._base_url, path)
        try:
            response = self._client.get_json(url, params=params)
        except ConnectionError as exc:
            raise AccessConnectionError(
                f"could not reach ArcGIS Server endpoint {safe_url(url)}: {exc}"
            ) from exc
        except ValueError as exc:
            raise AccessSchemaError(
                f"unparseable response from ArcGIS Server endpoint {safe_url(url)}: "
                f"{exc}"
            ) from exc
        return _interpret_response(
            response,
            url=url,
            scope=scope,
            diagnostics=diagnostics,
            soft_auth_failure=soft_auth_failure,
        )


def _interpret_response(
    response: HttpResponse,
    *,
    url: str,
    scope: str,
    diagnostics: list[Diagnostic],
    soft_auth_failure: bool,
) -> Any:
    status = response.status_code
    body = response.body
    if status == 200 and isinstance(body, dict):
        error_obj = body.get("error")
        if isinstance(error_obj, dict):
            code = envelope_code(error_obj)
            if code in {401, 498, 499} and soft_auth_failure:
                diagnostics.append(
                    Diagnostic(
                        code="missing-permission",
                        severity="warn",
                        message=(
                            "ArcGIS Server denied admin access; continuing "
                            "without this endpoint."
                        ),
                        scope=scope,
                    )
                )
                return None
            if code == 403 and soft_auth_failure:
                diagnostics.append(
                    Diagnostic(
                        code="missing-permission",
                        severity="warn",
                        message="ArcGIS Server returned forbidden; skipping endpoint.",
                        scope=scope,
                    )
                )
                return None
            if code == 429:
                raise AccessRateLimitedError(
                    f"ArcGIS Server endpoint {safe_url(url)} rate-limited the scan."
                )
            if code in {401, 498, 499}:
                raise AccessAuthError(
                    f"ArcGIS Server endpoint {safe_url(url)} requires authentication."
                )
            if code == 403:
                raise AccessForbiddenError(
                    f"ArcGIS Server endpoint {safe_url(url)} denied access."
                )
            if code == 404:
                raise AccessNotFoundError(
                    f"ArcGIS Server endpoint {safe_url(url)} was not found."
                )
            raise AccessApiError(
                f"ArcGIS Server endpoint {safe_url(url)} returned error envelope "
                f"code={code}."
            )
        return body
    if status in {401, 403} and soft_auth_failure:
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                severity="warn",
                message=(
                    "ArcGIS Server endpoint requires admin scope; access "
                    "enumeration is skipping it."
                ),
                scope=scope,
            )
        )
        return None
    if status == 404 and soft_auth_failure:
        diagnostics.append(
            Diagnostic(
                code="unresolved-reference",
                severity="warn",
                message="ArcGIS Server endpoint not found; skipping.",
                scope=scope,
            )
        )
        return None
    if status == 429:
        raise AccessRateLimitedError(
            f"ArcGIS Server endpoint {safe_url(url)} rate-limited the scan."
        )
    if status == 401:
        raise AccessAuthError(
            f"ArcGIS Server endpoint {safe_url(url)} requires authentication."
        )
    if status == 403:
        raise AccessForbiddenError(
            f"ArcGIS Server endpoint {safe_url(url)} denied access."
        )
    if status == 404:
        raise AccessNotFoundError(
            f"ArcGIS Server endpoint {safe_url(url)} was not found."
        )
    if 200 <= status < 300:
        return body
    raise AccessApiError(
        f"ArcGIS Server endpoint {safe_url(url)} returned HTTP {status}."
    )


def _sanitize_text(value: str) -> str:
    """Scrub credential-shaped fragments from a free-text server-access field.

    Mirrors ``honua_esri_assess.access.portal._sanitize_text`` — server-side
    payloads (role descriptions, user full names) can still embed
    ``token=...`` / ``Bearer ...`` substrings inside an otherwise-valid
    field, so we route them through the shared redactor before they reach
    the artifact.
    """

    return _redact_secrets(value)


def _ref_is_safe(ref: ServiceRef) -> bool:
    if ref.folder and not _SAFE_FOLDER_RE.fullmatch(ref.folder):
        return False
    if not _SAFE_SERVICE_RE.fullmatch(ref.name):
        return False
    if not _SAFE_TYPE_RE.fullmatch(ref.type):
        return False
    return True


def _permissions_path(ref: ServiceRef) -> str:
    parts = ["admin", "services"]
    if ref.folder:
        parts.append(quote(ref.folder, safe=""))
    parts.append(f"{quote(ref.name, safe='')}.{quote(ref.type, safe='')}")
    parts.append("permissions")
    return "/".join(parts)


def _service_url(base_url: str, ref: ServiceRef) -> str:
    parts = ["rest", "services"]
    if ref.folder:
        parts.append(quote(ref.folder, safe=""))
    parts.append(f"{quote(ref.name, safe='')}/{quote(ref.type, safe='')}")
    raw = urljoin(base_url, "/".join(parts))
    return credential_free_url(raw)


def _service_scope(ref: ServiceRef) -> str:
    base = (
        f"server.access.services/{ref.folder}/{ref.name}.{ref.type}"
        if ref.folder
        else f"server.access.services/{ref.name}.{ref.type}"
    )
    return base


def _server_role_scope(role_id: str, privileges: tuple[str, ...]) -> RoleScope:
    lowered = role_id.lower()
    if "admin" in lowered:
        return "admin"
    if "publish" in lowered:
        return "publisher"
    if "user" in lowered or "viewer" in lowered:
        return "user"
    text = " ".join(p.lower() for p in privileges)
    if "admin" in text:
        return "admin"
    if "publish" in text or "edit" in text:
        return "publisher"
    if "use" in text or "view" in text:
        return "user"
    return "custom"


def _parse_permission_record(
    record: Any,
    service_url: str,
    *,
    diagnostics: list[Diagnostic],
    scope: str,
) -> ServicePermission | None:
    if not isinstance(record, dict):
        return None
    principal = record.get("principal")
    if not is_safe_principal_name(principal):
        if isinstance(principal, str) and principal:
            diagnostics.append(
                Diagnostic(
                    code="redacted-field",
                    severity="info",
                    message=(
                        "Service permission record omitted: principal is email-shaped "
                        "or fails the PrincipalName pattern."
                    ),
                    scope=scope,
                )
            )
        return None
    principal_kind = _principal_kind_from_payload(record)
    operations = record.get("operations") or record.get("capabilities") or []
    if not isinstance(operations, list):
        return None
    caps = tuple(sorted({str(c) for c in operations if isinstance(c, str)}))
    if not caps:
        return None
    return ServicePermission(
        service_url=service_url,
        principal=principal,
        principal_kind=principal_kind,
        capabilities=caps,
    )


def _principal_kind_from_payload(record: dict[str, Any]) -> PrincipalKind:
    kind = record.get("principalKind") or record.get("type")
    if isinstance(kind, str):
        lowered = kind.lower()
        if lowered in {"role", "group", "user"}:
            return lowered  # type: ignore[return-value]
    if record.get("isGroup") is True:
        return "group"
    if record.get("isRole") is True:
        return "role"
    return "user"


__all__ = [
    "ServerAccessCollector",
    "ServerAccessResult",
    "ServiceRef",
]
