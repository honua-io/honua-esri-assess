"""Canonical CLI commands for runtime-neutral migration runs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import typer

from ..contracts import (
    EXIT_APPLY_REFUSED,
    EXIT_INPUT_ERROR,
    EXIT_UNAVAILABLE,
    MigrationError,
)
from .orchestration import (
    ExecutionReceipt,
    MigrationExecutor,
    load_plan,
    resume_run,
    start_run,
)
from .reconciliation import reconcile_run

ExecutorFactory = Callable[[Mapping[str, Any]], MigrationExecutor]
_EXECUTORS: dict[str, ExecutorFactory] = {}


def register_executor(service: str, factory: ExecutorFactory) -> None:
    """Register a service-owned runtime adapter without coupling core orchestration."""

    _EXECUTORS[service] = factory


def _executor(service: str, config: Mapping[str, Any]) -> MigrationExecutor:
    factory = _EXECUTORS.get(service)
    if factory is None:
        raise MigrationError(
            "No execution adapter is installed for this migration service.",
            exit_code=EXIT_UNAVAILABLE,
        )
    try:
        return factory(config)
    except Exception as exc:
        raise MigrationError(
            "Unable to initialize the migration execution adapter.",
            exit_code=EXIT_UNAVAILABLE,
        ) from exc


class _LazyExecutor:
    """Resolve an adapter only when a bound run actually needs remote I/O."""

    def __init__(self, service: str, config: Mapping[str, Any]) -> None:
        self.service = service
        self.config = config
        self.delegate: MigrationExecutor | None = None

    def _get(self) -> MigrationExecutor:
        if self.delegate is None:
            self.delegate = _executor(self.service, self.config)
        return self.delegate

    def inspect(self, action: Mapping[str, Any]) -> ExecutionReceipt | None:
        return self._get().inspect(action)

    def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
        return self._get().execute(action)


def _config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(
            "Unable to read the migration configuration.",
            exit_code=EXIT_INPUT_ERROR,
        ) from exc
    if not isinstance(value, dict):
        raise MigrationError(
            "Migration configuration must be a JSON object.",
            exit_code=EXIT_INPUT_ERROR,
        )
    return value


def verify_plan_command(plan_path: Path) -> None:
    """Verify the schema and canonical digest of a plan artifact."""

    plan = load_plan(plan_path)
    typer.echo(json.dumps({"id": plan["id"], "plan_digest": plan["plan_digest"]}))


def apply_run_command(
    plan_path: Path,
    output: Path = typer.Option(..., "--output", help="New run artifact path."),
    config: Path | None = typer.Option(None, "--config", help="Runtime config JSON."),
    yes: bool = typer.Option(False, "--yes", help="Acknowledge target mutations."),
    run_id: str | None = typer.Option(None, "--run-id", help="Stable run identity."),
) -> None:
    """Execute an authenticated plan as a new durable run."""

    plan = load_plan(plan_path)
    if any(action.get("write", True) for action in plan["actions"]) and not yes:
        raise MigrationError(
            "Explicit acknowledgement is required before migration writes.",
            exit_code=EXIT_APPLY_REFUSED,
        )
    raw_config = _config(config)
    result = start_run(
        plan_path,
        output,
        _LazyExecutor(plan["service"], raw_config),
        config=raw_config,
        acknowledged=yes,
        run_id=run_id,
    )
    typer.echo(json.dumps({"run_id": result["id"], "outcome": result["outcome"]}))


def apply_resume_command(
    plan_path: Path,
    run_path: Path,
    config: Path | None = typer.Option(None, "--config", help="Runtime config JSON."),
    yes: bool = typer.Option(False, "--yes", help="Acknowledge target mutations."),
) -> None:
    """Inspect and resume an incomplete durable run."""

    plan = load_plan(plan_path)
    raw_config = _config(config)
    result = resume_run(
        plan_path,
        run_path,
        _LazyExecutor(plan["service"], raw_config),
        config=raw_config,
        acknowledged=yes,
    )
    typer.echo(json.dumps({"run_id": result["id"], "outcome": result["outcome"]}))


def reconcile_compare_command(
    run_path: Path,
    source: Path = typer.Option(..., "--source", help="Source snapshot JSON."),
    target: Path = typer.Option(..., "--target", help="Target snapshot JSON."),
    output: Path = typer.Option(..., "--output", help="New result artifact path."),
) -> None:
    """Compare portable source and target snapshots for a run."""

    result = reconcile_run(run_path, source, target, output)
    typer.echo(json.dumps({"run_id": result["run_id"], "status": result["status"]}))


__all__ = [
    "apply_resume_command",
    "apply_run_command",
    "reconcile_compare_command",
    "register_executor",
    "verify_plan_command",
]
