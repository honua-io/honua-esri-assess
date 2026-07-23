from __future__ import annotations

import json
from typing import Any

import httpx

import pytest

from honua_migrate.code.python import (
    ArcPyJobError,
    ArcPyJobTimeoutError,
    ArcPyProcessRunner,
    UnsupportedArcPyCallError,
    scan_arcpy_source,
    translate_arcpy_source,
)
from honua_migrate.code.python.arcpy import ArcPyProcessExecution, ArcPyProcessTranslation


class _OgcProcessesClient:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            f"/ogc/processes/processes/{process_id}/execution",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def job(self, job_id: str) -> dict[str, Any]:
        response = self._client.get(f"/ogc/processes/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def job_results(self, job_id: str) -> dict[str, Any]:
        response = self._client.get(f"/ogc/processes/jobs/{job_id}/results")
        response.raise_for_status()
        return response.json()


class HonuaClient:
    """Test double for the public SDK protocol consumed by the runner."""

    def __init__(self, base_url: str, *, transport: httpx.BaseTransport) -> None:
        self._client = httpx.Client(base_url=base_url, transport=transport)

    def __enter__(self) -> HonuaClient:
        self._client.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        self._client.__exit__(*args)

    def ogc_processes(self) -> _OgcProcessesClient:
        return _OgcProcessesClient(self._client)


ARCPY_SOURCE = """
import arcpy as ap
from arcpy.analysis import Clip
from arcpy import management as mgmt

buffered = ap.Buffer_analysis("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
Clip("roads_buffer", "study_area", "roads_clip")
mgmt.Project("roads_clip", "roads_wgs84", 4326)
ap.management.SelectLayerByAttribute("roads_layer", "NEW_SELECTION", "STATUS = 'OPEN'")
with ap.da.SearchCursor("roads", ["OID@", "STATUS"]) as rows:
    pass
ap.sa.Kriging("stations", "PredZ")
"""


def test_scan_arcpy_source_classifies_aliases_legacy_tools_and_unsupported_calls() -> None:
    report = scan_arcpy_source(ARCPY_SOURCE, filename="workflow.py")

    assert [(call.qualified_name, call.family, call.tool, call.supported) for call in report.calls] == [
        ("arcpy.Buffer_analysis", "analysis", "Buffer", True),
        ("arcpy.analysis.Clip", "analysis", "Clip", True),
        ("arcpy.management.Project", "management", "Project", True),
        ("arcpy.management.SelectLayerByAttribute", "management", "SelectLayerByAttribute", True),
        ("arcpy.da.SearchCursor", "data-access", "SearchCursor", False),
        ("arcpy.sa.Kriging", "spatial-analyst", "Kriging", False),
    ]
    assert report.calls[0].args == ("roads", "roads_buffer", "25 Meters")
    assert report.calls[0].kwargs == {"dissolve_option": "ALL"}
    assert report.calls[0].assignment_targets == ("buffered",)
    assert report.unsupported_families == ("data-access", "spatial-analyst")


def test_translate_arcpy_source_builds_ogc_process_payloads_for_supported_vector_tools() -> None:
    plan = translate_arcpy_source(ARCPY_SOURCE, filename="workflow.py")

    assert [translation.process_id for translation in plan.translations] == [
        "buffer",
        "clip",
        "project",
        "select-by-attribute",
    ]
    buffer_payload = plan.translations[0].payload
    assert buffer_payload["inputs"] == {
        "input_features": "roads",
        "distance": "25 Meters",
        "dissolve_option": "ALL",
    }
    assert buffer_payload["outputs"] == {"result": "roads_buffer"}
    assert buffer_payload["metadata"]["honuaMigration"]["qualifiedName"] == "arcpy.Buffer_analysis"
    assert buffer_payload["metadata"]["honuaMigration"]["assignmentTargets"] == ["buffered"]

    select_payload = plan.translations[3].payload
    assert select_payload["inputs"] == {
        "input_features": "roads_layer",
        "selection_type": "NEW_SELECTION",
        "where": "STATUS = 'OPEN'",
    }
    assert plan.unsupported_families == ("data-access", "spatial-analyst")


def test_process_runner_executes_translated_steps_through_ogc_processes_client() -> None:
    plan = translate_arcpy_source(
        """
import arcpy
arcpy.analysis.Buffer("parcels", "parcels_buffer", "10 Meters")
arcpy.analysis.Clip("parcels_buffer", "district", "parcels_clip")
"""
    )
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.raw_path.decode("ascii").split("?")[0],
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
        process_id = request.url.path.split("/")[-2]
        return httpx.Response(200, json={"processID": process_id, "status": "accepted"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        results = ArcPyProcessRunner(client).execute_plan(plan)

    assert [result.result["processID"] for result in results] == ["buffer", "clip"]
    assert [(entry["method"], entry["path"]) for entry in seen] == [
        ("POST", "/ogc/processes/processes/buffer/execution"),
        ("POST", "/ogc/processes/processes/clip/execution"),
    ]
    assert seen[0]["body"]["inputs"] == {"input_features": "parcels", "distance": "10 Meters"}
    assert seen[0]["body"]["outputs"] == {"result": "parcels_buffer"}
    assert seen[1]["body"]["inputs"] == {
        "input_features": "parcels_buffer",
        "clip_features": "district",
    }
    assert seen[1]["body"]["outputs"] == {"result": "parcels_clip"}


def test_scan_arcpy_source_reports_syntax_error_without_importing_arcpy() -> None:
    report = scan_arcpy_source("import arcpy\narcpy.analysis.Buffer(")

    assert report.calls == ()
    assert report.syntax_error is not None
    assert "line 2" in report.syntax_error


def _make_translation(process_id: str = "buffer") -> ArcPyProcessTranslation:
    plan = translate_arcpy_source(
        'import arcpy\narcpy.analysis.Buffer("parcels", "parcels_buffer", "10 Meters")'
    )
    translation = plan.translations[0]
    return ArcPyProcessTranslation(
        call=translation.call,
        process_id=process_id,
        payload=translation.payload,
        notes=translation.notes,
    )


class _JobHandler:
    """Stateful OGC API - Processes async-job mock transport."""

    def __init__(self, *, status_sequence: list[str], results: dict[str, Any] | None = None, job_id: str = "job-1") -> None:
        self.status_sequence = status_sequence
        self.results = results if results is not None else {"outputs": {"result": "https://store/parcels_buffer.json"}}
        self.job_id = job_id
        self.requests: list[tuple[str, str]] = []
        self._poll_index = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        self.requests.append((request.method, path))
        if request.method == "POST" and path.endswith("/execution"):
            return httpx.Response(201, json={"jobID": self.job_id, "status": self.status_sequence[0]})
        if request.method == "GET" and path.endswith(f"/jobs/{self.job_id}"):
            self._poll_index += 1
            index = min(self._poll_index, len(self.status_sequence) - 1)
            return httpx.Response(200, json={"jobID": self.job_id, "status": self.status_sequence[index]})
        if request.method == "GET" and path.endswith(f"/jobs/{self.job_id}/results"):
            return httpx.Response(200, json=self.results)
        return httpx.Response(404, json={"error": "unexpected"})


def test_runner_execute_async_polls_job_until_success_and_downloads_results() -> None:
    handler = _JobHandler(status_sequence=["accepted", "running", "successful"])
    slept: list[float] = []
    translation = _make_translation("buffer")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        runner = ArcPyProcessRunner(client, poll_interval=0.5, sleep=slept.append)
        execution = runner.execute_async(translation)

    assert execution.job_id == "job-1"
    assert execution.status == "successful"
    assert execution.succeeded is True
    assert execution.results == {"outputs": {"result": "https://store/parcels_buffer.json"}}
    # submit + 2 polls (running, successful) + results download
    assert handler.requests == [
        ("POST", "/ogc/processes/processes/buffer/execution"),
        ("GET", "/ogc/processes/jobs/job-1"),
        ("GET", "/ogc/processes/jobs/job-1"),
        ("GET", "/ogc/processes/jobs/job-1/results"),
    ]
    assert slept == [0.5, 0.5]

    evidence = execution.to_dict()
    assert evidence["jobId"] == "job-1"
    assert evidence["status"] == "successful"
    assert evidence["succeeded"] is True
    assert evidence["results"] == handler.results


def test_runner_execute_async_returns_synchronous_response_without_polling() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # No job id in the body => server executed synchronously.
        return httpx.Response(200, json={"outputs": {"result": "inline"}})

    translation = _make_translation("buffer")
    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        execution = ArcPyProcessRunner(client).execute_async(translation)

    assert execution.job_id is None
    assert execution.status is None
    assert execution.results is None
    assert execution.result == {"outputs": {"result": "inline"}}
    assert execution.succeeded is True


def test_runner_execute_async_raises_on_failed_job() -> None:
    handler = _JobHandler(status_sequence=["accepted", "failed"])
    translation = _make_translation("buffer")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        runner = ArcPyProcessRunner(client, sleep=lambda _seconds: None)
        with pytest.raises(ArcPyJobError) as excinfo:
            runner.execute_async(translation)

    assert excinfo.value.job_id == "job-1"
    assert excinfo.value.status == "failed"
    # No results fetch after a failed job.
    assert ("GET", "/ogc/processes/jobs/job-1/results") not in handler.requests


def test_runner_execute_async_times_out_when_job_never_finishes() -> None:
    handler = _JobHandler(status_sequence=["accepted", "running"])
    translation = _make_translation("buffer")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        runner = ArcPyProcessRunner(client, max_polls=3, sleep=lambda _seconds: None)
        with pytest.raises(ArcPyJobTimeoutError) as excinfo:
            runner.execute_async(translation)

    assert excinfo.value.polls == 3
    assert excinfo.value.status == "running"


def test_runner_normalizes_vendor_job_status_aliases() -> None:
    handler = _JobHandler(status_sequence=["queued", "in_progress", "succeeded"])
    translation = _make_translation("buffer")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        runner = ArcPyProcessRunner(client, sleep=lambda _seconds: None)
        execution = runner.execute_async(translation)

    assert execution.status == "successful"
    assert execution.succeeded is True


def test_runner_execute_plan_async_runs_all_translations_in_order() -> None:
    plan = translate_arcpy_source(
        'import arcpy\n'
        'arcpy.analysis.Buffer("parcels", "parcels_buffer", "10 Meters")\n'
        'arcpy.analysis.Clip("parcels_buffer", "district", "parcels_clip")\n'
    )
    submitted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        if request.method == "POST" and path.endswith("/execution"):
            process_id = path.split("/")[-2]
            submitted.append(process_id)
            return httpx.Response(201, json={"jobID": f"job-{process_id}", "status": "accepted"})
        if path.endswith("/results"):
            return httpx.Response(200, json={"outputs": {}})
        job_id = path.split("/")[-1]
        return httpx.Response(200, json={"jobID": job_id, "status": "successful"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        runner = ArcPyProcessRunner(client, sleep=lambda _seconds: None)
        executions = runner.execute_plan_async(plan)

    assert submitted == ["buffer", "clip"]
    assert all(execution.succeeded for execution in executions)
    assert [execution.job_id for execution in executions] == ["job-buffer", "job-clip"]


def test_runner_execute_async_rejects_unmapped_translation() -> None:
    translation = _make_translation(process_id="")
    runner = ArcPyProcessRunner(object())
    with pytest.raises(UnsupportedArcPyCallError):
        runner.execute_async(translation)


def test_process_execution_to_dict_for_synchronous_result() -> None:
    translation = _make_translation("buffer")
    execution = ArcPyProcessExecution(translation=translation, result={"status": "successful"})

    record = execution.to_dict()
    assert "jobId" not in record
    assert "status" not in record
    assert record["succeeded"] is True
    assert record["result"] == {"status": "successful"}
