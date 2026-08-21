"""Stable public contracts for Honua migration tooling."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .contracts import (
    EXIT_APPLY_REFUSED,
    EXIT_BAD_ARGUMENTS,
    EXIT_INPUT_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_PARTIAL,
    EXIT_REMOTE_ERROR,
    EXIT_SAFETY_REFUSAL,
    EXIT_SUCCESS,
    EXIT_UNAVAILABLE,
    EXIT_VALIDATION_ERROR,
    Diagnostic,
    EngineReport,
    MigrationError,
    MigrationPlan,
    MigrationResult,
    MigrationRun,
    Readiness,
    ReconciliationResult,
    SafetyMode,
    plan_digest,
)
from .contract_validation import (
    assert_artifact_safe,
    load_contract_schema,
    validate_contract,
)

try:
    __version__ = version("honua-migrate")
except PackageNotFoundError:
    __version__ = "0.7.1"

__all__ = [
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
    "__version__",
    "assert_artifact_safe",
    "load_contract_schema",
    "plan_digest",
    "validate_contract",
]
