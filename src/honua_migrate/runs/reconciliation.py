"""Deterministic comparison of source and target migration snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..contract_validation import assert_artifact_safe, validate_contract
from ..contracts import (
    EXIT_APPLY_REFUSED,
    EXIT_INPUT_ERROR,
    EXIT_VALIDATION_ERROR,
    MigrationError,
    ReconciliationResult,
)
from .orchestration import RunStore, _atomic_write_new, _serialized

_COMPARISONS = ("counts", "schemas", "extents", "samples", "relationships")
_ORDER_INSENSITIVE = frozenset({"samples", "relationships"})
_BINDING_FIELDS = ("run_id", "plan_id", "plan_digest", "service")


def load_snapshot(path: Path) -> dict[str, Any]:
    """Load a credential-free snapshot emitted by a service adapter."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(
            "Unable to read a reconciliation snapshot.",
            exit_code=EXIT_INPUT_ERROR,
        ) from exc
    if not isinstance(value, dict):
        raise MigrationError(
            "Reconciliation snapshot must be a JSON object.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    assert_artifact_safe(value)
    return value


def _ordered(value: Any) -> Any:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return value
    return sorted(
        value,
        key=lambda item: json.dumps(
            item, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ),
    )


def _compare(name: str, source: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    if name not in source or name not in target:
        return {
            "name": name,
            "status": "skipped",
            "warnings": [
                {
                    "code": "snapshot-category-missing",
                    "message": f"{name} was not present in both snapshots.",
                }
            ],
        }
    source_value = source[name]
    target_value = target[name]
    if name in _ORDER_INSENSITIVE:
        source_value = _ordered(source_value)
        target_value = _ordered(target_value)
    return {
        "name": name,
        "status": "matched" if source_value == target_value else "mismatched",
        "source": source_value,
        "target": target_value,
    }


def _compare_metadata(
    source: Mapping[str, Any], target: Mapping[str, Any]
) -> dict[str, Any]:
    source_metadata = source.get("metadata")
    target_metadata = target.get("metadata")
    supported = target.get("supported_metadata")
    if (
        not isinstance(source_metadata, Mapping)
        or not isinstance(target_metadata, Mapping)
        or not isinstance(supported, list)
        or not all(isinstance(item, str) for item in supported)
    ):
        return {
            "name": "metadata",
            "status": "skipped",
            "warnings": [
                {
                    "code": "metadata-capabilities-missing",
                    "message": "Supported metadata capabilities were not supplied.",
                }
            ],
        }
    supported_names = sorted(set(supported))
    source_supported = {
        name: source_metadata.get(name)
        for name in supported_names
        if name in source_metadata
    }
    target_supported = {
        name: target_metadata.get(name)
        for name in supported_names
        if name in target_metadata
    }
    result: dict[str, Any] = {
        "name": "metadata",
        "status": (
            "matched" if source_supported == target_supported else "mismatched"
        ),
        "source": source_supported,
        "target": target_supported,
    }
    unsupported = sorted(str(name) for name in source_metadata if name not in supported_names)
    if unsupported:
        result["warnings"] = [
            {
                "code": "metadata-unsupported",
                "message": "Some source metadata is not supported by the target.",
            }
        ]
        result["evidence"] = [{"unsupported_fields": unsupported}]
    return result


def reconcile_snapshots(
    run_id: str,
    source: Mapping[str, Any],
    target: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare all portable reconciliation categories deterministically."""

    assert_artifact_safe(source)
    assert_artifact_safe(target)
    checks = [*(_compare(name, source, target) for name in _COMPARISONS)]
    checks.append(_compare_metadata(source, target))
    statuses = {check["status"] for check in checks}
    if "failed" in statuses:
        status = "failed"
    elif "mismatched" in statuses:
        status = "mismatched"
    elif "skipped" in statuses:
        status = "partial"
    else:
        status = "matched"
    result = ReconciliationResult(
        run_id=run_id,
        status=status,
        checks=tuple(checks),
    ).to_dict()
    validate_contract("reconciliation", result)
    return result


def write_reconciliation(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically create a reconciliation artifact without clobbering one."""

    validate_contract("reconciliation", payload)
    try:
        _atomic_write_new(path, _serialized(payload))
    except FileExistsError as exc:
        raise MigrationError(
            "Reconciliation artifact already exists; choose a new output.",
            exit_code=EXIT_APPLY_REFUSED,
        ) from exc
    except OSError as exc:
        raise MigrationError(
            "Unable to create the reconciliation artifact.",
            exit_code=EXIT_INPUT_ERROR,
        ) from exc


def _validate_snapshot_binding(
    run: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> None:
    expected = {
        "run_id": run["id"],
        "plan_id": run["plan_id"],
        "plan_digest": run["plan_digest"],
        "service": run["service"],
    }
    if any(snapshot.get(field) != expected[field] for field in _BINDING_FIELDS):
        raise MigrationError(
            "Reconciliation snapshot does not match the migration run.",
            exit_code=EXIT_VALIDATION_ERROR,
        )


def reconcile_run(
    run_path: Path,
    source_path: Path,
    target_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Validate one run and write its source-target reconciliation result."""

    run = RunStore(run_path).load()
    if run["outcome"] != "succeeded":
        raise MigrationError(
            "Reconciliation requires a successfully completed migration run.",
            exit_code=EXIT_APPLY_REFUSED,
        )
    source = load_snapshot(source_path)
    target = load_snapshot(target_path)
    _validate_snapshot_binding(run, source)
    _validate_snapshot_binding(run, target)
    result = reconcile_snapshots(run["id"], source, target)
    write_reconciliation(output_path, result)
    return result


__all__ = [
    "load_snapshot",
    "reconcile_run",
    "reconcile_snapshots",
    "write_reconciliation",
]
