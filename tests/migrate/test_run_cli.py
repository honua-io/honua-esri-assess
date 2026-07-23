"""Tests for the canonical run and reconciliation CLI surface."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import honua_migrate.runs.cli as run_cli
from honua_migrate.app import cli_app
from honua_migrate.cli import main
from honua_migrate.contracts import (
    EXIT_APPLY_REFUSED,
    EXIT_REMOTE_ERROR,
    EXIT_UNAVAILABLE,
    MigrationError,
    MigrationPlan,
)
from honua_migrate.runs import ExecutionReceipt, start_run


def _plan(
    path: Path,
    *,
    service: str = "missing-adapter",
    idempotent: bool = False,
) -> None:
    payload = MigrationPlan(
        id="plan-1",
        service=service,
        actions=({"id": "copy", "write": True, "idempotent": idempotent},),
    ).to_dict()
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_canonical_commands_are_mounted_without_replacing_placeholders() -> None:
    runner = CliRunner()
    assert runner.invoke(cli_app, ["plan", "--help"]).exit_code == 0
    assert "verify" in runner.invoke(cli_app, ["plan", "--help"]).output
    assert "run" in runner.invoke(cli_app, ["apply", "--help"]).output
    assert "resume" in runner.invoke(cli_app, ["apply", "--help"]).output
    assert "compare" in runner.invoke(cli_app, ["reconcile", "--help"]).output
    assert main(["plan", "create"]) == EXIT_UNAVAILABLE
    assert main(["apply", "plan"]) == EXIT_APPLY_REFUSED


def test_plan_verify_and_apply_ack_preflight(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path)

    verified = CliRunner().invoke(cli_app, ["plan", "verify", str(plan_path)])
    assert verified.exit_code == 0
    assert json.loads(verified.output)["id"] == "plan-1"

    assert (
        main(["apply", "run", str(plan_path), "--output", str(run_path)])
        == EXIT_APPLY_REFUSED
    )
    assert not run_path.exists()

    assert (
        main(
            [
                "apply",
                "run",
                str(plan_path),
                "--output",
                str(run_path),
                "--yes",
            ]
        )
        == EXIT_UNAVAILABLE
    )
    assert json.loads(run_path.read_text(encoding="utf-8"))["outcome"] == "partial"


def test_existing_output_refuses_before_adapter_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, service="factory-must-not-run")
    run_path.write_text("existing", encoding="utf-8")
    factory_calls: list[dict[str, Any]] = []

    def factory(config: Mapping[str, Any]) -> Any:
        factory_calls.append(dict(config))
        raise AssertionError("factory should not run")

    monkeypatch.setitem(run_cli._EXECUTORS, "factory-must-not-run", factory)

    code = main(
        ["apply", "run", str(plan_path), "--output", str(run_path), "--yes"]
    )

    assert code == EXIT_APPLY_REFUSED
    assert factory_calls == []
    assert run_path.read_text(encoding="utf-8") == "existing"


def test_completed_non_idempotent_resume_refuses_before_adapter_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Executor:
        def inspect(self, action: Mapping[str, Any]) -> ExecutionReceipt | None:
            return None

        def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
            return ExecutionReceipt(job_id="job-1")

    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, service="not-installed")
    start_run(plan_path, run_path, Executor(), acknowledged=True)
    monkeypatch.delitem(run_cli._EXECUTORS, "not-installed", raising=False)

    code = main(["apply", "resume", str(plan_path), str(run_path), "--yes"])

    assert code == EXIT_APPLY_REFUSED


def test_unsafe_adapter_job_id_never_reaches_artifact_or_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "https://alice:pw@example.test/jobs?token=topsecret"

    class Executor:
        def inspect(self, action: Mapping[str, Any]) -> ExecutionReceipt | None:
            return None

        def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
            return ExecutionReceipt(job_id=secret)

    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, service="leaky")
    monkeypatch.setitem(run_cli._EXECUTORS, "leaky", lambda config: Executor())

    code = main(
        ["apply", "run", str(plan_path), "--output", str(run_path), "--yes"]
    )
    error = capsys.readouterr().err

    assert code == EXIT_REMOTE_ERROR
    assert secret not in error
    assert "topsecret" not in run_path.read_text(encoding="utf-8")


def test_unsafe_adapter_error_never_reaches_artifact_or_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "https://alice:pw@example.test/jobs?token=topsecret"

    class Executor:
        def inspect(self, action: Mapping[str, Any]) -> ExecutionReceipt | None:
            return None

        def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
            raise MigrationError(f"adapter failed at {secret}", exit_code=EXIT_REMOTE_ERROR)

    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, service="leaky-message")
    monkeypatch.setitem(
        run_cli._EXECUTORS, "leaky-message", lambda config: Executor()
    )

    code = main(
        ["apply", "run", str(plan_path), "--output", str(run_path), "--yes"]
    )
    error = capsys.readouterr().err

    assert code == EXIT_REMOTE_ERROR
    assert secret not in error
    assert "topsecret" not in run_path.read_text(encoding="utf-8")


def test_adapter_factory_errors_are_generic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "Bearer adapter-secret"

    def fail(config: Mapping[str, Any]) -> Any:
        raise RuntimeError(secret)

    plan_path = tmp_path / "plan.json"
    run_path = tmp_path / "run.json"
    _plan(plan_path, service="broken")
    monkeypatch.setitem(run_cli._EXECUTORS, "broken", fail)

    code = main(
        ["apply", "run", str(plan_path), "--output", str(run_path), "--yes"]
    )
    error = capsys.readouterr().err

    assert code == EXIT_UNAVAILABLE
    assert secret not in error
    assert run_path.exists()
    assert secret not in run_path.read_text(encoding="utf-8")
