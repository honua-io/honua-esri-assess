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


@dataclass(frozen=True)
class AssessmentError(Exception):
    """Base class for sanitized assessment errors."""

    message: str
    code: str = "assessment.error"
    exit_code: int = 1
    context: Mapping[str, Any] = dataclass_field(default_factory=dict)
    severity: str = "error"

    def __str__(self) -> str:
        return self.message

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
            message=message,
            code=code,
            exit_code=exit_code,
            context=context or {},
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
            message=message,
            code="report.schema.invalid",
            exit_code=3,
            context=context or {},
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
            message=message,
            code="report.render.internal",
            exit_code=4,
            context=context or {},
        )


class PortalError(AssessmentError):
    """Base class for ArcGIS Portal scanner errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "portal.error",
        exit_code: int = 20,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            exit_code=exit_code,
            context=context or {},
        )


class PortalAuthError(PortalError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="portal.auth",
            exit_code=21,
            context=context,
        )


class PortalForbiddenError(PortalError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="portal.forbidden",
            exit_code=22,
            context=context,
        )


class PortalNotFoundError(PortalError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="portal.not-found",
            exit_code=23,
            context=context,
        )


class PortalRateLimitedError(PortalError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="portal.rate-limited",
            exit_code=24,
            context=context,
        )


class PortalConnectionError(PortalError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="portal.connection",
            exit_code=25,
            context=context,
        )


class PortalApiError(PortalError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="portal.api",
            exit_code=26,
            context=context,
        )


class PortalSchemaError(PortalError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="portal.schema",
            exit_code=27,
            context=context,
        )


def render_error(error: AssessmentError) -> str:
    """Return the one-line CLI error format."""

    return f"error: [{error.code}] {error.message}"
