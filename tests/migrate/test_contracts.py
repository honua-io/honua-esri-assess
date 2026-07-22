"""Shared migration contract and safety tests."""

from __future__ import annotations

import json

import pytest

from honua_migrate import (
    EXIT_INPUT_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_PARTIAL,
    EXIT_REMOTE_ERROR,
    EXIT_SAFETY_REFUSAL,
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
    assert_artifact_safe,
    load_contract_schema,
    plan_digest,
    validate_contract,
)


def test_exit_code_families_are_distinguishable() -> None:
    codes = {
        EXIT_INPUT_ERROR,
        EXIT_VALIDATION_ERROR,
        EXIT_PARTIAL,
        EXIT_REMOTE_ERROR,
        EXIT_INTERNAL_ERROR,
        EXIT_SAFETY_REFUSAL,
    }
    assert len(codes) == 6


def test_plan_digest_is_deterministic_and_detects_tampering() -> None:
    plan = MigrationPlan(
        id="plan-1", service="arcgis", actions=({"layer": 3, "kind": "copy"},)
    )
    first = plan.to_dict()
    second = plan.to_dict()
    assert first == second
    assert plan.verify(first)
    assert first["plan_digest"] == plan_digest(
        {key: value for key, value in first.items() if key != "plan_digest"}
    )
    first["actions"][0]["layer"] = 4
    assert not plan.verify(first)


def test_every_packaged_contract_schema_is_draft_2020_12() -> None:
    for name in ("diagnostic", "plan", "report", "reconciliation", "result", "run"):
        schema = load_contract_schema(name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert "/migrate/v1/" in schema["$id"]


def test_common_contract_instances_validate() -> None:
    warning = Diagnostic(code="manual-review", message="Review one mapping.", severity="warning")
    report = EngineReport(
        engine="python",
        readiness=Readiness.ASSISTED,
        automated=({"kind": "buffer"},),
        manual=({"kind": "kriging"},),
        warnings=(warning,),
        evidence=({"source": "workflow.py", "count": 2},),
    )
    plan = MigrationPlan(id="plan-1", service="python", actions=({"kind": "buffer"},))
    plan_payload = plan.to_dict()
    run = MigrationRun(
        id="run-1",
        plan_id="plan-1",
        plan_digest=plan_payload["plan_digest"],
        service="python",
        safety_mode=SafetyMode.APPLY,
        job_ids=("job-1",),
        outcome="succeeded",
    )
    result = MigrationResult(status="succeeded", run_id="run-1", report=report)
    reconciliation = ReconciliationResult(
        run_id="run-1",
        status="matched",
        checks=({"name": "row-count", "status": "matched", "source": 3, "target": 3},),
    )

    validate_contract("diagnostic", warning.to_dict())
    validate_contract("report", report.to_dict())
    validate_contract("plan", plan_payload)
    validate_contract("run", run.to_dict())
    validate_contract("result", result.to_dict())
    validate_contract("reconciliation", reconciliation.to_dict())


def test_run_v1_config_extension_is_backward_compatible_and_object_only() -> None:
    plan = MigrationPlan(id="plan-1", service="python", actions=())
    run = MigrationRun(
        id="run-1",
        plan_id="plan-1",
        plan_digest=plan.to_dict()["plan_digest"],
        service="python",
        safety_mode=SafetyMode.READ_ONLY,
    ).to_dict()
    del run["config"]
    validate_contract("run", run)

    run["config"] = ["not", "an", "object"]
    with pytest.raises(MigrationError):
        validate_contract("run", run)


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "value"},
        {"nested": {"accessTokenSecretReference": "env:TOKEN"}},
        {"url": "https://alice:secret@example.test/data"},
        {"url": "https://example.test/data?token=secret"},
        {"url": "https://example.test/data?f=json"},
        {"message": "Authorization: Bearer raw-token"},
    ],
)
def test_artifact_safety_rejects_credentials_and_url_secrets(payload: object) -> None:
    with pytest.raises(MigrationError) as caught:
        assert_artifact_safe(payload)
    assert caught.value.exit_code == EXIT_VALIDATION_ERROR
    assert "secret" not in str(caught.value).lower()
    assert "raw-token" not in str(caught.value)


def test_schema_and_semantic_errors_do_not_reflect_payload_values() -> None:
    payload = {
        "contract_version": "v1",
        "id": "plan",
        "plan_digest": "sha256:" + "0" * 64,
        "service": "arcgis",
        "safety_mode": "apply",
        "actions": [],
    }
    with pytest.raises(MigrationError) as caught:
        validate_contract("plan", payload)
    assert caught.value.exit_code == EXIT_VALIDATION_ERROR
    assert json.dumps(payload) not in str(caught.value)
