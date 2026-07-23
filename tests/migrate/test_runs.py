"""Acceptance tests for durable and resumable migration runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from honua_migrate.contracts import (
    EXIT_APPLY_REFUSED,
    EXIT_PARTIAL,
    EXIT_REMOTE_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_VALIDATION_ERROR,
    MigrationError,
    MigrationPlan,
)
from honua_migrate.runs import ExecutionReceipt, RunStore, resume_run, start_run


class FakeExecutor:
    """Deterministic in-memory executor with separately controlled GET results."""

    def __init__(
        self,
        *,
        inspect_results: Mapping[str, ExecutionReceipt | None] | None = None,
        interrupt_on: str | None = None,
    ) -> None:
        self.inspect_results = dict(inspect_results or {})
        self.interrupt_on = interrupt_on
        self.execute_calls: list[str] = []
        self.inspect_calls: list[str] = []

    def inspect(self, action: Mapping[str, Any]) -> ExecutionReceipt | None:
        action_id = str(action["id"])
        self.inspect_calls.append(action_id)
        return self.inspect_results.get(action_id)

    def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
        action_id = str(action["id"])
        self.execute_calls.append(action_id)
        if self.interrupt_on == action_id:
            raise InterruptedError
        return ExecutionReceipt(
            job_id=f"job-{action_id}", evidence={"action": action_id}
        )


def _plan(path: Path, *actions: dict[str, Any]) -> dict[str, Any]:
    payload = MigrationPlan(id="plan-1", service="fake", actions=actions).to_dict()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_start_persists_bound_redacted_run_and_refuses_clobber(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    plan = _plan(plan_path, {"id": "copy", "write": True, "idempotent": True})
    executor = FakeExecutor()

    result = start_run(
        plan_path,
        run_path,
        executor,
        acknowledged=True,
        config={
            "endpoint": "https://alice:pw@example.test/api?key=raw#fragment",
            "password": "do-not-persist",
            "header": "Bearer do-not-persist",
            "nested": {"credential": "do-not-persist", "batch": 10},
        },
    )

    persisted = json.loads(run_path.read_text(encoding="utf-8"))
    assert persisted == result
    assert persisted["plan_id"] == plan["id"]
    assert persisted["plan_digest"] == plan["plan_digest"]
    assert persisted["config"] == {
        "endpoint": "https://example.test/api",
        "header": "[redacted]",
        "nested": {"batch": 10},
    }
    assert persisted["job_ids"] == ["job-copy"]
    assert persisted["checkpoints"][0]["status"] == "succeeded"
    assert persisted["outcome"] == "succeeded"
    assert "do-not-persist" not in run_path.read_text(encoding="utf-8")

    with pytest.raises(MigrationError) as caught:
        start_run(plan_path, run_path, FakeExecutor(), acknowledged=True)
    assert caught.value.exit_code == EXIT_APPLY_REFUSED


def test_acknowledgement_precedes_run_creation_and_target_mutation(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "copy", "write": True})
    executor = FakeExecutor()

    with pytest.raises(MigrationError) as caught:
        start_run(plan_path, run_path, executor)

    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert executor.execute_calls == []
    assert not run_path.exists()


def test_read_only_plan_can_run_without_acknowledgement(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "inspect", "write": False})
    executor = FakeExecutor()

    result = start_run(plan_path, run_path, executor)

    assert executor.execute_calls == ["inspect"]
    assert result["safety_mode"] == "read-only"


def test_resume_get_confirms_incomplete_write_without_ack_or_requeue(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(
        plan_path,
        {"id": "complete", "write": True},
        {"id": "uncertain", "write": True},
    )
    interrupted = FakeExecutor(interrupt_on="uncertain")
    with pytest.raises(MigrationError) as caught:
        start_run(plan_path, run_path, interrupted, acknowledged=True)
    assert caught.value.exit_code == EXIT_PARTIAL
    assert interrupted.execute_calls == ["complete", "uncertain"]

    recovery = FakeExecutor(
        inspect_results={
            "uncertain": ExecutionReceipt(
                job_id="remote-job", evidence={"observed": "complete"}
            )
        }
    )
    result = resume_run(plan_path, run_path, recovery)

    assert recovery.inspect_calls == ["uncertain"]
    assert recovery.execute_calls == []
    assert result["job_ids"] == ["job-complete", "remote-job"]
    assert result["outcome"] == "succeeded"


def test_resume_refuses_ambiguous_non_idempotent_replay(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "create", "write": True, "idempotent": False})
    with pytest.raises(MigrationError):
        start_run(
            plan_path,
            run_path,
            FakeExecutor(interrupt_on="create"),
            acknowledged=True,
        )
    recovery = FakeExecutor()

    with pytest.raises(MigrationError) as caught:
        resume_run(plan_path, run_path, recovery, acknowledged=True)

    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert recovery.inspect_calls == ["create"]
    assert recovery.execute_calls == []


@pytest.mark.parametrize(
    "replacement",
    [
        {"action_id": "create", "write": True, "idempotent": False, "status": "failed"},
        {"action_id": "create", "write": False, "idempotent": False, "status": "started"},
        {"action_id": "unknown", "write": True, "idempotent": False, "status": "started"},
    ],
)
def test_resume_rejects_ambiguous_or_mismatched_checkpoints(
    tmp_path: Path, replacement: dict[str, Any]
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "create", "write": True, "idempotent": False})
    with pytest.raises(MigrationError):
        start_run(
            plan_path,
            run_path,
            FakeExecutor(interrupt_on="create"),
            acknowledged=True,
        )
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["checkpoints"] = [replacement]
    run_path.write_text(json.dumps(run), encoding="utf-8")
    executor = FakeExecutor()

    with pytest.raises(MigrationError) as caught:
        resume_run(plan_path, run_path, executor, acknowledged=True)

    assert caught.value.exit_code == EXIT_VALIDATION_ERROR
    assert executor.execute_calls == []


def test_resume_rejects_duplicate_checkpoints(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "create", "write": True, "idempotent": False})
    with pytest.raises(MigrationError):
        start_run(
            plan_path,
            run_path,
            FakeExecutor(interrupt_on="create"),
            acknowledged=True,
        )
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["checkpoints"] = [run["checkpoints"][0], run["checkpoints"][0]]
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(MigrationError) as caught:
        resume_run(plan_path, run_path, FakeExecutor(), acknowledged=True)

    assert caught.value.exit_code == EXIT_VALIDATION_ERROR


def test_run_lease_refuses_concurrent_resume_before_remote_io(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "upsert", "write": True, "idempotent": True})
    with pytest.raises(MigrationError):
        start_run(
            plan_path,
            run_path,
            FakeExecutor(interrupt_on="upsert"),
            acknowledged=True,
        )
    executor = FakeExecutor()

    with RunStore(run_path).lease():
        with pytest.raises(MigrationError) as caught:
            resume_run(plan_path, run_path, executor, acknowledged=True)

    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert executor.inspect_calls == []
    assert executor.execute_calls == []


def test_run_lease_refuses_symlink_without_touching_target_or_executor(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    lock_path = tmp_path / ".run.json.lock"
    target = tmp_path / "outside.txt"
    _plan(plan_path, {"id": "copy", "write": True})
    target.write_text("sentinel", encoding="utf-8")
    try:
        lock_path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    executor = FakeExecutor()

    with pytest.raises(MigrationError) as caught:
        start_run(plan_path, run_path, executor, acknowledged=True)

    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert target.read_text(encoding="utf-8") == "sentinel"
    assert executor.execute_calls == []
    assert not run_path.exists()


def test_run_lease_refuses_non_regular_path_before_remote_io(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    lock_path = tmp_path / ".run.json.lock"
    _plan(plan_path, {"id": "copy", "write": True})
    lock_path.mkdir()
    executor = FakeExecutor()

    with pytest.raises(MigrationError) as caught:
        start_run(plan_path, run_path, executor, acknowledged=True)

    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert executor.execute_calls == []
    assert not run_path.exists()


def test_resume_rejects_later_only_checkpoint_and_inconsistent_outcome(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(
        plan_path,
        {"id": "first", "write": True},
        {"id": "second", "write": True},
    )
    with pytest.raises(MigrationError):
        start_run(
            plan_path,
            run_path,
            FakeExecutor(interrupt_on="second"),
            acknowledged=True,
        )
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["checkpoints"] = [run["checkpoints"][1]]
    run["job_ids"] = []
    run["outcome"] = "pending"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    executor = FakeExecutor()

    with pytest.raises(MigrationError) as caught:
        resume_run(plan_path, run_path, executor, acknowledged=True)

    assert caught.value.exit_code == EXIT_VALIDATION_ERROR
    assert executor.execute_calls == []


def test_resume_rejects_job_ids_not_represented_by_ordered_checkpoints(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "first", "write": True, "idempotent": True})
    start_run(plan_path, run_path, FakeExecutor(), acknowledged=True)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["outcome"] = "running"
    run["job_ids"] = ["unrepresented-job"]
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(MigrationError) as caught:
        resume_run(plan_path, run_path, FakeExecutor(), acknowledged=True)

    assert caught.value.exit_code == EXIT_VALIDATION_ERROR


def test_idempotent_requeue_still_requires_fresh_acknowledgement(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "upsert", "write": True, "idempotent": True})
    with pytest.raises(MigrationError):
        start_run(
            plan_path,
            run_path,
            FakeExecutor(interrupt_on="upsert"),
            acknowledged=True,
        )
    recovery = FakeExecutor()

    with pytest.raises(MigrationError) as caught:
        resume_run(plan_path, run_path, recovery)
    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert recovery.execute_calls == []

    result = resume_run(plan_path, run_path, recovery, acknowledged=True)
    assert recovery.inspect_calls == ["upsert", "upsert"]
    assert recovery.execute_calls == ["upsert"]
    assert result["outcome"] == "succeeded"


def test_completed_non_idempotent_run_fails_safely_without_replay(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "create", "write": True, "idempotent": False})
    start_run(plan_path, run_path, FakeExecutor(), acknowledged=True)
    recovery = FakeExecutor()

    with pytest.raises(MigrationError) as caught:
        resume_run(plan_path, run_path, recovery, acknowledged=True)

    assert caught.value.exit_code == EXIT_APPLY_REFUSED
    assert recovery.execute_calls == []
    assert recovery.inspect_calls == []


def test_resume_refuses_changed_nonsecret_configuration(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "inspect", "write": False})
    start_run(plan_path, run_path, FakeExecutor(), config={"batch": 10})

    with pytest.raises(MigrationError) as caught:
        resume_run(
            plan_path,
            run_path,
            FakeExecutor(),
            config={"batch": 20},
        )

    assert caught.value.exit_code == EXIT_VALIDATION_ERROR


def test_adapter_errors_and_unsafe_job_ids_never_cross_core_boundary(
    tmp_path: Path,
) -> None:
    secret = "https://alice:pw@example.test/jobs?token=topsecret"

    class LeakyErrorExecutor(FakeExecutor):
        def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
            self.execute_calls.append(str(action["id"]))
            raise MigrationError(f"adapter response: {secret}", exit_code=EXIT_REMOTE_ERROR)

    class LeakyJobExecutor(FakeExecutor):
        def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
            self.execute_calls.append(str(action["id"]))
            return ExecutionReceipt(job_id=secret)

    for name, executor in (
        ("error", LeakyErrorExecutor()),
        ("job", LeakyJobExecutor()),
    ):
        plan_path = tmp_path / f"{name}-plan.json"
        run_path = tmp_path / f"{name}-run.json"
        _plan(plan_path, {"id": "copy", "write": True})

        with pytest.raises(MigrationError) as caught:
            start_run(plan_path, run_path, executor, acknowledged=True)

        assert secret not in str(caught.value)
        assert "topsecret" not in run_path.read_text(encoding="utf-8")


def test_post_remote_checkpoint_write_failure_remains_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "copy", "write": True, "idempotent": False})
    original_save = RunStore.save
    save_calls = 0

    def fail_completed_checkpoint_once(
        store: RunStore, payload: Mapping[str, Any]
    ) -> None:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise MigrationError(
                "transient persistence failure",
                exit_code=EXIT_INPUT_ERROR,
            )
        original_save(store, payload)

    monkeypatch.setattr(RunStore, "save", fail_completed_checkpoint_once)
    executor = FakeExecutor()
    with pytest.raises(MigrationError):
        start_run(plan_path, run_path, executor, acknowledged=True)

    persisted = json.loads(run_path.read_text(encoding="utf-8"))
    assert persisted["outcome"] == "partial"
    assert persisted["checkpoints"][-1]["status"] == "started"
    assert persisted["job_ids"] == []
    assert executor.execute_calls == ["copy"]

    monkeypatch.setattr(RunStore, "save", original_save)
    recovery = FakeExecutor(
        inspect_results={"copy": ExecutionReceipt(job_id="remote-job")}
    )
    result = resume_run(plan_path, run_path, recovery)

    assert recovery.inspect_calls == ["copy"]
    assert recovery.execute_calls == []
    assert result["outcome"] == "succeeded"


@pytest.mark.parametrize("tamper", ["plan", "run"])
def test_resume_refuses_tampered_or_mismatched_plan_binding(
    tmp_path: Path, tamper: str
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, {"id": "inspect", "write": False})
    start_run(plan_path, run_path, FakeExecutor())
    if tamper == "plan":
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        payload["service"] = "other"
        plan_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        payload = json.loads(run_path.read_text(encoding="utf-8"))
        payload["plan_id"] = "other"
        payload["outcome"] = "partial"
        run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MigrationError) as caught:
        resume_run(plan_path, run_path, FakeExecutor())

    assert caught.value.exit_code == EXIT_VALIDATION_ERROR
    assert "other" not in str(caught.value)
