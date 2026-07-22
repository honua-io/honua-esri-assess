"""Versioned, dependency-free contracts shared by migration command modules.

The contracts deliberately use JSON-compatible primitives so services can emit
them without coupling to a transport, database, or telemetry implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

CONTRACT_VERSION = "v1"
EXIT_SUCCESS = 0
EXIT_INTERNAL_ERROR = 1
EXIT_BAD_ARGUMENTS = 2
EXIT_UNAVAILABLE = 4
EXIT_APPLY_REFUSED = 40


class SafetyMode(str, Enum):
    """The permission level requested by a migration operation."""

    READ_ONLY = "read-only"
    PLAN = "plan"
    APPLY = "apply"


@dataclass(frozen=True)
class Diagnostic:
    """A machine-readable migration diagnostic without secret-bearing fields."""

    code: str
    message: str
    severity: str = "error"
    scope: str | None = None


@dataclass(frozen=True)
class MigrationPlan:
    """A reproducible, reviewable migration plan."""

    id: str
    service: str
    actions: tuple[dict[str, Any], ...]
    contract_version: str = CONTRACT_VERSION
    safety_mode: SafetyMode = SafetyMode.PLAN

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["safety_mode"] = self.safety_mode.value
        return value


@dataclass(frozen=True)
class MigrationRun:
    """An execution attempt associated with a plan."""

    id: str
    plan_id: str
    service: str
    safety_mode: SafetyMode
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["safety_mode"] = self.safety_mode.value
        return value


@dataclass(frozen=True)
class MigrationResult:
    """The result of a read, plan, or apply command."""

    status: str
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MigrationError(Exception):
    """A safe CLI error with a stable process exit status."""

    def __init__(self, message: str, *, exit_code: int = EXIT_UNAVAILABLE) -> None:
        super().__init__(message)
        self.exit_code = exit_code
