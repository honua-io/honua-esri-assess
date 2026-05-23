"""Typed, prospect-safe diagnostics surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    scope: str = "unknown"
    severity: str = "warn"
    hint: str | None = None

    def __post_init__(self) -> None:
        if self.code not in DIAGNOSTIC_CODES:
            raise ValueError(
                f"Unknown diagnostic code {self.code!r}; "
                f"expected one of {sorted(DIAGNOSTIC_CODES)}"
            )
        if self.severity not in SEVERITY_LEVELS:
            raise ValueError(
                f"Unknown diagnostic severity {self.severity!r}; "
                f"expected one of {sorted(SEVERITY_LEVELS)}"
            )

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {
            "code": self.code,
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
    code: str
    exit_code: int
    context: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


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
