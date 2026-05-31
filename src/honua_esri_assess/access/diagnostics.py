"""Typed exception hierarchy for the access export module.

Soft failures (e.g., admin endpoint denies access to a user list) become
:class:`Diagnostic` records inside the artifact and reuse the locked v0.1
diagnostic-code vocabulary defined in
:mod:`honua_esri_assess.entitlements.diagnostics`. Hard failures raise
:class:`AccessExportError` subclasses that the CLI catches and renders as
prospect-safe messages.
"""

from __future__ import annotations

import re
from typing import Any, TypeGuard

from honua_esri_assess.entitlements.diagnostics import AssessmentError


# Same RFC822-ish email shape used by the v0.2 PrincipalName schema's
# ``not`` clause. Keep these in lock-step: a value that the collector
# accepts here MUST also pass the schema.
_PRINCIPAL_NAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
_EMAIL_SHAPE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def is_safe_principal_name(value: Any) -> TypeGuard[str]:
    """Return True iff *value* is a schema-valid ``PrincipalName``.

    A schema-valid PrincipalName matches ``^[A-Za-z0-9._@-]{1,128}$`` AND
    is NOT email-shaped. The v0.2 schema's ``PrincipalName.not`` clause
    rejects RFC822-ish ``user@host.tld`` values; the collectors must
    mirror that check or the artifact would carry records that strict
    consumers reject. Subject-style ids like ``alice@enterprise``
    (no TLD-shaped suffix) remain valid.

    Annotated as a :class:`typing.TypeGuard` so callers can narrow the
    inferred type to ``str`` after the check, mirroring the dataclass
    fields that consume the value.
    """

    if not isinstance(value, str):
        return False
    if not _PRINCIPAL_NAME_RE.fullmatch(value):
        return False
    if _EMAIL_SHAPE_RE.fullmatch(value):
        return False
    return True


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
    "is_safe_principal_name",
]
