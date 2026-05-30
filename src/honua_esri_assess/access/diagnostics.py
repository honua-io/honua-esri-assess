"""Typed exception hierarchy for the access export module.

Soft failures (e.g., admin endpoint denies access to a user list) become
:class:`Diagnostic` records inside the artifact and reuse the locked v0.1
diagnostic-code vocabulary defined in
:mod:`honua_esri_assess.entitlements.diagnostics`. Hard failures raise
:class:`AccessExportError` subclasses that the CLI catches and renders as
prospect-safe messages.
"""

from __future__ import annotations

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


__all__ = [
    "AccessApiError",
    "AccessAuthError",
    "AccessConnectionError",
    "AccessExportError",
    "AccessForbiddenError",
    "AccessNotFoundError",
    "AccessRateLimitedError",
    "AccessSchemaError",
]
