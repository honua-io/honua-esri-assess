"""End-to-end wiring of the read-only Admin-API usage/binding facet.

Exercises ``scan server --admin-usage``: the server catalog walk plus the
opt-in ``/admin/usagereports`` + ``/admin/data/items`` pull are stubbed with
``responses`` (GET-only), and the emitted ``EsriFootprint.json`` is asserted to
carry the usage-ranked ordering and per-dataset binding modes, to validate
against the v0.2 schema, and to never leak credentials drawn from the
data-store registrations.
"""

from __future__ import annotations

import json
from pathlib import Path

import responses
from typer.testing import CliRunner

from honua_esri_assess.cli import cli_app

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _register_server_catalog() -> None:
    responses.add(
        responses.GET,
        "https://fixture.local/server/rest/info",
        json={"currentVersion": 11.2},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://fixture.local/server/rest/services",
        json={"folders": [], "services": []},
        status=200,
    )


def _register_admin_endpoints() -> None:
    responses.add(
        responses.GET,
        "https://fixture.local/server/admin/usagereports",
        json=_fixture("admin-usagereports.json"),
        status=200,
    )
    responses.add(
        responses.GET,
        "https://fixture.local/server/admin/data/items",
        json=_fixture("admin-data-items.json"),
        status=200,
    )


def _run(output: Path, *extra: str):
    runner = CliRunner()
    return runner.invoke(
        cli_app,
        [
            "scan",
            "server",
            "--target",
            "https://fixture.local/server",
            "--token-env",
            "SERVER_TOKEN",
            "--output",
            str(output),
            "--validate",
            *extra,
        ],
        env={"SERVER_TOKEN": "top-secret-token"},
    )


@responses.activate
def test_admin_usage_emits_binding_plan_and_validates(tmp_path: Path) -> None:
    output = tmp_path / "EsriFootprint.json"
    _register_server_catalog()
    _register_admin_endpoints()
    result = _run(output, "--admin-usage")
    assert result.exit_code == 0, result.output

    footprint = json.loads(output.read_text(encoding="utf-8"))
    plan = footprint["server"]["bindingPlan"]

    # Usage-driven ordering (descending observed request volume).
    ranked = plan["usageRankedServices"]
    assert ranked[0]["service"] == "Parcels.MapServer"
    assert ranked[0]["rank"] == 1
    assert [s["rank"] for s in ranked] == sorted(s["rank"] for s in ranked)

    # Storage type from registrations -> binding-mode routing.
    by_id = {b["datasetId"]: b for b in plan["datasetBindings"]}
    assert by_id["/enterpriseDatabases/parcels_egdb"]["bindingMode"] == "federate"
    assert by_id["/cloudStores/imagery_s3"]["bindingMode"] == "connect-in-place"
    assert by_id["/fileShares/legacy_gdb"]["bindingMode"] == "materialize"
    assert by_id["/enterpriseDatabases/mystery_store"]["connectionKind"] == "unknown"


@responses.activate
def test_admin_usage_artifact_never_leaks_registration_credentials(
    tmp_path: Path,
) -> None:
    output = tmp_path / "EsriFootprint.json"
    _register_server_catalog()
    _register_admin_endpoints()
    result = _run(output, "--admin-usage")
    assert result.exit_code == 0, result.output

    raw = output.read_text(encoding="utf-8")
    # Secrets carried in the data/items registrations' info/connection blocks
    # (and the access token) must never reach the artifact — storage type only.
    for secret in (
        "top-secret-token",
        "topsecret-db-pw",
        "PASSWORD=",
        "connectionString",
        "AKIAEXAMPLE",
        "super-secret-key",
        "secret-future-conn",
        "sql.internal",
        "fileserver",
    ):
        assert secret not in raw


@responses.activate
def test_plain_server_scan_omits_binding_plan(tmp_path: Path) -> None:
    output = tmp_path / "EsriFootprint.json"
    _register_server_catalog()
    # No admin endpoints registered: --admin-usage is off, so the catalog walk
    # must not touch /admin and the artifact must be unchanged.
    result = _run(output)
    assert result.exit_code == 0, result.output

    footprint = json.loads(output.read_text(encoding="utf-8"))
    assert "bindingPlan" not in footprint["server"]
    assert not any("/admin" in call.request.url for call in responses.calls)


@responses.activate
def test_admin_usage_missing_scope_degrades_to_diagnostic(tmp_path: Path) -> None:
    output = tmp_path / "EsriFootprint.json"
    _register_server_catalog()
    responses.add(
        responses.GET,
        "https://fixture.local/server/admin/usagereports",
        json={"error": {"code": 403}},
        status=403,
    )
    responses.add(
        responses.GET,
        "https://fixture.local/server/admin/data/items",
        json={"error": {"code": 403}},
        status=403,
    )
    result = _run(output, "--admin-usage")
    # A token without admin scope degrades to a diagnostic; the scan still
    # produces a valid artifact, just without the binding plan.
    assert result.exit_code == 0, result.output
    footprint = json.loads(output.read_text(encoding="utf-8"))
    assert "bindingPlan" not in footprint["server"]
    combined = result.output + (result.stderr or "")
    assert "missing-permission" in combined
