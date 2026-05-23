"""Credential redaction helpers shared by the client, scanner, and cache."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Any query-parameter name matching one of these tokens is replaced with a
# fixed redaction sentinel before the URL is logged or hashed.
_REDACTED_PARAMS = frozenset({"token", "password", "passwd", "key", "apikey", "api_key"})
_REDACTION = "***"


def _strip_userinfo(netloc: str) -> str:
    """Remove ``user:pass@`` authority data while preserving host and port."""

    return netloc.rsplit("@", 1)[-1]


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
    """Redact credential-bearing URL parts from *url*.

    The path, scheme, host, and non-sensitive query params are preserved so
    the result still identifies the endpoint that was hit. Authority userinfo
    and URL fragments are dropped; secret-looking query parameters are
    replaced with the redaction sentinel.
    """

    parts = urlsplit(url)
    netloc = _strip_userinfo(parts.netloc)
    if not parts.query:
        return urlunsplit(parts._replace(netloc=netloc, fragment=""))
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    sanitized = [
        (key, _REDACTION if key.lower() in _REDACTED_PARAMS else value) for key, value in pairs
    ]
    return urlunsplit(parts._replace(netloc=netloc, query=urlencode(sanitized), fragment=""))


def credential_free_url(url: str) -> str:
    """Return *url* without authority credentials, query params, or fragments.

    This stricter form is for persisted artifacts. Unlike :func:`safe_url`,
    it does not retain non-sensitive query parameters because server identity
    URLs in ``EsriFootprint.json`` do not need any query string to be useful.
    """

    parts = urlsplit(url)
    return urlunsplit(parts._replace(netloc=_strip_userinfo(parts.netloc), query="", fragment=""))


__all__ = ["credential_free_url", "redact_params", "safe_url"]
