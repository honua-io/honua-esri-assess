"""Portal entitlement collector for ArcGIS Online / Enterprise Portal.

Only documented Sharing API endpoints are touched and only via HTTP GET.
When the caller's token does not have the scope required to read an admin
endpoint, the collector emits a ``missing-permission`` diagnostic at
``warning`` severity and continues with whatever public information the
endpoint exposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urljoin
import logging

from .diagnostics import (
    Diagnostic,
    EntitlementsApiError,
    EntitlementsAuthError,
    EntitlementsConnectionError,
    EntitlementsForbiddenError,
    EntitlementsNotFoundError,
    EntitlementsRateLimitedError,
    EntitlementsSchemaError,
)
from .extensions import resolve_extension
from .http import HttpClient, HttpResponse, safe_url
from .models import (
    ExtensionEntitlement,
    PortalLicensing,
    UserTypeCount,
)


_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortalEntitlementsResult:
    licensing: PortalLicensing
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)


class PortalEntitlementsCollector:
    """Enumerate Portal licensing through documented Sharing endpoints."""

    def __init__(
        self,
        base_url: str,
        client: HttpClient,
        *,
        anonymous: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._client = client
        self._anonymous = anonymous

    def collect(self) -> PortalEntitlementsResult:
        diagnostics: list[Diagnostic] = []
        self_payload = self._get(
            "sharing/rest/portals/self",
            scope="portal.self",
            diagnostics=diagnostics,
            soft_auth_failure=False,
        )
        tier, subscription_type, allowed_add_ons, extensions, premium_credits = (
            self._read_self_payload(self_payload, diagnostics)
        )

        user_types: list[UserTypeCount] = []
        org_id = _safe_get(self_payload, "id") if isinstance(self_payload, dict) else None
        if self._anonymous:
            diagnostics.append(
                Diagnostic(
                    code="missing-permission",
                    severity="warn",
                    message=(
                        "Anonymous Portal scan: skipping subscription and user-license "
                        "endpoints that require a token."
                    ),
                    scope="portal.subscriptionInfo",
                )
            )
        else:
            sub_payload = self._get(
                "sharing/rest/portals/self/subscriptionInfo",
                scope="portal.subscriptionInfo",
                diagnostics=diagnostics,
                soft_auth_failure=True,
            )
            if isinstance(sub_payload, dict):
                tier = _as_non_empty_str(sub_payload.get("type")) or tier
                subscription_type = (
                    _as_non_empty_str(sub_payload.get("subscriptionType"))
                    or subscription_type
                )
                add_ons_field = sub_payload.get("allowedAddOns")
                if isinstance(add_ons_field, list):
                    allowed_add_ons = sorted({str(x) for x in add_ons_field if x})
                extensions = _merge_extensions(
                    extensions,
                    _extension_entitlements_from_subscription(sub_payload, diagnostics),
                )
                user_types.extend(
                    _user_types_from_subscription(sub_payload.get("userLicenseTypes"))
                )

            license_types_payload = self._get(
                "sharing/rest/portals/self/userLicenseTypes",
                scope="portal.userLicenseTypes",
                diagnostics=diagnostics,
                soft_auth_failure=True,
            )
            extras = _user_types_from_license_types(license_types_payload)
            user_types = _merge_user_types(user_types, extras)

            if org_id:
                users_payload = self._get(
                    f"sharing/rest/portals/{org_id}/users",
                    scope="portal.users",
                    diagnostics=diagnostics,
                    soft_auth_failure=True,
                    params={"num": "1", "sortField": "created", "sortOrder": "desc"},
                )
                if isinstance(users_payload, dict):
                    user_types = _augment_user_total(user_types, users_payload)

        licensing = PortalLicensing(
            tier=tier,
            subscription_type=subscription_type,
            user_types=user_types,
            premium_credits_enabled=premium_credits,
            allowed_add_ons=allowed_add_ons,
            extensions_observed=extensions,
        )
        return PortalEntitlementsResult(licensing=licensing, diagnostics=tuple(diagnostics))

    def _read_self_payload(
        self,
        payload: Any,
        diagnostics: list[Diagnostic],
    ) -> tuple[
        str | None,
        str | None,
        list[str],
        list[ExtensionEntitlement],
        bool | None,
    ]:
        if not isinstance(payload, dict):
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message="Portal self endpoint returned no usable JSON payload.",
                    scope="portal.self",
                )
            )
            return None, None, [], [], None

        portal_mode = payload.get("portalMode")
        tier = "enterprise" if portal_mode == "singletenant" else "online"
        if payload.get("isPortal") is True:
            tier = "enterprise"

        subscription_info = payload.get("subscriptionInfo")
        subscription_type: str | None = None
        allowed_add_ons: list[str] = []
        extensions: list[ExtensionEntitlement] = []
        premium_credits: bool | None = None

        if isinstance(subscription_info, dict):
            tier = _as_non_empty_str(subscription_info.get("type")) or tier
            subscription_type = _as_non_empty_str(subscription_info.get("subscriptionType"))
            add_ons = subscription_info.get("allowedAddOns")
            if isinstance(add_ons, list):
                allowed_add_ons = sorted({str(x) for x in add_ons if x})
            credits_balance = subscription_info.get("availableCredits")
            if credits_balance is None:
                credits_balance = payload.get("availableCredits")
            if isinstance(credits_balance, (int, float)):
                premium_credits = credits_balance > 0
            elif isinstance(subscription_info.get("premium"), bool):
                premium_credits = bool(subscription_info["premium"])

            extensions.extend(
                _extension_entitlements_from_subscription(subscription_info, diagnostics)
            )
        return tier, subscription_type, allowed_add_ons, extensions, premium_credits

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
            raise EntitlementsConnectionError(
                f"could not reach Portal endpoint {safe_url(url)}: {exc}"
            ) from exc
        except ValueError as exc:
            raise EntitlementsSchemaError(
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
        error_obj = body.get("error") if isinstance(body, dict) else None
        if isinstance(error_obj, dict):
            code = int(error_obj.get("code") or 0)
            if code in {401, 498, 499} and soft_auth_failure:
                diagnostics.append(
                    Diagnostic(
                        code="missing-permission",
                        severity="warn",
                        message=(
                            "Esri endpoint denied access; the supplied token does not "
                            "appear to have the required scope."
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
                raise EntitlementsRateLimitedError(
                    f"Esri endpoint {safe_url(url)} rate-limited the scan."
                )
            if code in {401, 498, 499}:
                raise EntitlementsAuthError(
                    f"Esri endpoint {safe_url(url)} requires authentication."
                )
            if code == 403:
                raise EntitlementsForbiddenError(
                    f"Esri endpoint {safe_url(url)} denied access."
                )
            if code == 404:
                raise EntitlementsNotFoundError(
                    f"Esri endpoint {safe_url(url)} was not found."
                )
            raise EntitlementsApiError(
                f"Esri endpoint {safe_url(url)} returned error envelope code={code}."
            )
        return body
    if status in {401, 403} and soft_auth_failure:
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                severity="warn",
                message=(
                    "Esri endpoint requires admin or higher scope; the scan is continuing "
                    "with publicly available data only."
                ),
                scope=scope,
            )
        )
        return None
    if status == 429:
        raise EntitlementsRateLimitedError(
            f"Esri endpoint {safe_url(url)} rate-limited the scan."
        )
    if status == 401:
        raise EntitlementsAuthError(
            f"Esri endpoint {safe_url(url)} requires authentication."
        )
    if status == 403:
        raise EntitlementsForbiddenError(
            f"Esri endpoint {safe_url(url)} denied access."
        )
    if status == 404:
        raise EntitlementsNotFoundError(
            f"Esri endpoint {safe_url(url)} was not found."
        )
    if 200 <= status < 300:
        return body
    raise EntitlementsApiError(
        f"Esri endpoint {safe_url(url)} returned HTTP {status}."
    )


def _user_types_from_subscription(payload: Any) -> Iterable[UserTypeCount]:
    if not isinstance(payload, list):
        return []
    out: list[UserTypeCount] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        name = entry.get("id") or entry.get("name")
        if not name:
            continue
        total = entry.get("numberOfSeats")
        assigned = entry.get("assignedSeats")
        out.append(
            UserTypeCount(
                name=str(name),
                total=int(total) if isinstance(total, (int, float)) else None,
                assigned=int(assigned) if isinstance(assigned, (int, float)) else None,
            )
        )
    return out


def _user_types_from_license_types(payload: Any) -> Iterable[UserTypeCount]:
    if not isinstance(payload, dict):
        return []
    types = payload.get("userLicenseTypes")
    if not isinstance(types, list):
        return []
    out: list[UserTypeCount] = []
    for entry in types:
        if not isinstance(entry, dict):
            continue
        name = entry.get("id") or entry.get("name")
        if not name:
            continue
        total = entry.get("maxUsers") or entry.get("numberOfSeats")
        out.append(
            UserTypeCount(
                name=str(name),
                total=int(total) if isinstance(total, (int, float)) else None,
                assigned=None,
            )
        )
    return out


def _merge_user_types(
    base: list[UserTypeCount], extras: Iterable[UserTypeCount]
) -> list[UserTypeCount]:
    by_name: dict[str, UserTypeCount] = {ut.name: ut for ut in base}
    for extra in extras:
        existing = by_name.get(extra.name)
        if existing is None:
            by_name[extra.name] = extra
            continue
        by_name[extra.name] = UserTypeCount(
            name=existing.name,
            total=existing.total if existing.total is not None else extra.total,
            assigned=existing.assigned
            if existing.assigned is not None
            else extra.assigned,
        )
    return sorted(by_name.values(), key=lambda ut: ut.name)


def _augment_user_total(
    base: list[UserTypeCount], users_payload: dict[str, Any]
) -> list[UserTypeCount]:
    total = users_payload.get("total")
    if not isinstance(total, int) or total < 0:
        return base
    # Esri's /users endpoint does not break down by license type; if the
    # caller learned nothing else, expose the org-wide total as the
    # ``all`` bucket so downstream consumers still see a count.
    if base:
        return base
    return [UserTypeCount(name="all", total=total, assigned=None)]


def _as_non_empty_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _extension_entitlements_from_subscription(
    subscription_info: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> list[ExtensionEntitlement]:
    extensions: list[ExtensionEntitlement] = []
    seen: set[str] = set()
    for raw_ext in _iter_subscription_extensions(subscription_info):
        resolved = resolve_extension(raw_ext)
        if resolved.code in seen:
            continue
        seen.add(resolved.code)
        extensions.append(
            ExtensionEntitlement(
                code=resolved.code,
                name=resolved.name,
                status="licensed",
                source="portal-subscription",
            )
        )
        if not resolved.known:
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message=(
                        "Portal subscription reported an extension code that is "
                        "not in the static catalog; recorded verbatim."
                    ),
                    scope=f"portal.subscriptionInfo.extensions.{resolved.code}",
                )
            )
    return extensions


def _merge_extensions(
    base: list[ExtensionEntitlement],
    extras: Iterable[ExtensionEntitlement],
) -> list[ExtensionEntitlement]:
    by_key: dict[tuple[str, str], ExtensionEntitlement] = {
        (ext.source, ext.code): ext for ext in base
    }
    for extra in extras:
        by_key.setdefault((extra.source, extra.code), extra)
    return sorted(by_key.values(), key=lambda ext: (ext.source, ext.code))


def _iter_subscription_extensions(subscription_info: dict[str, Any]) -> Iterable[str]:
    for field in (
        "extensions",
        "extensionCodes",
        "extensionLicenseCodes",
        "licensedExtensions",
    ):
        explicit = subscription_info.get(field)
        if not isinstance(explicit, list):
            continue
        for value in explicit:
            if isinstance(value, dict):
                code = value.get("code") or value.get("id") or value.get("name")
                if code:
                    yield str(code)
            elif value:
                yield str(value)


def _safe_get(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        return payload.get(key)
    return None
