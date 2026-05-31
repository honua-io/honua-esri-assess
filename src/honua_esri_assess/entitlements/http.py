"""HTTP client surface used by the entitlement collectors.

The collectors only depend on the :class:`HttpClient` protocol, so the
default ``requests``-backed implementation can be swapped for E4's
``PortalClient`` or E5's ``ServerClient`` with a single-import change once
those land. The same protocol is what fixture-driven tests stub.

Read-only by design: only ``get_json`` is exposed. Any future code that
needs ``POST`` belongs in a different module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode, urlparse, urlunparse
import json
import logging
import time
import urllib.error
import urllib.request


_LOG = logging.getLogger(__name__)


_REDACTED_QUERY_KEYS = frozenset(
    {
        "token",
        "auth",
        "password",
        "x-esri-authorization",
        "code",
        "client_secret",
    }
)


def safe_url(url: str) -> str:
    """Return ``url`` with credential-bearing pieces redacted.

    Esri admin endpoints typically take a ``?token=`` query parameter, and
    re-running the scanner with logging enabled would otherwise leak the
    token into log files. This helper strips those values, userinfo, and
    admin path tails before any log line, cache key, or error message uses
    the URL.
    """

    if not url:
        return url
    try:
        parsed = urlparse(url)
    except ValueError:
        return "[unparseable-url]"
    netloc = _safe_netloc(parsed)
    path = _safe_path(parsed.path)
    if not parsed.query:
        return urlunparse(parsed._replace(netloc=netloc, path=path, fragment=""))
    safe_pairs: list[tuple[str, str]] = []
    for pair in parsed.query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
        else:
            key, value = pair, ""
        if key.lower() in _REDACTED_QUERY_KEYS and value:
            value = "REDACTED"
        safe_pairs.append((key, value))
    redacted_query = "&".join(f"{k}={v}" if v != "" else k for k, v in safe_pairs)
    return urlunparse(
        parsed._replace(netloc=netloc, path=path, query=redacted_query, fragment="")
    )


def _safe_netloc(parsed: Any) -> str:
    if "@" not in parsed.netloc:
        return parsed.netloc
    host = parsed.hostname
    if host is None:
        return parsed.netloc.rsplit("@", 1)[-1]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    return f"{host}:{port}" if port is not None else host


def _safe_path(path: str) -> str:
    segments = path.split("/")
    for index, segment in enumerate(segments):
        if segment.lower() != "admin":
            continue
        if (
            index >= 2
            and segments[index - 2].lower() == "rest"
            and segments[index - 1].lower() == "services"
        ):
            continue
        return "/".join([*segments[: index + 1], "[redacted]"])
    return path


@dataclass(frozen=True)
class HttpResponse:
    """Minimal response envelope returned by :class:`HttpClient`."""

    status_code: int
    body: Any
    """Parsed JSON body, or ``None`` when the body was empty."""


class HttpClient(Protocol):
    """Duck-typed HTTP client used by the entitlement collectors."""

    def get_json(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        *,
        timeout: float | None = None,
    ) -> HttpResponse:
        """Issue an HTTP GET and return a parsed JSON response."""


class RequestsHttpClient:
    """Default HTTP client implementation using ``urllib`` from the stdlib.

    Kept stdlib-only to avoid forcing a third-party HTTP dep at the
    bootstrap stage. When E4/E5 land they will supply their own
    ``requests``-backed client that satisfies :class:`HttpClient`; this
    implementation only has to keep the fixture-driven tests honest.

    The class is named after ``requests`` because the design contract calls
    for that library; consumers should not depend on the concrete class.
    """

    _RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        *,
        token: str | None = None,
        user_agent: str = "honua-esri-assess",
        default_timeout: float = 30.0,
        max_attempts: int = 1,
        initial_backoff: float = 1.0,
        backoff_factor: float = 2.0,
        max_backoff_seconds: float = 30.0,
        sleep: Any = time.sleep,
    ) -> None:
        self._token = token
        self._user_agent = user_agent
        self._default_timeout = default_timeout
        self._max_attempts = max(1, int(max_attempts))
        self._initial_backoff = max(0.0, float(initial_backoff))
        self._backoff_factor = max(1.0, float(backoff_factor))
        self._max_backoff_seconds = max(0.0, float(max_backoff_seconds))
        self._sleep = sleep

    def get_json(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        *,
        timeout: float | None = None,
    ) -> HttpResponse:
        merged = dict(params or {})
        merged.setdefault("f", "json")
        if self._token and "token" not in merged:
            merged["token"] = self._token
        query = urlencode(merged)
        separator = "&" if ("?" in url) else "?"
        full_url = f"{url}{separator}{query}" if query else url
        request = urllib.request.Request(
            full_url,
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            method="GET",
        )
        effective_timeout = timeout if timeout is not None else self._default_timeout
        _LOG.debug("GET %s", safe_url(full_url))

        last_response: HttpResponse | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=effective_timeout) as response:
                    status = response.getcode()
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                raw = exc.read() if hasattr(exc, "read") else b""
                status = exc.code
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self._max_attempts:
                    self._sleep(self._backoff_for(attempt))
                    continue
                raise ConnectionError(str(exc)) from exc
            # Retry retryable HTTP statuses BEFORE attempting to parse the
            # body: Esri proxies routinely answer 503/429 with HTML/text,
            # and forcing a JSON parse on those would raise ValueError after
            # one attempt instead of letting --max-retries take effect.
            if status in self._RETRYABLE_STATUSES and attempt < self._max_attempts:
                self._sleep(self._backoff_for(attempt))
                continue
            body: Any = None
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"non-JSON response from Esri endpoint: {exc}"
                    ) from exc
            last_response = HttpResponse(status_code=status, body=body)
            # Esri also returns HTTP 200 with a JSON error envelope when the
            # gateway throttles; the collectors map ``error.code == 429`` to
            # ``AccessRateLimitedError``. Honor --max-retries for that shape
            # too so the client absorbs transient envelope throttles.
            if (
                _envelope_indicates_rate_limit(body)
                and attempt < self._max_attempts
            ):
                self._sleep(self._backoff_for(attempt))
                continue
            return last_response
        # Loop only exits via return or raise; the assertion guards against
        # a future edit that accidentally drops the terminal return.
        assert last_response is not None
        return last_response

    def _backoff_for(self, attempt: int) -> float:
        return min(
            self._initial_backoff * (self._backoff_factor ** (attempt - 1)),
            self._max_backoff_seconds,
        )


def _envelope_indicates_rate_limit(body: Any) -> bool:
    """Return True for an HTTP-200 Esri body whose error envelope is 429."""

    if not isinstance(body, dict):
        return False
    error = body.get("error")
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    if code is None:
        return False
    # Esri sometimes serializes the code as a string; coerce defensively
    # so the retry path covers both shapes without raising.
    try:
        numeric = int(code)
    except (TypeError, ValueError):
        return False
    return numeric == 429
