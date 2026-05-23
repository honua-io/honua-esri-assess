"""Read-only HTTP wrapper around the ArcGIS Server REST API.

The client deliberately exposes no write helpers: every call is a ``GET``
of the documented REST surface. This makes the read-only constraint a
property of the type, not of reviewer vigilance.

HTTP outcomes are mapped to typed diagnostics from
:mod:`honua_esri_assess.diagnostics`. ``Retry-After`` is honored
explicitly so 429s respect the value rather than backing off blindly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests

from .. import __version__
from ..diagnostics import (
    ServerApiError,
    ServerAuthError,
    ServerConnectionError,
    ServerForbiddenError,
    ServerNotFoundError,
    ServerRateLimitedError,
    sanitize_message,
)
from ..logging import get_logger
from ._safe import credential_free_url, redact_params, safe_url
from .auth import AnonymousCredential, Credential

_DEFAULT_USER_AGENT = f"honua-esri-assess/{__version__} (+https://github.com/honua-io/honua-esri-assess)"
_DEFAULT_TIMEOUT = 30.0
_REST_SUFFIX = "/arcgis/rest/services"
_ARCGIS_PREFIX = "/arcgis"

_AUTH_ERROR_CODES = frozenset({498, 499})


@dataclass(frozen=True)
class RetryPolicy:
    """Cap retries on transient HTTP failures.

    The defaults are intentionally conservative: three attempts with a
    30-second retry-sleep budget and exponential backoff between tries.
    Per-request timeout is controlled separately. A ``Retry-After`` header
    is always honored verbatim and is not multiplied by the exponential
    factor.
    """

    max_attempts: int = 3
    initial_backoff: float = 1.0
    backoff_factor: float = 2.0
    max_total_seconds: float = 30.0
    retry_statuses: frozenset[int] = field(default_factory=lambda: frozenset({429, 502, 503, 504}))


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None:
        return max(0.0, seconds)
    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    return max(0.0, (target - datetime.now(UTC)).total_seconds())


def normalize_base_url(base_url: str, *, allow_nonstandard: bool = False) -> str:
    """Canonicalize a user-supplied base URL to ``<host>/arcgis/rest/services``.

    Accepts any of ``https://host``, ``https://host/``,
    ``https://host/arcgis``, ``https://host/arcgis/``,
    ``https://host/arcgis/rest``, or ``https://host/arcgis/rest/services``
    and rewrites internally. With ``allow_nonstandard=True`` the path is
    preserved as-is for servers mounted under unusual prefixes.
    """

    if not base_url:
        raise ValueError("base_url must be a non-empty string")
    safe_base_url = credential_free_url(base_url)
    parts = urlsplit(safe_base_url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"base_url must include scheme and host, got {safe_base_url!r}")
    path = parts.path.rstrip("/")
    if allow_nonstandard:
        return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")
    lowered = path.lower()
    if lowered.endswith("/rest/services"):
        canonical_path = path
    elif lowered.endswith("/rest"):
        canonical_path = path + "/services"
    elif lowered.endswith("/arcgis"):
        canonical_path = path + "/rest/services"
    elif lowered == "":
        canonical_path = _ARCGIS_PREFIX + "/rest/services"
    else:
        # Treat as a custom mount that still needs the REST suffix appended.
        canonical_path = path + "/rest/services"
    return urlunsplit((parts.scheme, parts.netloc, canonical_path, "", ""))


def _rest_root_to_info_url(rest_root: str) -> str:
    """Map the canonical ``/arcgis/rest/services`` root to ``/arcgis/rest/info``."""

    parts = urlsplit(rest_root)
    path = parts.path
    if path.lower().endswith("/services"):
        info_path = path[: -len("/services")] + "/info"
    else:
        info_path = path.rstrip("/") + "/info"
    return urlunsplit((parts.scheme, parts.netloc, info_path, "", ""))


class ServerClient:
    """Thin ``GET``-only wrapper around the ArcGIS Server REST API.

    The client owns base-URL normalization, credential application, retry
    policy, and HTTP-to-typed-diagnostic mapping. It does not own catalog
    or service-shape semantics — those live in :class:`ServerScanner`.
    """

    def __init__(
        self,
        base_url: str,
        credential: Credential | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        user_agent: str = _DEFAULT_USER_AGENT,
        retry: RetryPolicy | None = None,
        session: requests.Session | None = None,
        sleep: Any = time.sleep,
        allow_nonstandard_base: bool = False,
    ) -> None:
        self.base_url = normalize_base_url(base_url, allow_nonstandard=allow_nonstandard_base)
        self.credential: Credential = credential or AnonymousCredential()
        self.timeout = timeout
        self.user_agent = user_agent
        self.retry = retry or RetryPolicy()
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", user_agent)
        self._sleep = sleep
        self._log = get_logger("server.client")

    # --- public helpers -------------------------------------------------

    @property
    def rest_root(self) -> str:
        return self.base_url

    @property
    def info_url(self) -> str:
        return _rest_root_to_info_url(self.base_url)

    def get_services_root(self) -> dict[str, Any]:
        return self.get_json(self.base_url)

    def get_rest_info(self) -> dict[str, Any]:
        return self.get_json(self.info_url)

    def get_folder(self, folder: str) -> dict[str, Any]:
        return self.get_json(f"{self.base_url}/{folder}")

    def get_service(self, *, name: str, service_type: str, folder: str | None) -> dict[str, Any]:
        if folder:
            url = f"{self.base_url}/{folder}/{name}/{service_type}"
        else:
            url = f"{self.base_url}/{name}/{service_type}"
        return self.get_json(url)

    # --- core ----------------------------------------------------------

    def get_json(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        """``GET`` *url* with ``f=json`` and credential params merged in.

        Returns the parsed JSON body on success; raises a typed
        :class:`AssessmentError` subclass otherwise. The Esri error
        envelope (``{"error": {...}}``) is also surfaced as a typed
        error even when HTTP status is 200.
        """

        request_params: dict[str, str] = {"f": "json"}
        if params:
            request_params.update({k: str(v) for k, v in params.items()})
        request_params = self.credential.apply(request_params)
        return self._request_with_retry(url, request_params)

    # --- internal ------------------------------------------------------

    def _request_with_retry(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        attempt = 0
        elapsed = 0.0
        safe = safe_url(url + ("?" + urlencode(redact_params(params)) if params else ""))
        last_status: int | None = None
        while True:
            attempt += 1
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.exceptions.RequestException as exc:
                raise ServerConnectionError(
                    f"could not reach ArcGIS Server: {type(exc).__name__}",
                    context={"url": safe},
                ) from None

            status = response.status_code
            last_status = status
            if status in self.retry.retry_statuses and attempt < self.retry.max_attempts:
                delay = self._compute_delay(response, attempt)
                if elapsed + delay > self.retry.max_total_seconds:
                    break
                self._log.warning(
                    "transient HTTP %s; sleeping %.2fs before retry %d/%d",
                    status,
                    delay,
                    attempt,
                    self.retry.max_attempts,
                    extra={"url": safe, "status": status},
                )
                self._sleep(delay)
                elapsed += delay
                continue
            break

        # Map terminal HTTP status to typed errors.
        if status == 401:
            raise ServerAuthError(
                "ArcGIS Server rejected the supplied credential (HTTP 401)",
                context={"url": safe, "status": 401},
            )
        if status == 403:
            raise ServerForbiddenError(
                "ArcGIS Server refused access to the requested resource (HTTP 403)",
                context={"url": safe, "status": 403},
            )
        if status == 404:
            raise ServerNotFoundError(
                "ArcGIS Server returned 404 for the requested resource",
                context={"url": safe, "status": 404},
            )
        if status == 429:
            raise ServerRateLimitedError(
                "ArcGIS Server rate-limited the scanner after retries (HTTP 429)",
                context={"url": safe, "status": 429},
            )
        if status >= 500:
            raise ServerConnectionError(
                f"ArcGIS Server returned a server-side error (HTTP {status})",
                context={"url": safe, "status": status},
            )
        if status >= 400:
            raise ServerApiError(
                f"ArcGIS Server returned HTTP {status}",
                context={"url": safe, "status": status},
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ServerApiError(
                "ArcGIS Server response did not parse as JSON",
                context={"url": safe, "status": status, "reason": type(exc).__name__},
            ) from None

        # ArcGIS commonly returns HTTP 200 with an embedded error envelope.
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            err = body["error"]
            esri_code = err.get("code") if isinstance(err.get("code"), int) else None
            raw_message = err.get("message") if isinstance(err.get("message"), str) else None
            message = sanitize_message(raw_message, fallback="ArcGIS Server returned an error")
            ctx = {"url": safe, "esriCode": esri_code}
            if esri_code in _AUTH_ERROR_CODES or esri_code == 401:
                raise ServerAuthError(message, context=ctx)
            if esri_code == 403:
                raise ServerForbiddenError(message, context=ctx)
            if esri_code == 404:
                raise ServerNotFoundError(message, context=ctx)
            if esri_code == 429:
                raise ServerRateLimitedError(message, context=ctx)
            raise ServerApiError(message, esri_code=esri_code, context=ctx)

        if not isinstance(body, dict):
            raise ServerApiError(
                "ArcGIS Server response was not a JSON object",
                context={"url": safe, "status": status},
            )
        return body

    def _compute_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            return min(retry_after, self.retry.max_total_seconds)
        # Exponential backoff capped by ``max_total_seconds``.
        backoff = self.retry.initial_backoff * (self.retry.backoff_factor ** (attempt - 1))
        return min(backoff, self.retry.max_total_seconds)


__all__ = ["RetryPolicy", "ServerClient", "normalize_base_url"]
