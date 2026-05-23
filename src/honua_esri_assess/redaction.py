"""Prospect-safe redaction helpers for handoff fields."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def sanitize_handoff_url(value: str) -> str:
    """Return a URL identifier safe to persist in ``EsriFootprint.json``.

    Esri targets may be supplied with auth material in userinfo, query strings,
    URL path parameters, or fragments. Those bytes are useful for scanner
    requests but are never part of the handoff contract.
    """

    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        netloc = parsed.netloc.rsplit("@", 1)[-1]
        path = _strip_path_params(parsed.path)
        return urlunsplit((parsed.scheme, netloc, path, "", ""))
    return value.split("?", 1)[0].split("#", 1)[0]


def _strip_path_params(path: str) -> str:
    return "/".join(segment.split(";", 1)[0] for segment in path.split("/"))
