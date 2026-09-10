"""Coverage for the ArcGIS existing-app handoff artifact and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from typer.testing import CliRunner

from honua_migrate.contract_validation import validate_contract
from honua_migrate.services.arcgis import arcgis_app

runner = CliRunner()
SOURCE_URL = "https://arcgis.test/rest/services/Parcels/FeatureServer"
TARGET_URL = "https://honua.test/services/parcels/FeatureServer"


def _invoke(args: list[str], *, env: dict[str, str] | None = None):
    # A wide COLUMNS keeps Typer's error panel from wrapping the assertion
    # substrings used below across multiple lines.
    return runner.invoke(arcgis_app, args, env={"COLUMNS": "200", **(env or {})}, color=False)


def _plain(result) -> str:
    return click.unstyle(result.output)


def _plan(tmp_path: Path, *, layer_id: int = 7, table_name: str = "parcels") -> Path:
    path = tmp_path / f"plan-{layer_id}.json"
    result = _invoke(
        [
            "plan",
            SOURCE_URL,
            "--layer-id",
            str(layer_id),
            "--table-name",
            table_name,
            "--output",
            str(path),
        ]
    )
    assert result.exit_code == 0, result.output
    return path


def _manifest(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


_BASE_ARGS = [
    "--target-service-url",
    TARGET_URL,
    "--client-version",
    "4.29",
    "--exercised-rendering",
    "--exercised-query",
    "--exercised-popup",
    "--exercised-auth",
    "--source-change",
    "endpoint",
    "--import-outcome",
    "success",
    "--reconciliation-outcome",
    "success",
    "--retained-app-outcome",
    "success",
    "--customer-message",
    "Parcels now served from Honua.",
]

_READ_ONLY_ARGS = [
    "--mode",
    "read-only-coexistence",
    "--source-still-serving",
    "--baseline-evidence",
    "GET 200 on source FeatureServer",
    "--route-back-method",
    "revert client baseURL env var",
]

_CUTOVER_ARGS = [
    "--mode",
    "writable-cutover",
    "--write-authority",
    "target",
    "--quiescence-window",
    "2026-09-10T02:00Z/PT2H",
    "--divergence-limit",
    "0 rows",
]


def test_handoff_builds_scope_id_mapping_and_validates_contract(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(
        tmp_path, [{"plan": str(plan), "jobId": "job-1", "targetLayerId": 12}]
    )
    output = tmp_path / "handoff.json"

    result = _invoke(
        ["handoff", str(manifest), *_BASE_ARGS, *_READ_ONLY_ARGS, "--output", str(output)]
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    validate_contract("handoff", artifact)
    plan_artifact = json.loads(plan.read_text(encoding="utf-8"))

    assert artifact["kind"] == "arcgis-existing-app-handoff"
    assert artifact["runtime"] == "existing-esri-js-retained"
    assert artifact["mode"] == "read-only-coexistence"
    assert artifact["planIds"] == [plan_artifact["id"]]
    assert artifact["planDigests"] == [plan_artifact["plan_digest"]]
    assert artifact["jobIds"] == ["job-1"]
    assert artifact["scope"] == {"serviceUrls": [SOURCE_URL], "layerIds": [7]}
    assert artifact["idMapping"] == [
        {
            "sourceServiceUrl": SOURCE_URL,
            "sourceLayerId": 7,
            "tableName": "parcels",
            "targetServiceUrl": TARGET_URL,
            "targetLayerId": 12,
            "jobId": "job-1",
        }
    ]
    assert artifact["outcome"] == "success"
    assert artifact["baseline"] == {
        "sourceStillServing": True,
        "evidence": "GET 200 on source FeatureServer",
        "routeBackOperatorControlled": True,
        "routeBackMethod": "revert client baseURL env var",
    }
    assert "cutover" not in artifact


def test_handoff_reads_job_id_from_matching_apply_artifact(tmp_path):
    plan = _plan(tmp_path)
    apply_artifact = tmp_path / "apply.json"
    plan_id = json.loads(plan.read_text(encoding="utf-8"))["id"]
    apply_artifact.write_text(
        json.dumps({"kind": "apply", "planId": plan_id, "response": {"jobId": "job-9"}}),
        encoding="utf-8",
    )
    manifest = _manifest(
        tmp_path, [{"plan": str(plan), "apply": str(apply_artifact), "targetLayerId": 12}]
    )
    output = tmp_path / "handoff.json"

    result = _invoke(
        ["handoff", str(manifest), *_BASE_ARGS, *_READ_ONLY_ARGS, "--output", str(output)]
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["jobIds"] == ["job-9"]
    assert artifact["idMapping"][0]["jobId"] == "job-9"


def test_handoff_rejects_apply_artifact_bound_to_a_different_plan(tmp_path):
    plan = _plan(tmp_path)
    apply_artifact = tmp_path / "apply.json"
    apply_artifact.write_text(
        json.dumps({"kind": "apply", "planId": "arcgis-plan-other", "response": {}}),
        encoding="utf-8",
    )
    manifest = _manifest(
        tmp_path, [{"plan": str(plan), "apply": str(apply_artifact), "targetLayerId": 12}]
    )

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_READ_ONLY_ARGS,
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "does not match its plan" in _plain(result)


def test_handoff_rejects_both_job_id_and_apply_on_one_entry(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(
        tmp_path,
        [{"plan": str(plan), "apply": str(plan), "jobId": "job-1", "targetLayerId": 12}],
    )

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_READ_ONLY_ARGS,
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "must not set both" in _plain(result)


def test_handoff_rejects_manifest_entry_without_verified_target_layer_id(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan)}])

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_READ_ONLY_ARGS,
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "verified integer 'targetLayerId'" in _plain(result)


def test_handoff_two_layers_aggregate_dependency_closure(tmp_path):
    plan_a = _plan(tmp_path, layer_id=7, table_name="parcels")
    plan_b = _plan(tmp_path, layer_id=8, table_name="owners")
    manifest = _manifest(
        tmp_path,
        [
            {"plan": str(plan_a), "jobId": "job-1", "targetLayerId": 12},
            {"plan": str(plan_b), "jobId": "job-2", "targetLayerId": 13},
        ],
    )
    output = tmp_path / "handoff.json"

    result = _invoke(
        ["handoff", str(manifest), *_BASE_ARGS, *_READ_ONLY_ARGS, "--output", str(output)]
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["scope"] == {"serviceUrls": [SOURCE_URL], "layerIds": [7, 8]}
    assert sorted(artifact["jobIds"]) == ["job-1", "job-2"]
    assert len(artifact["planIds"]) == 2
    assert len(artifact["idMapping"]) == 2


def test_handoff_read_only_coexistence_requires_baseline_fields(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            "--mode",
            "read-only-coexistence",
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "requires proving the source still serves the baseline" in _plain(result)


def test_handoff_rejects_cutover_fields_under_read_only_mode(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_READ_ONLY_ARGS,
            "--write-authority",
            "target",
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "only apply to --mode writable-cutover" in _plain(result)


def test_handoff_writable_cutover_requires_cutover_fields(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            "--mode",
            "writable-cutover",
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "requires declaring --write-authority" in _plain(result)


def test_handoff_writable_cutover_rejects_baseline_fields(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_CUTOVER_ARGS,
            "--baseline-evidence",
            "GET 200",
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "only apply to --mode read-only-coexistence" in _plain(result)


def test_handoff_source_change_none_cannot_combine_with_a_real_change(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])
    args = [arg for arg in _BASE_ARGS if arg not in {"--source-change", "endpoint"}]

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *args,
            "--source-change",
            "none",
            "--source-change",
            "endpoint",
            *_READ_ONLY_ARGS,
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "never a zero-change" in _plain(result)


def test_handoff_switchback_requires_divergence_handling(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_CUTOVER_ARGS,
            "--recovery-action",
            "endpoint-switchback",
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "target-only writes are never silently discarded" in _plain(result)


def test_handoff_switchback_with_divergence_handling_never_bare_discard(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])
    output = tmp_path / "handoff.json"

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_CUTOVER_ARGS,
            "--recovery-action",
            "endpoint-switchback",
            "--divergence-handling",
            "discarded-with-consent",
            "--output",
            str(output),
        ]
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["status"]["divergenceHandling"] == "discarded-with-consent"

    rejected = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_CUTOVER_ARGS,
            "--recovery-action",
            "endpoint-switchback",
            "--divergence-handling",
            "discarded",
            "--output",
            str(tmp_path / "handoff-bad.json"),
        ]
    )
    assert rejected.exit_code != 0
    assert "target-only writes are never silently discarded" in _plain(rejected)


@pytest.mark.parametrize(
    ("import_outcome", "reconciliation_outcome", "retained_app_outcome", "expected"),
    [
        ("success", "success", "success", "success"),
        ("success", "success", "unknown", "partial"),
        ("success", "partial", "success", "partial"),
        ("failed", "success", "success", "failed"),
        ("success", "success", "failed", "failed"),
    ],
)
def test_handoff_outcome_is_never_a_bare_feature_count_match(
    tmp_path, import_outcome, reconciliation_outcome, retained_app_outcome, expected
):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])
    output = tmp_path / "handoff.json"
    args = [
        arg
        for arg in _BASE_ARGS
        if arg
        not in {
            "--import-outcome",
            "success",
            "--reconciliation-outcome",
            "--retained-app-outcome",
        }
    ]

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *args,
            "--import-outcome",
            import_outcome,
            "--reconciliation-outcome",
            reconciliation_outcome,
            "--retained-app-outcome",
            retained_app_outcome,
            *_READ_ONLY_ARGS,
            "--output",
            str(output),
        ]
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["importOutcome"] == import_outcome
    assert artifact["reconciliationOutcome"] == reconciliation_outcome
    assert artifact["retainedAppOutcome"] == retained_app_outcome
    assert artifact["outcome"] == expected


def test_handoff_effort_requires_explicit_consent(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_READ_ONLY_ARGS,
            "--elapsed-seconds",
            "120",
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "--effort-consent" in _plain(result)


def test_handoff_effort_is_recorded_only_with_consent(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])
    output = tmp_path / "handoff.json"

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_READ_ONLY_ARGS,
            "--elapsed-seconds",
            "120",
            "--manual-interventions",
            "1",
            "--effort-consent",
            "--output",
            str(output),
        ]
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["effort"] == {
        "consent": True,
        "elapsedSeconds": 120.0,
        "manualInterventions": 1,
    }


def test_handoff_requires_force_to_overwrite_existing_output(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])
    output = tmp_path / "handoff.json"

    first = _invoke(
        ["handoff", str(manifest), *_BASE_ARGS, *_READ_ONLY_ARGS, "--output", str(output)]
    )
    assert first.exit_code == 0, first.output
    original = output.read_text(encoding="utf-8")

    refused = _invoke(
        ["handoff", str(manifest), *_BASE_ARGS, *_CUTOVER_ARGS, "--output", str(output)]
    )
    assert refused.exit_code != 0
    assert "--force" in _plain(refused)
    assert output.read_text(encoding="utf-8") == original


def test_handoff_rejects_unreviewed_manifest_plan_path(tmp_path):
    manifest = _manifest(
        tmp_path, [{"plan": str(tmp_path / "missing.json"), "targetLayerId": 12}]
    )

    result = _invoke(
        [
            "handoff",
            str(manifest),
            *_BASE_ARGS,
            *_READ_ONLY_ARGS,
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "Could not read the requested plan artifact" in _plain(result)


def test_handoff_target_service_url_rejects_credentials_and_query_strings(tmp_path):
    plan = _plan(tmp_path)
    manifest = _manifest(tmp_path, [{"plan": str(plan), "targetLayerId": 12}])
    non_target_args = _BASE_ARGS[2:]  # drop the leading --target-service-url pair

    result = _invoke(
        [
            "handoff",
            str(manifest),
            "--target-service-url",
            "https://user:pass@honua.test/services/parcels/FeatureServer",
            *non_target_args,
            *_READ_ONLY_ARGS,
            "--output",
            str(tmp_path / "handoff.json"),
        ]
    )

    assert result.exit_code != 0
    assert "credentials" in _plain(result)
