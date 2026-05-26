from __future__ import annotations

import json
from typing import Any

import httpx

from honua_sdk import HonuaClient
from honua_migrate.code.python import (
    ArcPyProcessRunner,
    scan_arcpy_source,
    translate_arcpy_source,
)


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
ap.sa.Slope("elevation")
"""


def test_scan_arcpy_source_classifies_aliases_legacy_tools_and_unsupported_calls() -> None:
    report = scan_arcpy_source(ARCPY_SOURCE, filename="workflow.py")

    assert [(call.qualified_name, call.family, call.tool, call.supported) for call in report.calls] == [
        ("arcpy.Buffer_analysis", "analysis", "Buffer", True),
        ("arcpy.analysis.Clip", "analysis", "Clip", True),
        ("arcpy.management.Project", "management", "Project", True),
        ("arcpy.management.SelectLayerByAttribute", "management", "SelectLayerByAttribute", True),
        ("arcpy.da.SearchCursor", "data-access", "SearchCursor", False),
        ("arcpy.sa.Slope", "spatial-analyst", "Slope", False),
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
