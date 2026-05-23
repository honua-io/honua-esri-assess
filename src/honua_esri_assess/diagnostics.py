"""Typed, prospect-safe diagnostics surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

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
