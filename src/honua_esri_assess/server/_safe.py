"""Credential redaction helpers shared by the client, scanner, and cache."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Any query-parameter name matching one of these tokens is replaced with a
# fixed redaction sentinel before the URL is logged or hashed.
_REDACTED_PARAMS = frozenset({"token", "password", "passwd", "key", "apikey", "api_key"})
_REDACTION = "***"


def redact_params(params: dict[str, str]) -> dict[str, str]:
    """Return a copy of *params* with credential-bearing keys masked."""

    safe: dict[str, str] = {}
    for key, value in params.items():
        if key.lower() in _REDACTED_PARAMS:
            safe[key] = _REDACTION
        else:
            safe[key] = value
    return safe


def safe_url(url: str) -> str:
    """Strip credential-bearing query params from *url*.

    The path, scheme, and host are preserved so the result still identifies
    the endpoint that was hit; only secret-looking query parameters are
    replaced with the redaction sentinel.
    """

    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    sanitized = [
        (key, _REDACTION if key.lower() in _REDACTED_PARAMS else value) for key, value in pairs
    ]
    return urlunsplit(parts._replace(query=urlencode(sanitized)))


__all__ = ["redact_params", "safe_url"]
