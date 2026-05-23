"""Typed exception hierarchy and structured diagnostic records.

Soft failures (e.g., admin endpoint denies access to a service-publisher
token) become :class:`Diagnostic` records inside the artifact; hard failures
(host unreachable, schema parse error) raise typed
:class:`EntitlementsError` subclasses that the CLI catches and renders as
prospect-safe messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DiagnosticSeverity = Literal["info", "warn", "error"]
"""Severity ladder mirrored from the EsriFootprint.json diagnostics surface."""


DiagnosticCode = Literal[
    "missing-permission",
    "partial-coverage",
    "rate-limited",
    "unresolved-reference",
    "unsupported-item-type",
    "redacted-field",
]
"""Locked v0.1 diagnostic code set carried in the artifact.

This module emits a subset: ``missing-permission`` (auth/forbidden on
optional endpoints), ``partial-coverage`` (degraded/unknown payload),
``rate-limited`` (429 from an Esri endpoint), and ``unresolved-reference``
(referenced service or folder could not be enumerated). Unknown extension
codes use ``partial-coverage`` with the unknown identifier carried in
    ``scope`` so E2's enum does not need to grow.
"""


@dataclass(frozen=True)
class Diagnostic:
    """One soft-failure record consumed by the footprint emitter.

    The ``scope`` field is a dotted path or stable identifier (e.g.,
    ``"portal.subscriptionInfo"``, ``"server.system/licenses"``,
    ``"server.services/Map/MapServer"``) that the closed migration product
    can route on. It must not contain credentials.
    """

    code: DiagnosticCode
    severity: DiagnosticSeverity
    message: str
    scope: str
    hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "scope": self.scope,
        }
        if self.hint is not None:
            out["hint"] = self.hint
        return out


class AssessmentError(Exception):
    """Root for all honua-esri-assess hard failures."""


class EntitlementsError(AssessmentError):
    """Root for the entitlements module."""


class EntitlementsAuthError(EntitlementsError):
    """Esri endpoint returned 401 on a required endpoint."""


class EntitlementsForbiddenError(EntitlementsError):
    """Esri endpoint returned 403 on a required endpoint."""


class EntitlementsNotFoundError(EntitlementsError):
    """Esri endpoint returned 404 on a required endpoint."""


class EntitlementsRateLimitedError(EntitlementsError):
    """Esri endpoint returned 429 on a required endpoint."""


class EntitlementsConnectionError(EntitlementsError):
    """Network failure reaching an Esri endpoint."""


class EntitlementsApiError(EntitlementsError):
    """Esri endpoint returned an unexpected error envelope or HTTP status."""


class EntitlementsSchemaError(EntitlementsError):
    """Response body could not be parsed into the expected shape."""
