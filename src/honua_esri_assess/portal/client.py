"""Read-only HTTP client for the ArcGIS Portal Sharing REST API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import time
from typing import Any, Callable
from urllib.parse import ParseResult, parse_qsl, urlencode, urlparse, urlunparse

import requests

from honua_esri_assess.diagnostics import (
    PortalApiError,
    PortalAuthError,
    PortalConnectionError,
    PortalForbiddenError,
    PortalNotFoundError,
    PortalRateLimitedError,
)
from honua_esri_assess.portal.auth import AnonymousCredential, Credential

LOGGER = logging.getLogger(__name__)

SENSITIVE_QUERY_KEYS = {"token", "password", "passwd", "client_secret", "assertion"}
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    backoff_seconds: float = 0.5
    retry_after_cap_seconds: float = 30.0


@dataclass(frozen=True)
class PortalUrls:
    portal_url: str
    sharing_rest_url: str


def normalize_portal_url(target: str) -> PortalUrls:
    """Normalize a portal target to the user-facing URL and Sharing API root."""

    raw_target = target.strip().rstrip("/")
    parsed = urlparse(raw_target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PortalApiError(
            "Portal target must be an absolute http(s) URL.",
            context={"target": redact_url(raw_target)},
        )
    try:
        parsed.port  # noqa: B018 - access triggers stdlib int() parsing
    except ValueError as exc:
        raise PortalApiError(
            "Portal target has an invalid port.",
            context={"target": redact_url(raw_target)},
        ) from exc

    path_lower = parsed.path.lower()
    marker = "/sharing/rest"
    marker_index = path_lower.find(marker)
    if marker_index >= 0:
        portal_path = parsed.path[:marker_index].rstrip("/")
        sharing_path = parsed.path[: marker_index + len(marker)]
    else:
        portal_path = parsed.path.rstrip("/")
        sharing_path = f"{portal_path}/sharing/rest" if portal_path else "/sharing/rest"

    safe_netloc = _host_port_netloc(parsed)
    portal_url = urlunparse((parsed.scheme, safe_netloc, portal_path, "", "", ""))
    sharing_rest_url = urlunparse((parsed.scheme, safe_netloc, sharing_path, "", "", ""))
    return PortalUrls(portal_url=portal_url.rstrip("/"), sharing_rest_url=sharing_rest_url.rstrip("/"))


def redact_url(url: str) -> str:
    """Redact known credential query parameters from a URL string."""

    parsed = urlparse(url)
    if parsed.hostname:
        parsed = parsed._replace(netloc=_host_port_netloc(parsed))
    if not parsed.query:
        return urlunparse(parsed)

    redacted_params: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS:
            redacted_params.append((key, "[REDACTED]"))
        else:
            redacted_params.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(redacted_params)))


def _host_port_netloc(parsed: ParseResult) -> str:
    host = parsed.hostname or parsed.netloc
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        # Malformed (non-numeric) port — keep the raw netloc string so callers
        # never raise from URL redaction. Callers that need a typed error
        # validate parsed.port themselves.
        return parsed.netloc or host
    if port is not None:
        return f"{host}:{port}"
    return host


class PortalClient:
    """Thin, read-only wrapper around the Portal Sharing REST API."""

    def __init__(
        self,
        target: str,
        credential: Credential | None = None,
        *,
        timeout: float = 30.0,
        retry_policy: RetryPolicy | None = None,
        session: requests.Session | None = None,
        user_agent: str = "honua-esri-assess/0.0.0",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.urls = normalize_portal_url(target)
        self.credential = credential or AnonymousCredential()
        self.timeout = timeout
        self.retry_policy = retry_policy or RetryPolicy()
        self.session = session or requests.Session()
        self.sleep = sleep
        self.session.headers.update({"User-Agent": user_agent})

    @property
    def portal_url(self) -> str:
        return self.urls.portal_url

    @property
    def sharing_rest_url(self) -> str:
        return self.urls.sharing_rest_url

    @property
    def auth_mode(self) -> str:
        return self.credential.auth_mode

    def get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a Portal resource and return its JSON body."""

        url = self._absolute_url(path_or_url)
        request_params = {"f": "json", **(params or {}), **self.credential.params()}
        safe_request_url = redact_url(self.credential.redact(_format_url(url, request_params)))

        response: requests.Response | None = None
        for attempt in range(1, max(1, self.retry_policy.attempts) + 1):
            try:
                response = self.session.get(url, params=request_params, timeout=self.timeout)
            except (requests.RequestException, ValueError) as exc:
                # ValueError covers malformed URL components (e.g. non-numeric
                # port) that some urllib3 / requests versions surface before
                # wrapping them as RequestException.
                message = f"Could not connect to ArcGIS Portal at {redact_url(url)}."
                raise PortalConnectionError(message, context={"url": redact_url(url)}) from exc

            if response.status_code not in RETRYABLE_STATUSES or attempt >= self.retry_policy.attempts:
                break

            delay = self._retry_delay(response, attempt)
            LOGGER.info(
                "retrying_portal_request",
                extra={"url": safe_request_url, "status": response.status_code, "delay": delay},
            )
            self.sleep(delay)

        if response is None:
            raise PortalConnectionError(
                f"Could not connect to ArcGIS Portal at {redact_url(url)}.",
                context={"url": redact_url(url)},
            )

        payload = self._parse_json(response, safe_request_url)
        if response.status_code >= 400:
            raise self._status_error(response.status_code, safe_request_url, payload)

        api_error = self._api_error(payload, safe_request_url)
        if api_error:
            raise api_error
        return payload

    def _absolute_url(self, path_or_url: str) -> str:
        parsed = urlparse(path_or_url)
        if parsed.scheme and parsed.netloc:
            return path_or_url
        return f"{self.sharing_rest_url}/{path_or_url.lstrip('/')}"

    def _parse_json(self, response: requests.Response, safe_url: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise PortalApiError(
                "ArcGIS Portal returned a non-JSON response.",
                context={"url": safe_url, "status": response.status_code},
            ) from exc
        if not isinstance(payload, dict):
            raise PortalApiError(
                "ArcGIS Portal returned an unexpected JSON response.",
                context={"url": safe_url, "status": response.status_code},
            )
        return payload

    def _status_error(
        self, status_code: int, safe_url: str, payload: dict[str, Any]
    ) -> PortalApiError:
        api_error = self._api_error(payload, safe_url, status_code=status_code)
        if api_error:
            return api_error
        if status_code == 401:
            return PortalAuthError("ArcGIS Portal rejected the provided credential.", context={"url": safe_url})
        if status_code == 403:
            return PortalForbiddenError("ArcGIS Portal denied access to the requested resource.", context={"url": safe_url})
        if status_code == 404:
            return PortalNotFoundError("ArcGIS Portal resource was not found.", context={"url": safe_url})
        if status_code == 429:
            return PortalRateLimitedError("ArcGIS Portal rate limited the scan.", context={"url": safe_url})
        return PortalApiError(
            "ArcGIS Portal returned an unsuccessful response.",
            context={"url": safe_url, "status": status_code},
        )

    def _api_error(
        self, payload: dict[str, Any], safe_url: str, *, status_code: int | None = None
    ) -> PortalApiError | None:
        error = payload.get("error")
        if not isinstance(error, dict):
            return None

        esri_code = _coerce_int(error.get("code"))
        raw_message = str(error.get("message") or "ArcGIS Portal returned an error.")
        message = _sanitize_message(self.credential.redact(raw_message))
        context: dict[str, Any] = {"url": safe_url}
        if status_code is not None:
            context["status"] = status_code
        if esri_code is not None:
            context["esriCode"] = esri_code

        if status_code == 401 or esri_code in {498, 499}:
            return PortalAuthError("ArcGIS Portal rejected the provided credential.", context=context)
        if status_code == 403:
            return PortalForbiddenError(message or "ArcGIS Portal denied access.", context=context)
        if status_code == 404:
            return PortalNotFoundError(message or "ArcGIS Portal resource was not found.", context=context)
        if status_code == 429 or esri_code == 429:
            return PortalRateLimitedError("ArcGIS Portal rate limited the scan.", context=context)
        return PortalApiError(message, context=context)

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            parsed_delay = _parse_retry_after(retry_after)
            if parsed_delay is not None:
                return min(parsed_delay, self.retry_policy.retry_after_cap_seconds)
        return min(
            self.retry_policy.backoff_seconds * (2 ** (attempt - 1)),
            self.retry_policy.retry_after_cap_seconds,
        )


def _format_url(url: str, params: dict[str, Any]) -> str:
    return f"{url}?{urlencode(params, doseq=True)}"


def _sanitize_message(message: str) -> str:
    single_line = " ".join(message.split())
    if len(single_line) > 240:
        return f"{single_line[:237]}..."
    return single_line


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_retry_after(value: str) -> float | None:
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
