"""Versioned, JSON-compatible contracts shared by migration engines."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

CONTRACT_VERSION = "v1"

# Stable CLI exit-code families. Existing values remain compatible with the
# assessment CLI while new callers can distinguish every failure class.
EXIT_SUCCESS = 0
EXIT_INTERNAL_ERROR = 1
EXIT_BAD_ARGUMENTS = 2
EXIT_INPUT_ERROR = EXIT_BAD_ARGUMENTS
EXIT_VALIDATION_ERROR = 3
EXIT_UNAVAILABLE = 4
EXIT_PARTIAL = 10
EXIT_REMOTE_ERROR = 20
EXIT_APPLY_REFUSED = 40
EXIT_SAFETY_REFUSAL = EXIT_APPLY_REFUSED


class SafetyMode(str, Enum):
    """The permission level requested by a migration operation."""

    READ_ONLY = "read-only"
    PLAN = "plan"
    APPLY = "apply"


class Readiness(str, Enum):
    """Overall readiness reported by a migration engine."""

    READY = "ready"
    ASSISTED = "assisted"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Diagnostic:
    """A machine-readable migration diagnostic without secret-bearing fields."""

    code: str
    message: str
    severity: str = "error"
    scope: str | None = None
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EngineReport:
    """Common readiness and evidence envelope emitted by every engine."""

    engine: str
    readiness: Readiness
    automated: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    manual: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    blocked: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    warnings: tuple[Diagnostic, ...] = field(default_factory=tuple)
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "readiness": self.readiness.value,
            "automated": list(self.automated),
            "manual": list(self.manual),
            "blocked": list(self.blocked),
            "warnings": [warning.to_dict() for warning in self.warnings],
            "evidence": list(self.evidence),
            "contract_version": self.contract_version,
        }


def plan_digest(payload: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 identity for an unsigned plan payload."""

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationPlan:
    """A reproducible, reviewable migration plan with an immutable identity."""

    id: str
    service: str
    actions: tuple[dict[str, Any], ...]
    contract_version: str = CONTRACT_VERSION
    safety_mode: SafetyMode = SafetyMode.PLAN

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "service": self.service,
            "actions": list(self.actions),
            "contract_version": self.contract_version,
            "safety_mode": self.safety_mode.value,
        }
        payload["plan_digest"] = plan_digest(payload)
        return payload

    def verify(self, payload: dict[str, Any]) -> bool:
        """Return whether a serialized plan matches its recorded digest."""

        recorded = payload.get("plan_digest")
        unsigned = {key: value for key, value in payload.items() if key != "plan_digest"}
        return isinstance(recorded, str) and recorded == plan_digest(unsigned)


@dataclass(frozen=True)
class MigrationRun:
    """A durable execution attempt associated with an immutable plan."""

    id: str
    plan_id: str
    plan_digest: str
    service: str
    safety_mode: SafetyMode
    job_ids: tuple[str, ...] = field(default_factory=tuple)
    checkpoints: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    outcome: str = "pending"
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "service": self.service,
            "safety_mode": self.safety_mode.value,
            "job_ids": list(self.job_ids),
            "checkpoints": list(self.checkpoints),
            "outcome": self.outcome,
            "contract_version": self.contract_version,
        }


@dataclass(frozen=True)
class MigrationResult:
    """The result of a read, plan, apply, or reconciliation command."""

    status: str
    run_id: str | None = None
    report: EngineReport | None = None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "status": self.status,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "artifacts": list(self.artifacts),
            "contract_version": self.contract_version,
        }
        if self.run_id is not None:
            value["run_id"] = self.run_id
        if self.report is not None:
            value["report"] = self.report.to_dict()
        return value


@dataclass(frozen=True)
class ReconciliationResult:
    """Source-to-target verification evidence for a migration run."""

    run_id: str
    status: str
    checks: tuple[dict[str, Any], ...]
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "checks": list(self.checks),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "contract_version": self.contract_version,
        }


class MigrationError(Exception):
    """A safe CLI error with a stable process exit status."""

    def __init__(self, message: str, *, exit_code: int = EXIT_UNAVAILABLE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


__all__ = [
    "CONTRACT_VERSION",
    "EXIT_APPLY_REFUSED",
    "EXIT_BAD_ARGUMENTS",
    "EXIT_INPUT_ERROR",
    "EXIT_INTERNAL_ERROR",
    "EXIT_PARTIAL",
    "EXIT_REMOTE_ERROR",
    "EXIT_SAFETY_REFUSAL",
    "EXIT_SUCCESS",
    "EXIT_UNAVAILABLE",
    "EXIT_VALIDATION_ERROR",
    "Diagnostic",
    "EngineReport",
    "MigrationError",
    "MigrationPlan",
    "MigrationResult",
    "MigrationRun",
    "Readiness",
    "ReconciliationResult",
    "SafetyMode",
    "plan_digest",
]
