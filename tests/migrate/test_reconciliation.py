"""Tests for portable source-target reconciliation evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from honua_migrate.contracts import (
    EXIT_APPLY_REFUSED,
    EXIT_VALIDATION_ERROR,
    MigrationError,
    MigrationPlan,
    MigrationRun,
    SafetyMode,
)
from honua_migrate.runs import ExecutionReceipt, start_run
from honua_migrate.runs.reconciliation import (
    reconcile_run,
    reconcile_snapshots,
    write_reconciliation,
)



class SnapshotExecutor:
    def inspect(self, action: Mapping[str, Any]) -> ExecutionReceipt | None:
        return None

    def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
        return ExecutionReceipt()


def _snapshot() -> dict[str, object]:
    return {
        "counts": {"roads": 2},
        "schemas": {"roads": {"id": "integer", "name": "string"}},
        "extents": {"roads": [0, 0, 10, 10]},
        "samples": [{"id": 1}, {"id": 2}],
        "relationships": [{"from": "roads", "to": "owners"}],
        "metadata": {"title": "Roads", "owner": "Migration team"},
    }


def test_reconcile_checks_all_categories_and_supported_metadata() -> None:
    source = _snapshot()
    target = _snapshot()
    target["samples"] = [{"id": 2}, {"id": 1}]
    target["supported_metadata"] = ["title"]

    result = reconcile_snapshots("run-1", source, target)

    assert result["status"] == "matched"
    assert [check["name"] for check in result["checks"]] == [
        "counts",
        "schemas",
        "extents",
        "samples",
        "relationships",
        "metadata",
    ]
    assert all(check["status"] == "matched" for check in result["checks"])
    metadata = result["checks"][-1]
    assert metadata["source"] == {"title": "Roads"}
    assert metadata["target"] == {"title": "Roads"}
    assert metadata["evidence"] == [{"unsupported_fields": ["owner"]}]


def test_reconcile_reports_mismatch_before_partial_categories() -> None:
    source = _snapshot()
    target = _snapshot()
    target["counts"] = {"roads": 1}
    del target["relationships"]
    target["supported_metadata"] = ["title", "owner"]

    result = reconcile_snapshots("run-1", source, target)

    assert result["status"] == "mismatched"
    statuses = {check["name"]: check["status"] for check in result["checks"]}
    assert statuses["counts"] == "mismatched"
    assert statuses["relationships"] == "skipped"


def test_missing_snapshot_categories_produce_partial_result() -> None:
    result = reconcile_snapshots(
        "run-1",
        {"counts": 1},
        {"counts": 1},
    )

    assert result["status"] == "partial"
    assert result["checks"][0]["status"] == "matched"
    assert all(check["status"] == "skipped" for check in result["checks"][1:])


def test_reconciliation_artifact_is_atomic_and_no_clobber(tmp_path: Path) -> None:
    output = tmp_path / "reconciliation.json"
    payload = reconcile_snapshots("run-1", {}, {})
    write_reconciliation(output, payload)
    original = output.read_text(encoding="utf-8")

    with pytest.raises(MigrationError) as caught:
        write_reconciliation(output, payload)

    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert output.read_text(encoding="utf-8") == original
    assert json.loads(original)["run_id"] == "run-1"


def test_reconcile_run_requires_success_and_bound_snapshots(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    source_path = tmp_path / "source.json"
    target_path = tmp_path / "target.json"
    output_path = tmp_path / "result.json"
    plan = MigrationPlan(
        id="plan-1",
        service="fake",
        actions=({"id": "inspect", "write": False},),
    ).to_dict()
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    run = start_run(plan_path, run_path, SnapshotExecutor())
    binding = {
        "run_id": run["id"],
        "plan_id": run["plan_id"],
        "plan_digest": run["plan_digest"],
        "service": run["service"],
    }
    snapshot = {**_snapshot(), **binding, "supported_metadata": ["title", "owner"]}
    source_path.write_text(json.dumps(snapshot), encoding="utf-8")
    target_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = reconcile_run(run_path, source_path, target_path, output_path)

    assert result["status"] == "matched"


def test_reconcile_run_refuses_mismatched_snapshot_identity(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    source_path = tmp_path / "source.json"
    target_path = tmp_path / "target.json"
    output_path = tmp_path / "result.json"
    plan = MigrationPlan(id="plan-1", service="fake", actions=()).to_dict()
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    run = start_run(plan_path, run_path, SnapshotExecutor())
    snapshot = {
        "run_id": run["id"],
        "plan_id": run["plan_id"],
        "plan_digest": run["plan_digest"],
        "service": run["service"],
        "supported_metadata": [],
    }
    source_path.write_text(json.dumps(snapshot), encoding="utf-8")
    snapshot["plan_id"] = "different-plan"
    target_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(MigrationError) as caught:
        reconcile_run(run_path, source_path, target_path, output_path)

    assert caught.value.exit_code == EXIT_VALIDATION_ERROR
    assert not output_path.exists()


def test_reconcile_run_refuses_incomplete_run_before_reading_snapshots(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    missing_source = tmp_path / "source.json"
    missing_target = tmp_path / "target.json"
    output_path = tmp_path / "result.json"
    plan = MigrationPlan(
        id="plan-1",
        service="fake",
        actions=({"id": "copy", "write": True},),
    ).to_dict()
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(MigrationError):
        start_run(
            plan_path,
            run_path,
            SnapshotExecutor(),
            acknowledged=False,
        )

    # Create a canonical pending artifact without making any target request.
    pending = MigrationRun(
        id="plan-1-run",
        plan_id=plan["id"],
        plan_digest=plan["plan_digest"],
        service=plan["service"],
        safety_mode=SafetyMode.APPLY,
    ).to_dict()
    run_path.write_text(json.dumps(pending), encoding="utf-8")

    with pytest.raises(MigrationError) as caught:
        reconcile_run(run_path, missing_source, missing_target, output_path)

    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert not output_path.exists()
