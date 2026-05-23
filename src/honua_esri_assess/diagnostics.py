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


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    target: str | None = None

    def __post_init__(self) -> None:
        if self.code not in DIAGNOSTIC_CODES:
            raise ValueError(
                f"Unknown diagnostic code {self.code!r}; "
                f"expected one of {sorted(DIAGNOSTIC_CODES)}"
            )

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"code": self.code, "message": self.message}
        if self.target is not None:
            out["target"] = self.target
        return out
