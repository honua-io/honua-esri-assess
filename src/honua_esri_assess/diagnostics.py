"""Typed, prospect-safe diagnostics surface."""

from __future__ import annotations

import json
import os
import re
import tempfile
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import typer

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

SECRET_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(r"(?i)(token|password|secret|authorization|api[_-]?key)=([^&\s]+)"),
        r"\1=<redacted>",
    ),
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1<redacted>"),
    (re.compile(r"(://)([^/\s@]+)@"), r"\1<redacted>@"),
    (
        re.compile(
            r"(?i)([;?&])(jsessionid|phpsessid|aspsessionid[a-z0-9]*|sessionid|sid)=([^&\s;#?]+)"
        ),
        r"\1\2=<redacted>",
    ),
)


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
class CliDiagnostic:
    code: str
    severity: str
    message: str
    scope: str | None = None


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


class DiagnosticError(Exception):
    """Base class for expected command failures."""

    exit_code = 10

    def __init__(
        self,
        message: str,
        *,
        code: str = "scanner-error",
        scope: str | None = None,
        severity: str = "error",
    ) -> None:
        super().__init__(message)
        self.diagnostic = CliDiagnostic(
            code=code,
            severity=severity,
            message=message,
            scope=scope,
        )


class BackendNotAvailableError(DiagnosticError):
    """Raised by placeholder handlers until a scanner backend merges."""

    exit_code = 1

    def __init__(self, message: str, *, backend: str) -> None:
        super().__init__(
            message,
            code="backend-not-available",
            scope=backend,
        )


class OutputWriteError(DiagnosticError):
    """Raised when the CLI cannot persist EsriFootprint.json."""

    exit_code = 20

    def __init__(self, path: Path) -> None:
        del path
        super().__init__(
            "Could not save EsriFootprint.json at the requested output path.",
            code="output-write-failed",
            scope="output",
        )


class OutputExistsError(DiagnosticError):
    """Raised when an output file already exists and ``--force`` was not set."""

    exit_code = 20

    def __init__(self, path: Path) -> None:
        del path
        super().__init__(
            "Output file already exists; re-run with --force to overwrite it.",
            code="output-exists",
            scope="output",
        )


class SchemaValidationError(DiagnosticError):
    """Raised when an artifact fails schema validation."""

    exit_code = 30

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="schema-validation-failed",
            scope="schema",
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


def render_diagnostic(diagnostic: Diagnostic | CliDiagnostic) -> str:
    """Render a diagnostic without raw exceptions or stack traces."""

    scope = f" scope={diagnostic.scope}" if diagnostic.scope else ""
    return f"{diagnostic.severity}[{diagnostic.code}]{scope}: {diagnostic.message}"


def print_diagnostic(diagnostic: Diagnostic | CliDiagnostic) -> None:
    typer.echo(render_diagnostic(diagnostic), err=True)


def print_diagnostic_error(error: DiagnosticError) -> None:
    print_diagnostic(error.diagnostic)


def redact(value: str) -> str:
    redacted = value
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def maybe_write_crash_dump(exc: BaseException) -> Path | None:
    """Write a local redacted crash dump only when explicitly enabled."""

    if os.environ.get("HONUA_ESRI_ASSESS_CRASH_DUMPS") != "1":
        return None

    crash_dir = Path.home() / ".cache" / "honua-esri-assess" / "crashes"
    crash_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fd, raw_path = tempfile.mkstemp(
        prefix=f"crash-{timestamp}-",
        suffix=".json",
        dir=crash_dir,
        text=True,
    )
    path = Path(raw_path)
    payload = {
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "exceptionType": type(exc).__name__,
        "message": redact(str(exc)),
        "traceback": redact("".join(traceback.format_exception(exc))),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def handle_unexpected_error(exc: BaseException) -> None:
    dump_path = maybe_write_crash_dump(exc)
    typer.echo(
        "error[internal-error]: The command failed unexpectedly. "
        "Raw exception details were not printed.",
        err=True,
    )
    if dump_path is not None:
        typer.echo(
            f"Local diagnostic file: ~/.cache/honua-esri-assess/crashes/{dump_path.name}",
            err=True,
        )
    raise typer.Exit(1)


def diagnostics_as_dicts(diagnostics: tuple[Diagnostic, ...]) -> list[dict[str, Any]]:
    return [diagnostic.to_dict() for diagnostic in diagnostics]


__all__ = [
    "AssessmentError",
    "BackendNotAvailableError",
    "CliDiagnostic",
    "DIAGNOSTIC_CODES",
    "Diagnostic",
    "DiagnosticError",
    "OutputWriteError",
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
    "SchemaValidationError",
    "ServerApiError",
    "ServerAuthError",
    "ServerConnectionError",
    "ServerError",
    "ServerForbiddenError",
    "ServerNotFoundError",
    "ServerRateLimitedError",
    "ServerSchemaError",
    "diagnostics_as_dicts",
    "handle_unexpected_error",
    "maybe_write_crash_dump",
    "print_diagnostic",
    "print_diagnostic_error",
    "redact",
    "render_diagnostic",
    "render_error",
    "sanitize_message",
]
