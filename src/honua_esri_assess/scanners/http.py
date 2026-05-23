"""Shared read-only HTTP helpers for Esri scanners."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from honua_esri_assess.diagnostics import Diagnostic


@dataclass(frozen=True)
class RequestOptions:
    token: str | None = None
    user_agent: str | None = None
    timeout: float = 10.0
    max_retries: int = 0


class JsonSession(Protocol):
    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> Any: ...


def configure_session(session: JsonSession, options: RequestOptions) -> None:
    headers = getattr(session, "headers", None)
    if options.user_agent and isinstance(headers, MutableMapping):
        headers["User-Agent"] = options.user_agent


def fetch_json(
    session: JsonSession,
    url: str,
    diagnostics: list[Diagnostic],
    target_label: str,
    *,
    options: RequestOptions,
    params: dict[str, Any] | None = None,
) -> Any:
    request_params = dict(params or {"f": "json"})
    if options.token:
        request_params.setdefault("token", options.token)

    attempts = max(0, options.max_retries) + 1
    for attempt in range(attempts):
        try:
            response = session.get(url, params=request_params, timeout=options.timeout)
        except requests.RequestException:
            if attempt + 1 < attempts:
                continue
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    message=(
                        f"Could not reach {target_label}; inventory may be incomplete."
                    ),
                    scope=target_label,
                )
            )
            return None

        status = response.status_code
        if status in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
            continue
        return _decode_response(response, diagnostics, target_label)

    return None


def _decode_response(
    response: Any,
    diagnostics: list[Diagnostic],
    target_label: str,
) -> Any:
    status = response.status_code
    if status == 403:
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                message=f"Access denied while reading {target_label}.",
                scope=target_label,
            )
        )
        return None
    if status == 429:
        diagnostics.append(
            Diagnostic(
                code="rate-limited",
                message=(
                    f"Rate limited while reading {target_label}; "
                    "partial inventory returned."
                ),
                scope=target_label,
                severity="info",
            )
        )
        return None
    if status >= 400:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Upstream returned HTTP {status} for {target_label}.",
                scope=target_label,
            )
        )
        return None
    try:
        payload = response.json()
    except ValueError:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Non-JSON response from {target_label}.",
                scope=target_label,
            )
        )
        return None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        err_code = payload["error"].get("code")
        if err_code == 403:
            diagnostics.append(
                Diagnostic(
                    code="missing-permission",
                    message=f"Access denied while reading {target_label}.",
                    scope=target_label,
                )
            )
        elif err_code == 429:
            diagnostics.append(
                Diagnostic(
                    code="rate-limited",
                    message=(
                        f"Rate limited while reading {target_label}; "
                        "partial inventory returned."
                    ),
                    scope=target_label,
                    severity="info",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    code="partial-coverage",
                    message=f"Esri returned an error envelope for {target_label}.",
                    scope=target_label,
                )
            )
        return None
    return payload
