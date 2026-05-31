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
from typing import Any, Iterable, TypeGuard

from honua_esri_assess.entitlements.diagnostics import (
    AssessmentError,
    Diagnostic,
)


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


def bounded_text(
    value: Any,
    cap: int,
    *,
    scope: str,
    diagnostics: list[Diagnostic],
    field: str | None = None,
) -> str | None:
    """Truncate ``value`` to ``cap`` characters with a ``redacted-field`` diagnostic.

    Used by the access collectors to guarantee that the v0.2 ``maxLength``
    caps on free-text fields (e.g. ``fullName`` at 256, role ``description``
    at 512) hold even when an Esri admin payload supplies an overlong
    string. Returns ``None`` when ``value`` is missing or not a non-empty
    string so the caller can drop the optional field cleanly.

    The truncation is byte-for-byte deterministic across runs and emits
    an info-severity diagnostic at ``scope`` so closed-product consumers
    can see when a field was bounded.
    """

    if not isinstance(value, str) or not value:
        return None
    if len(value) <= cap:
        return value
    qualifier = f" {field}" if field else ""
    diagnostics.append(
        Diagnostic(
            code="redacted-field",
            severity="info",
            message=(
                f"Free-text{qualifier} truncated to {cap} characters "
                "to satisfy the v0.2 schema cap."
            ),
            scope=scope,
        )
    )
    return value[:cap]


def bounded_str_array(
    values: Any,
    cap: int,
    *,
    scope: str,
    diagnostics: list[Diagnostic],
    field: str | None = None,
) -> tuple[str, ...]:
    """Bound each string entry in ``values`` to ``cap`` characters.

    Mirrors :func:`bounded_text` for the array-of-strings v0.2 caps such
    as ``RoleDefinition.privileges`` (items <= 128) and
    ``GroupDefinition.capabilities`` (items <= 64). Non-string entries
    are dropped silently; over-cap entries are truncated and a single
    ``redacted-field`` diagnostic is emitted per call regardless of how
    many entries were bounded so the diagnostic surface stays compact.
    """

    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return ()
    out: list[str] = []
    truncated = 0
    for entry in values:
        if not isinstance(entry, str) or not entry:
            continue
        if len(entry) > cap:
            entry = entry[:cap]
            truncated += 1
        out.append(entry)
    if truncated:
        qualifier = f" {field}" if field else ""
        diagnostics.append(
            Diagnostic(
                code="redacted-field",
                severity="info",
                message=(
                    f"{truncated} array{qualifier} entry/entries truncated "
                    f"to {cap} characters to satisfy the v0.2 schema cap."
                ),
                scope=scope,
            )
        )
    return tuple(out)


__all__ = [
    "AccessApiError",
    "AccessAuthError",
    "AccessConnectionError",
    "AccessExportError",
    "AccessForbiddenError",
    "AccessNotFoundError",
    "AccessRateLimitedError",
    "AccessSchemaError",
    "bounded_str_array",
    "bounded_text",
    "envelope_code",
    "is_safe_principal_name",
]
