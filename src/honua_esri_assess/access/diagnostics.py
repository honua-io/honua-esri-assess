"""Typed exception hierarchy for the access export module.

Soft failures (e.g., admin endpoint denies access to a user list) become
:class:`Diagnostic` records inside the artifact and reuse the locked v0.1
diagnostic-code vocabulary defined in
:mod:`honua_esri_assess.entitlements.diagnostics`. Hard failures raise
:class:`AccessExportError` subclasses that the CLI catches and renders as
prospect-safe messages.
"""

from __future__ import annotations

from typing import Any

from honua_esri_assess.entitlements.diagnostics import AssessmentError


class AccessExportError(AssessmentError):
    """Root for the access export module."""


class AccessAuthError(AccessExportError):
    """Esri endpoint returned 401 on a required access endpoint."""


class AccessForbiddenError(AccessExportError):
    """Esri endpoint returned 403 on a required access endpoint."""


class AccessNotFoundError(AccessExportError):
    """Esri endpoint returned 404 on a required access endpoint."""


class AccessRateLimitedError(AccessExportError):
    """Esri endpoint returned 429 on a required access endpoint."""


class AccessConnectionError(AccessExportError):
    """Network failure reaching an Esri access endpoint."""


class AccessApiError(AccessExportError):
    """Esri endpoint returned an unexpected error envelope or HTTP status."""


class AccessSchemaError(AccessExportError):
    """Response body could not be parsed into the expected shape."""


def envelope_code(error_obj: Any) -> int:
    """Coerce an Esri error envelope's ``code`` field to ``int`` safely.

    Esri admin endpoints occasionally serialize the envelope ``code`` as a
    string, and broken proxies have been observed dropping non-numeric
    values into it. A bare ``int(...)`` therefore raises ``ValueError``,
    which is not an :class:`AccessExportError` and would otherwise bypass
    the scan handler's ``access-export-failed`` mapping and surface as a
    generic ``internal-error``. Routing through this helper keeps the
    failure typed.

    Returns ``0`` when the envelope contains no ``code`` (or an empty
    one); raises :class:`AccessSchemaError` for any value that cannot be
    parsed as an integer.
    """

    if not isinstance(error_obj, dict):
        return 0
    raw = error_obj.get("code")
    if raw is None or raw == "":
        return 0
    if isinstance(raw, bool):
        # ``bool`` is a subclass of ``int``; treat it as a schema mismatch.
        raise AccessSchemaError(
            "Esri error envelope contained a boolean where an integer code was expected."
        )
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise AccessSchemaError(
            "Esri error envelope contained a non-integer code; refusing to interpret it."
        ) from None


__all__ = [
    "AccessApiError",
    "AccessAuthError",
    "AccessConnectionError",
    "AccessExportError",
    "AccessForbiddenError",
    "AccessNotFoundError",
    "AccessRateLimitedError",
    "AccessSchemaError",
    "envelope_code",
]
