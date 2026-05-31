"""Tests for the ``honua_migrate.code.python`` CLI entrypoint (``honua-migrate``)."""

from __future__ import annotations

import json
from pathlib import Path

from honua_migrate.code.python._cli import main

# Buffer -> translatable (geometry.buffer); Erase -> manual-review
# (feature-class-vs-single-geometry semantics, honua-server#1228); Slope ->
# unsupported (no mapping).
SCRIPT = """
import arcpy
arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters")
arcpy.analysis.Erase("a", "b", "c")
arcpy.sa.Slope("dem")
"""

PYT = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.alias = "t"
        self.tools = [A]


class A(object):
    def __init__(self):
        self.label = "A tool"

    def getParameterInfo(self):
        return [arcpy.Parameter(name="in_features", displayName="In", datatype="GPFeatureLayer")]

    def execute(self, parameters, messages):
        arcpy.cartography.SimplifyPolygon("poly", "poly_s", "POINT_REMOVE", "10 Meters")
'''


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_scan_writes_classified_report(tmp_path: Path) -> None:
    script = _write(tmp_path, "wf.py", SCRIPT)
    out = tmp_path / "scan.json"

    rc = main(["scan", str(script), "--output", str(out)])

    assert rc == 0
    report = json.loads(out.read_text())
    statuses = {(c["tool"], c["status"]) for c in report["calls"]}
    assert ("Buffer", "translatable") in statuses
    assert ("Erase", "manual-review") in statuses
    assert ("Slope", "unsupported") in statuses
    assert report["translatableCount"] == 1
    assert report["manualReviewCount"] == 1
    assert report["unsupportedCount"] == 1
    # The classified Buffer call records its reconciled-server job id.
    buffer_call = next(c for c in report["calls"] if c["tool"] == "Buffer")
    assert buffer_call["jobProcessId"] == "geometry.buffer"


def test_cli_translate_emits_plan_and_evidence(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "wf.py", SCRIPT)
    plan_out = tmp_path / "plan.json"
    evidence_out = tmp_path / "evidence.json"

    rc = main(["translate", str(script), "--output", str(plan_out), "--evidence", str(evidence_out)])

    assert rc == 0
    plan = json.loads(plan_out.read_text())
    # The OGC plan translates every supported call (buffer + erase); coverage
    # gating to job-executable tools is reported in the evidence, not by
    # dropping translations.
    assert [t["processId"] for t in plan["translations"]] == ["buffer", "erase"]

    evidence = json.loads(evidence_out.read_text())
    assert evidence["schema"] == "honua.migration.arcpy.parity-evidence/v1"
    assert evidence["summary"]["translatableCalls"] == 1
    assert evidence["summary"]["manualReviewCalls"] == 1
    assert evidence["summary"]["unsupportedCalls"] == 1

    captured = capsys.readouterr()
    assert "coverage:" in captured.err


def test_cli_run_dry_run_emits_only_job_executable_payloads(tmp_path: Path) -> None:
    script = _write(tmp_path, "wf.py", SCRIPT)
    out = tmp_path / "run.json"

    rc = main(["run", str(script), "--server", "http://example.test", "--dry-run", "--output", str(out)])

    assert rc == 0
    result = json.loads(out.read_text())
    assert result["dryRun"] is True
    # Only the job-executable Buffer is queued to run; Erase is skipped.
    assert [e["processId"] for e in result["executions"]] == ["buffer"]
    assert [e["jobProcessId"] for e in result["executions"]] == ["geometry.buffer"]
    assert "arcpy.analysis.Erase" in result["skipped"]


def test_cli_pyt_parses_toolbox(tmp_path: Path) -> None:
    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"
    evidence = tmp_path / "tb_evidence.json"

    rc = main(["pyt", str(toolbox), "--output", str(out), "--evidence", str(evidence)])

    assert rc == 0
    parsed = json.loads(out.read_text())
    assert parsed["label"] == "T"
    assert [t["className"] for t in parsed["tools"]] == ["A"]
    assert [x["processId"] for x in parsed["tools"][0]["plan"]["translations"]] == ["simplify"]

    agg = json.loads(evidence.read_text())
    assert agg["summary"]["coveragePercent"] == 100.0


def test_cli_pyt_binary_toolbox_reports_stub(tmp_path: Path, capsys) -> None:
    binary = tmp_path / "legacy.atbx"
    binary.write_bytes(b"\x00binary\x00")

    rc = main(["pyt", str(binary)])

    assert rc == 3
    assert "not implemented" in capsys.readouterr().err


def test_cli_run_executes_via_mock_transport(tmp_path: Path, monkeypatch) -> None:
    import httpx

    import honua_sdk
    from honua_sdk import HonuaClient

    script = _write(tmp_path, "wf.py", SCRIPT)
    out = tmp_path / "run.json"

    def handler(request: httpx.Request) -> httpx.Response:
        process_id = request.url.path.split("/")[-2]
        return httpx.Response(200, json={"processID": process_id, "status": "accepted"})

    def fake_client(base_url, *args, **kwargs):
        return HonuaClient(base_url, transport=httpx.MockTransport(handler))

    # The CLI imports HonuaClient lazily from the top-level package.
    monkeypatch.setattr(honua_sdk, "HonuaClient", fake_client)

    rc = main(["run", str(script), "--server", "http://example.test", "--output", str(out)])

    assert rc == 0
    result = json.loads(out.read_text())
    assert [e["processId"] for e in result["executions"]] == ["buffer"]
    assert result["executions"][0]["result"]["status"] == "accepted"
    assert "arcpy.analysis.Erase" in result["skipped"]


def test_cli_run_with_no_job_executable_calls_reports_skips(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "manual.py", 'import arcpy\narcpy.analysis.Erase("a", "b", "c")\n')
    out = tmp_path / "run.json"

    rc = main(["run", str(script), "--server", "http://example.test", "--output", str(out)])

    assert rc == 0
    result = json.loads(out.read_text())
    assert result["executions"] == []
    assert "arcpy.analysis.Erase" in result["skipped"]
    assert "no translatable" in capsys.readouterr().err


def test_cli_scan_reports_syntax_error_exit_code(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "bad.py", "import arcpy\narcpy.analysis.Buffer(")

    rc = main(["scan", str(script)])

    assert rc == 2
    assert "syntax error" in capsys.readouterr().err


def test_cli_translate_reports_syntax_error_and_emits_no_plan(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "bad.py", "import arcpy\narcpy.analysis.Buffer(")
    plan_out = tmp_path / "plan.json"
    evidence_out = tmp_path / "evidence.json"

    rc = main(["translate", str(script), "--output", str(plan_out), "--evidence", str(evidence_out)])

    assert rc == 2
    captured = capsys.readouterr()
    assert "syntax error" in captured.err
    # On a syntax error no plan/evidence/coverage is emitted.
    assert not plan_out.exists()
    assert not evidence_out.exists()
    assert "coverage:" not in captured.err
    assert captured.out == ""
