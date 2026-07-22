"""Tests for the stable unified CLI foundation."""

from __future__ import annotations

from typer.testing import CliRunner

from honua_migrate.app import cli_app
from honua_migrate.cli import main
from honua_migrate.contracts import EXIT_APPLY_REFUSED, EXIT_UNAVAILABLE, MigrationPlan


def test_root_help_exposes_the_migration_command_tree() -> None:
    result = CliRunner().invoke(cli_app, ["--help"], env={"COLUMNS": "160"})

    assert result.exit_code == 0
    for command in ("assess", "plan", "services", "content", "code", "apply", "reconcile"):
        assert command in result.output


def test_assess_nests_the_legacy_read_only_cli() -> None:
    result = CliRunner().invoke(cli_app, ["assess", "--help"], env={"COLUMNS": "160"})

    assert result.exit_code == 0
    assert "scan" in result.output
    assert "report" in result.output


def test_placeholders_are_explicit_and_safe() -> None:
    assert main(["plan", "create"]) == EXIT_UNAVAILABLE
    assert main(["apply", "plan"]) == EXIT_APPLY_REFUSED


def test_plan_contract_is_json_compatible_and_versioned() -> None:
    plan = MigrationPlan(id="plan-1", service="arcgis", actions=({"kind": "copy"},))

    assert plan.to_dict() == {
        "id": "plan-1",
        "service": "arcgis",
        "actions": ({"kind": "copy"},),
        "contract_version": "v1",
        "safety_mode": "plan",
    }
