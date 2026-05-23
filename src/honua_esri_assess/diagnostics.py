"""Typed, prospect-safe diagnostics surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Final

DIAGNOSTIC_CODES: Final[frozenset[str]] = frozenset(
    {
        "rate-limited",
        "partial-coverage",
        "missing-permission",
        "unresolved-reference",
        "unsupported-item-type",
        "redacted-field",
    }
)

SEVERITY_LEVELS: Final[frozenset[str]] = frozenset({"info", "warn", "error"})
_SEVERITY_ALIASES: Final[dict[str, str]] = {"warning": "warn"}
_MAX_MESSAGE_LENGTH = 240


@dataclass(frozen=True)
class Diagnostic:
    """A scanner diagnostic that can be emitted into the v0.1 contract."""

    code: str
    message: str
    scope: str = "unknown"
    severity: str = "warn"
    hint: str | None = None
    field: str | None = None
    context: Mapping[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = _SEVERITY_ALIASES.get(self.severity, self.severity)
        if normalized not in SEVERITY_LEVELS:
            raise ValueError(
                f"Unknown diagnostic severity {self.severity!r}; "
                f"expected one of {sorted(SEVERITY_LEVELS)}"
            )
        object.__setattr__(self, "severity", normalized)

    def to_dict(self) -> dict[str, Any]:
        code = self.code if self.code in DIAGNOSTIC_CODES else "partial-coverage"
        out: dict[str, Any] = {
            "code": code,
            "severity": self.severity,
            "message": self.message,
            "scope": self.scope,
        }
        if self.hint is not None:
            out["hint"] = self.hint
        return out


class AssessmentError(Exception):
    """Base class for sanitized assessment errors."""

    code = "assessment.error"
    exit_code = 1
    severity = "error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        exit_code: int | None = None,
        context: Mapping[str, Any] | None = None,
        severity: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.exit_code = exit_code if exit_code is not None else self.exit_code
        self.context: Mapping[str, Any] = dict(context) if context else {}
        self.severity = severity or self.severity

    def __str__(self) -> str:
        return self.message

    def render(self) -> str:
        return render_error(self)

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code,
            severity=self.severity,
            message=self.message,
            context=self.context,
        )


class ReportInputError(AssessmentError):
    """Input or output handling failed before or after rendering."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "report.input.read",
        exit_code: int = 2,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=code,
            exit_code=exit_code,
            context=context,
        )


class ReportSchemaValidationError(AssessmentError):
    """A strict report input failed EsriFootprint schema validation."""

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="report.schema.invalid",
            exit_code=3,
            context=context,
        )


class ReportRenderError(AssessmentError):
    """Report rendering failed after input parsing succeeded."""

    def __init__(
        self,
        message: str = "Unable to render readiness report.",
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="report.render.internal",
            exit_code=4,
            context=context,
        )


class ServerError(AssessmentError):
    code = "server.error"
    exit_code = 10


class ServerAuthError(ServerError):
    code = "server.auth"
    exit_code = 11


class ServerForbiddenError(ServerError):
    code = "server.forbidden"
    exit_code = 12


class ServerNotFoundError(ServerError):
    code = "server.not-found"
    exit_code = 13


class ServerRateLimitedError(ServerError):
    code = "server.rate-limited"
    exit_code = 14


class ServerConnectionError(ServerError):
    code = "server.connection"
    exit_code = 15


class ServerApiError(ServerError):
    code = "server.api"
    exit_code = 16

    def __init__(
        self,
        message: str,
        *,
        esri_code: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, context=context)
        self.esri_code = esri_code


class ServerSchemaError(ServerError):
    code = "server.schema"
    exit_code = 17


class PortalError(AssessmentError):
    """Base class for ArcGIS Portal scanner errors."""

    code = "portal.error"
    exit_code = 20


class PortalAuthError(PortalError):
    code = "portal.auth"
    exit_code = 21


class PortalForbiddenError(PortalError):
    code = "portal.forbidden"
    exit_code = 22


class PortalNotFoundError(PortalError):
    code = "portal.not-found"
    exit_code = 23


class PortalRateLimitedError(PortalError):
    code = "portal.rate-limited"
    exit_code = 24


class PortalConnectionError(PortalError):
    code = "portal.connection"
    exit_code = 25


class PortalApiError(PortalError):
    code = "portal.api"
    exit_code = 26


class PortalSchemaError(PortalError):
    code = "portal.schema"
    exit_code = 27


def sanitize_message(message: str | None, *, fallback: str = "ArcGIS Server error") -> str:
    """Trim and length-cap an Esri error message so it stays prospect-safe."""

    if not message:
        return fallback
    cleaned = " ".join(str(message).split())
    safe_parts = [
        part
        for part in cleaned.split(" ")
        if not (part.startswith("http://") or part.startswith("https://"))
    ]
    safe = " ".join(safe_parts).strip() or fallback
    if len(safe) > _MAX_MESSAGE_LENGTH:
        safe = safe[: _MAX_MESSAGE_LENGTH - 1].rstrip() + "..."
    return safe


def render_error(error: AssessmentError) -> str:
    """Return the one-line CLI error format."""

    return f"error: [{error.code}] {error.message}"


__all__ = [
    "AssessmentError",
    "DIAGNOSTIC_CODES",
    "Diagnostic",
    "PortalApiError",
    "PortalAuthError",
    "PortalConnectionError",
    "PortalError",
    "PortalForbiddenError",
    "PortalNotFoundError",
    "PortalRateLimitedError",
    "PortalSchemaError",
    "ReportInputError",
    "ReportRenderError",
    "ReportSchemaValidationError",
    "SEVERITY_LEVELS",
    "ServerApiError",
    "ServerAuthError",
    "ServerConnectionError",
    "ServerError",
    "ServerForbiddenError",
    "ServerNotFoundError",
    "ServerRateLimitedError",
    "ServerSchemaError",
    "render_error",
    "sanitize_message",
]
