"""Portal access collector for ArcGIS Online / Enterprise Portal.

Only documented Sharing API and community endpoints are touched and only
via HTTP GET. When the caller's token does not have the scope required
to read an admin endpoint, the collector emits a ``missing-permission``
diagnostic at ``warn`` severity and continues with whatever the token
*can* read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urljoin
import logging
import re

from honua_esri_assess.diagnostics import redact as _redact_secrets
from honua_esri_assess.entitlements.diagnostics import Diagnostic
from honua_esri_assess.entitlements.http import HttpClient, HttpResponse, safe_url

from .diagnostics import (
    AccessApiError,
    AccessAuthError,
    AccessConnectionError,
    AccessForbiddenError,
    AccessNotFoundError,
    AccessRateLimitedError,
    AccessSchemaError,
)
from .models import (
    GroupDefinition,
    ItemSharing,
    OrgSecurityPolicy,
    PortalAccess,
    RoleDefinition,
    RoleScope,
    UserPrincipal,
    UserStatus,
)


_LOG = logging.getLogger(__name__)


_DEFAULT_GROUP_CAP = 200
_PAGE_NUM = 100
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class PortalAccessResult:
    access: PortalAccess
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)


class PortalAccessCollector:
    """Enumerate Portal access through documented Sharing / community endpoints."""

    def __init__(
        self,
        base_url: str,
        client: HttpClient,
        *,
        group_cap: int = _DEFAULT_GROUP_CAP,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._client = client
        self._group_cap = max(0, int(group_cap))

    def collect(
        self, *, item_sharing: Iterable[ItemSharing] = (),
    ) -> PortalAccessResult:
        diagnostics: list[Diagnostic] = []

        self_payload = self._get(
            "sharing/rest/portals/self",
            scope="portal.access",
            diagnostics=diagnostics,
            soft_auth_failure=True,
        )
        org_id = _safe_get(self_payload, "id")
        if not isinstance(org_id, str) or not _ID_RE.fullmatch(org_id):
            org_id = None
        if org_id is None:
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message=(
                        "Portal self endpoint did not return a usable org id; "
                        "access enumeration is skipping admin paths that need it."
                    ),
                    scope="portal.access",
                )
            )
            return PortalAccessResult(access=PortalAccess(), diagnostics=tuple(diagnostics))

        roles = self._collect_roles(org_id, diagnostics)
        security = self._collect_security_policy(org_id, diagnostics)
        groups = self._collect_groups(org_id, diagnostics)
        users = self._collect_users(org_id, diagnostics)
        sharing = _normalize_item_sharing(item_sharing, diagnostics)

        access = PortalAccess(
            users=users,
            roles=roles,
            groups=groups,
            item_sharing=sharing,
            security_policy=security,
        )
        return PortalAccessResult(access=access, diagnostics=tuple(diagnostics))

    def _collect_roles(
        self, org_id: str, diagnostics: list[Diagnostic]
    ) -> tuple[RoleDefinition, ...]:
        payloads = self._paginate(
            f"sharing/rest/portals/{org_id}/roles",
            scope="portal.access.roles",
            diagnostics=diagnostics,
            page_key="roles",
        )
        roles: list[RoleDefinition] = []
        seen: set[str] = set()
        for entry in payloads:
            if not isinstance(entry, dict):
                continue
            role_id = entry.get("id") or entry.get("roleId")
            name = entry.get("name") or entry.get("roleName")
            if not _is_safe_id(role_id) or not isinstance(name, str) or not name:
                continue
            role_id = str(role_id)
            if role_id in seen:
                continue
            seen.add(role_id)
            privileges = tuple(
                str(p) for p in entry.get("privileges", []) if isinstance(p, str)
            )
            description = entry.get("description")
            if isinstance(description, str) and description:
                description = _sanitize_text(description)
            else:
                description = None
            scope = _role_scope_from_payload(role_id, entry)
            roles.append(
                RoleDefinition(
                    id=role_id,
                    name=_sanitize_text(name),
                    scope=scope,
                    privileges=privileges,
                    description=description,
                )
            )
        return tuple(roles)

    def _collect_security_policy(
        self, org_id: str, diagnostics: list[Diagnostic]
    ) -> OrgSecurityPolicy | None:
        payload = self._get(
            f"sharing/rest/portals/{org_id}/securityPolicy",
            scope="portal.access.securityPolicy",
            diagnostics=diagnostics,
            soft_auth_failure=True,
        )
        if not isinstance(payload, dict):
            return None
        sign_in = payload.get("signinOptions") or payload.get("signInMethods") or []
        if not isinstance(sign_in, list):
            sign_in = []
        return OrgSecurityPolicy(
            mfa_required=_as_optional_bool(payload.get("mfaRequired")),
            sign_in_methods=tuple(sorted({str(m) for m in sign_in if m})),
            password_min_length=_as_optional_int(payload.get("minLength")),
            password_complexity=_as_optional_bool(payload.get("hasMixedCase"))
            or _as_optional_bool(payload.get("hasDigit")),
            allowed_origins=tuple(
                sorted(
                    {
                        _sanitize_text(str(o))
                        for o in (payload.get("allowedOrigins") or [])
                        if isinstance(o, str)
                    }
                )
            ),
            session_expiry_minutes=_as_optional_int(payload.get("sessionExpiry")),
        )

    def _collect_groups(
        self, org_id: str, diagnostics: list[Diagnostic]
    ) -> tuple[GroupDefinition, ...]:
        payloads = self._paginate(
            "sharing/rest/community/groups",
            scope="portal.access.groups",
            diagnostics=diagnostics,
            page_key="results",
            base_params={"q": f"orgid:{org_id}"},
        )
        groups: list[GroupDefinition] = []
        seen: set[str] = set()
        for entry in payloads:
            if not isinstance(entry, dict):
                continue
            group_id = entry.get("id")
            title = entry.get("title")
            owner = entry.get("owner")
            access = entry.get("access")
            if not _is_safe_id(group_id):
                continue
            if not isinstance(title, str) or not title:
                continue
            if not isinstance(owner, str) or not _USERNAME_RE.fullmatch(owner):
                continue
            if access not in {"private", "org", "public", "shared"}:
                continue
            group_id = str(group_id)
            if group_id in seen:
                continue
            seen.add(group_id)
            capabilities = tuple(
                str(c) for c in entry.get("capabilities", []) if isinstance(c, str)
            )
            member_count = self._maybe_member_count(group_id, diagnostics)
            shared_count = _as_optional_int(entry.get("itemsAvailable"))
            groups.append(
                GroupDefinition(
                    id=group_id,
                    title=_sanitize_text(title),
                    access=access,
                    owner=owner,
                    capabilities=capabilities,
                    is_invitation_only=bool(entry.get("isInvitationOnly")),
                    is_view_only=bool(entry.get("isViewOnly")),
                    member_count=member_count,
                    shared_item_count=shared_count,
                )
            )
        return tuple(groups)

    def _maybe_member_count(
        self, group_id: str, diagnostics: list[Diagnostic]
    ) -> int | None:
        if self._group_cap == 0:
            return None
        scope = f"portal.access.groups.{group_id}.users"
        payload = self._get(
            f"sharing/rest/community/groups/{group_id}/users",
            scope=scope,
            diagnostics=diagnostics,
            soft_auth_failure=True,
            params={"num": str(self._group_cap)},
        )
        if not isinstance(payload, dict):
            return None
        total = payload.get("total")
        if isinstance(total, int) and total >= 0:
            if total > self._group_cap:
                diagnostics.append(
                    Diagnostic(
                        code="partial-coverage",
                        severity="info",
                        message=(
                            "Group member enumeration capped; full membership "
                            "exceeds the configured per-group cap."
                        ),
                        scope=scope,
                        hint=f"Re-run with --access-group-cap >= {total}.",
                    )
                )
            return total
        members = payload.get("users")
        if isinstance(members, list):
            return len(members)
        return None

    def _collect_users(
        self, org_id: str, diagnostics: list[Diagnostic]
    ) -> tuple[UserPrincipal, ...]:
        payloads = self._paginate(
            "sharing/rest/community/users",
            scope="portal.access.users",
            diagnostics=diagnostics,
            page_key="results",
            base_params={"q": f"orgid:{org_id}"},
        )
        users: list[UserPrincipal] = []
        seen: set[str] = set()
        for entry in payloads:
            if not isinstance(entry, dict):
                continue
            username = entry.get("username")
            if not isinstance(username, str) or not _USERNAME_RE.fullmatch(username):
                continue
            if username in seen:
                continue
            seen.add(username)
            full_name = entry.get("fullName") or entry.get("displayName")
            if isinstance(full_name, str) and (
                _EMAIL_RE.fullmatch(full_name) or "@" in full_name
            ):
                full_name = None
            elif isinstance(full_name, str) and full_name:
                full_name = _sanitize_text(full_name)
            else:
                full_name = None
            role_id = entry.get("roleId") or entry.get("role")
            if not _is_safe_id(role_id):
                role_id = None
            user_type = entry.get("userType") or entry.get("userLicenseTypeId")
            user_type = user_type if isinstance(user_type, str) and user_type else None
            status = _user_status(entry.get("disabled"), entry.get("status"))
            last_login = _quantize_last_login(entry.get("lastLogin"))
            raw_group_ids = entry.get("groups") or []
            if isinstance(raw_group_ids, list):
                group_ids = tuple(
                    str(g) for g in raw_group_ids if _is_safe_id(g)
                )
            else:
                group_ids = ()
            users.append(
                UserPrincipal(
                    username=username,
                    full_name=full_name,
                    role_id=str(role_id) if role_id else None,
                    user_type=user_type,
                    status=status,
                    last_login=last_login,
                    group_ids=group_ids,
                )
            )
        return tuple(users)

    def _paginate(
        self,
        path: str,
        *,
        scope: str,
        diagnostics: list[Diagnostic],
        page_key: str,
        base_params: dict[str, str] | None = None,
    ) -> list[Any]:
        start = 1
        out: list[Any] = []
        # Bound the loop to keep a malformed Esri response from running away.
        for _ in range(100):
            params: dict[str, str] = {"num": str(_PAGE_NUM), "start": str(start)}
            if base_params:
                params.update(base_params)
            payload = self._get(
                path,
                scope=scope,
                diagnostics=diagnostics,
                soft_auth_failure=True,
                params=params,
            )
            if not isinstance(payload, dict):
                break
            page = payload.get(page_key)
            if isinstance(page, list):
                out.extend(page)
            next_start = payload.get("nextStart")
            if not isinstance(next_start, int) or next_start <= 0:
                break
            if next_start == start:
                break
            start = next_start
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
                f"could not reach Portal endpoint {safe_url(url)}: {exc}"
            ) from exc
        except ValueError as exc:
            raise AccessSchemaError(
                f"unparseable response from Portal endpoint {safe_url(url)}: {exc}"
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
            code = int(error_obj.get("code") or 0)
            if code in {401, 498, 499} and soft_auth_failure:
                diagnostics.append(
                    Diagnostic(
                        code="missing-permission",
                        severity="warn",
                        message=(
                            "Esri endpoint denied access; the supplied token "
                            "does not appear to have the required scope."
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
                        message="Esri endpoint returned forbidden; continuing without it.",
                        scope=scope,
                    )
                )
                return None
            if code == 429:
                raise AccessRateLimitedError(
                    f"Esri endpoint {safe_url(url)} rate-limited the scan."
                )
            if code in {401, 498, 499}:
                raise AccessAuthError(
                    f"Esri endpoint {safe_url(url)} requires authentication."
                )
            if code == 403:
                raise AccessForbiddenError(
                    f"Esri endpoint {safe_url(url)} denied access."
                )
            if code == 404:
                raise AccessNotFoundError(
                    f"Esri endpoint {safe_url(url)} was not found."
                )
            raise AccessApiError(
                f"Esri endpoint {safe_url(url)} returned error envelope code={code}."
            )
        return body
    if status in {401, 403} and soft_auth_failure:
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                severity="warn",
                message=(
                    "Esri endpoint requires admin or higher scope; access "
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
                message="Esri endpoint not found; skipping.",
                scope=scope,
            )
        )
        return None
    if status == 429:
        raise AccessRateLimitedError(
            f"Esri endpoint {safe_url(url)} rate-limited the scan."
        )
    if status == 401:
        raise AccessAuthError(
            f"Esri endpoint {safe_url(url)} requires authentication."
        )
    if status == 403:
        raise AccessForbiddenError(
            f"Esri endpoint {safe_url(url)} denied access."
        )
    if status == 404:
        raise AccessNotFoundError(
            f"Esri endpoint {safe_url(url)} was not found."
        )
    if 200 <= status < 300:
        return body
    raise AccessApiError(
        f"Esri endpoint {safe_url(url)} returned HTTP {status}."
    )


def _role_scope_from_payload(role_id: str, entry: dict[str, Any]) -> RoleScope:
    if role_id in {"org_admin", "iaaadmin"}:
        return "admin"
    if role_id in {"org_publisher"}:
        return "publisher"
    if role_id in {"org_user", "org_viewer", "viewer"}:
        return "user"
    raw_scope = entry.get("scope") or entry.get("kind")
    if isinstance(raw_scope, str):
        lowered = raw_scope.lower()
        if lowered in {"admin", "publisher", "user"}:
            return lowered  # type: ignore[return-value]
    return "custom"


def _normalize_item_sharing(
    sharing: Iterable[ItemSharing],
    diagnostics: list[Diagnostic],
) -> tuple[ItemSharing, ...]:
    out: list[ItemSharing] = []
    for entry in sharing:
        if not _ID_RE.fullmatch(entry.item_id):
            diagnostics.append(
                Diagnostic(
                    code="redacted-field",
                    severity="info",
                    message="Item sharing record omitted: item id is not prospect-safe.",
                    scope="portal.access.itemSharing",
                )
            )
            continue
        if not _USERNAME_RE.fullmatch(entry.owner):
            diagnostics.append(
                Diagnostic(
                    code="redacted-field",
                    severity="info",
                    message="Item sharing record omitted: owner username is not prospect-safe.",
                    scope="portal.access.itemSharing",
                )
            )
            continue
        out.append(entry)
    return tuple(out)


def _user_status(disabled: Any, raw_status: Any) -> UserStatus:
    if disabled is True:
        return "disabled"
    if disabled is False:
        return "active"
    if isinstance(raw_status, str):
        lowered = raw_status.lower()
        if lowered in {"active", "enabled"}:
            return "active"
        if lowered in {"disabled", "deactivated", "inactive"}:
            return "disabled"
    return "unknown"


def _quantize_last_login(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    # Quantize to UTC date (00:00:00Z) so the artifact does not carry
    # per-minute behavioral telemetry.
    from datetime import datetime, timezone

    seconds = int(value / 1000) if value > 10_000_000_000 else int(value)
    try:
        ts = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return ts.strftime("%Y-%m-%dT00:00:00Z")


def _sanitize_text(value: str) -> str:
    """Scrub credential-shaped fragments from a free-text access field.

    Group titles, user full names, role display names, and security-policy
    origin URLs are emitted into the artifact verbatim from Esri payloads.
    A hostile or careless Esri admin can plant a ``token=...`` or
    ``Bearer ...`` substring inside an otherwise-valid free-text field;
    routing those through the shared :func:`redact` keeps the
    no-credential-artifact constraint intact even when the field passes
    every other shape check.
    """

    return _redact_secrets(value)


def _is_safe_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def _as_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _as_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _safe_get(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        return payload.get(key)
    return None


__all__ = [
    "PortalAccessCollector",
    "PortalAccessResult",
]
