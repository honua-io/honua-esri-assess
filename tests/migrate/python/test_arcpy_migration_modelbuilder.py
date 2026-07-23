"""Tests for the ModelBuilder (.atbx) + GP-service translation slice (issue #82).

Covers:

* ModelBuilder model-definition translation (process steps -> Honua plan),
* clean-room ``.atbx`` zip-of-JSON parsing (models + script-tool discovery),
* the proprietary ``.tbx`` binary stub staying a hard error,
* GP-service task/service definition translation (ArcGIS REST GPServer JSON),
* aggregated parity-evidence for both new inputs.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from honua_migrate.code.python import (
    EXECUTABLE_PROCESS_IDS,
    GpService,
    GpTask,
    ModelBuilderToolbox,
    UnsupportedModelFormatError,
    UnsupportedToolboxError,
    build_atbx_parity_evidence,
    build_gp_service_parity_evidence,
    build_model_parity_evidence,
    parse_atbx_toolbox,
    parse_binary_toolbox,
    parse_gp_service_definition,
    parse_gp_task_definition,
    parse_model_definition,
)


# ---------------------------------------------------------------------------
# ModelBuilder model definitions
# ---------------------------------------------------------------------------

MODEL_DEFINITION = {
    "name": "WetlandsAnalysis",
    "label": "Wetlands Analysis",
    "processes": [
        {
            "toolName": "Buffer",
            "toolbox": "analysis",
            "label": "Buffer Wetlands",
            "parameters": {
                "in_features": "wetlands",
                "out_feature_class": "wetlands_buf",
                "buffer_distance_or_field": "100 Meters",
            },
        },
        {
            "toolName": "Erase_analysis",
            "parameters": {
                "in_features": "wetlands_buf",
                "erase_features": "roads",
                "out_feature_class": "trimmed",
            },
        },
        {
            "toolName": "AddField",
            "toolbox": "management",
            "parameters": {"in_table": "trimmed", "field_name": "AREA"},
        },
    ],
}


def test_parse_model_definition_classifies_each_step() -> None:
    model = parse_model_definition(MODEL_DEFINITION)

    assert model.name == "WetlandsAnalysis"
    assert model.label == "Wetlands Analysis"
    assert [step.tool_name for step in model.steps] == ["Buffer", "Erase_analysis", "AddField"]

    buffer, erase, addfield = model.steps
    assert buffer.call.qualified_name == "arcpy.analysis.Buffer"
    assert buffer.call.status == "translatable"
    assert buffer.call.process_id == "buffer"
    assert buffer.call.job_process_id == "geometry.buffer"

    # Legacy "Buffer_analysis"-style underscore reference normalizes to family.
    assert erase.call.qualified_name == "arcpy.analysis.Erase"
    assert erase.call.status == "manual-review"
    assert erase.call.process_id == "erase"

    # AddField has no Honua mapping -> unsupported.
    assert addfield.call.status == "unsupported"
    assert addfield.call.process_id is None


def test_parse_model_definition_translates_inputs_to_payload() -> None:
    model = parse_model_definition(MODEL_DEFINITION)
    buffer_step = model.steps[0]
    (translation,) = (t for t in model.plan.translations if t.call.tool == "Buffer")
    assert translation.payload["inputs"]["input_features"] == "wetlands"
    assert translation.payload["inputs"]["distance"] == "100 Meters"
    assert translation.payload["outputs"]["result"] == "wetlands_buf"
    # The model step exposes the raw inputs alongside the classification.
    assert buffer_step.inputs["buffer_distance_or_field"] == "100 Meters"


def test_parse_model_definition_accepts_json_string() -> None:
    model = parse_model_definition(json.dumps(MODEL_DEFINITION), name="Override")
    assert model.name == "Override"
    assert len(model.steps) == 3


def test_parse_model_definition_alternate_step_keys() -> None:
    # ``steps`` + ``tool`` + ``inputs`` variant must parse identically.
    model = parse_model_definition(
        {
            "name": "Alt",
            "steps": [
                {"tool": "analysis.Buffer", "inputs": {"in_features": "a", "out_feature_class": "b"}},
            ],
        }
    )
    (step,) = model.steps
    assert step.call.qualified_name == "arcpy.analysis.Buffer"
    assert step.call.status == "translatable"


def test_parse_model_definition_rejects_non_object() -> None:
    with pytest.raises(UnsupportedModelFormatError):
        parse_model_definition(json.dumps([1, 2, 3]))


def test_model_parity_evidence_reports_coverage() -> None:
    model = parse_model_definition(MODEL_DEFINITION)
    evidence = build_model_parity_evidence(model)
    assert evidence["modelName"] == "WetlandsAnalysis"
    summary = evidence["summary"]
    assert summary["totalCalls"] == 3
    assert summary["translatableCalls"] == 1
    assert summary["manualReviewCalls"] == 1
    assert summary["unsupportedCalls"] == 1
    assert summary["coveragePercent"] == 33.33


# ---------------------------------------------------------------------------
# .atbx clean-room zip parsing
# ---------------------------------------------------------------------------


def _write_atbx(path, *, models=None, script_tools=None):
    """Build a minimal clean-room .atbx zip-of-JSON fixture.

    Mirrors the published ``.atbx`` layout: a zip whose ``<ToolName>.tool/``
    folders carry a JSON ``*.content`` describing either a model (process list)
    or a script tool (``script`` -> ``.py``).
    """

    models = models or {}
    script_tools = script_tools or {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("toolbox.content", json.dumps({"version": "1.0"}))
        for tool_name, definition in models.items():
            archive.writestr(f"{tool_name}.tool/tool.content", json.dumps(definition))
        for tool_name, script in script_tools.items():
            archive.writestr(
                f"{tool_name}.tool/tool.content",
                json.dumps({"type": "ScriptTool", "script": script}),
            )
    path.write_bytes(buffer.getvalue())
    return path


def test_parse_atbx_toolbox_extracts_models(tmp_path) -> None:
    atbx = _write_atbx(
        tmp_path / "wetlands.atbx",
        models={
            "WetlandsAnalysis": MODEL_DEFINITION,
            "JustBuffer": {
                "name": "JustBuffer",
                "processes": [
                    {"toolName": "Buffer", "toolbox": "analysis",
                     "parameters": {"in_features": "a", "out_feature_class": "b",
                                    "buffer_distance_or_field": "5 Meters"}},
                ],
            },
        },
        script_tools={"CustomScript": "custom.py"},
    )

    toolbox = parse_atbx_toolbox(atbx)
    assert isinstance(toolbox, ModelBuilderToolbox)
    assert toolbox.parse_error is None
    model_names = sorted(m.name for m in toolbox.models)
    assert model_names == ["JustBuffer", "WetlandsAnalysis"]
    assert toolbox.script_tool_names == ("CustomScript",)


def test_parse_atbx_toolbox_aggregated_evidence(tmp_path) -> None:
    atbx = _write_atbx(tmp_path / "wetlands.atbx", models={"WetlandsAnalysis": MODEL_DEFINITION})
    toolbox = parse_atbx_toolbox(atbx)
    evidence = build_atbx_parity_evidence(toolbox)

    assert evidence["schema"] == "honua.migration.arcpy.atbx-parity-evidence/v1"
    summary = evidence["summary"]
    assert summary["modelCount"] == 1
    assert summary["totalCalls"] == 3
    assert summary["translatableCalls"] == 1
    assert summary["coveragePercent"] == 33.33


def test_parse_atbx_toolbox_bad_archive_reports_parse_error(tmp_path) -> None:
    bad = tmp_path / "not-a-zip.atbx"
    bad.write_text("this is not a zip", encoding="utf-8")
    toolbox = parse_atbx_toolbox(bad)
    assert toolbox.models == ()
    assert toolbox.parse_error is not None


def test_parse_atbx_rejects_binary_tbx(tmp_path) -> None:
    tbx = tmp_path / "legacy.tbx"
    tbx.write_bytes(b"\x00\x01binary")
    with pytest.raises(UnsupportedModelFormatError):
        parse_atbx_toolbox(tbx)


def test_parse_binary_toolbox_redirects_atbx(tmp_path) -> None:
    # The legacy pyt entry point must redirect .atbx to the modelbuilder reader.
    with pytest.raises(UnsupportedToolboxError) as excinfo:
        parse_binary_toolbox(tmp_path / "example.atbx")
    assert "parse_atbx_toolbox" in str(excinfo.value)


def test_parse_binary_toolbox_still_stubs_tbx(tmp_path) -> None:
    with pytest.raises(UnsupportedToolboxError) as excinfo:
        parse_binary_toolbox(tmp_path / "legacy.tbx")
    assert ".tbx" in str(excinfo.value)


# ---------------------------------------------------------------------------
# GP-service task / service definitions
# ---------------------------------------------------------------------------

BUFFER_TASK_DEF = {
    "name": "Buffer",
    "displayName": "Buffer",
    "executionType": "esriExecutionTypeAsynchronous",
    "parameters": [
        {"name": "in_features", "dataType": "GPFeatureRecordSetLayer",
         "direction": "esriGPParameterDirectionInput"},
        {"name": "distance", "dataType": "GPLinearUnit",
         "direction": "esriGPParameterDirectionInput", "defaultValue": "100 Meters"},
        {"name": "out_feature_class", "dataType": "DEFeatureClass",
         "direction": "esriGPParameterDirectionOutput"},
    ],
}


def test_parse_gp_task_definition_maps_to_process() -> None:
    task = parse_gp_task_definition(BUFFER_TASK_DEF)
    assert isinstance(task, GpTask)
    assert task.name == "Buffer"
    assert task.execution_type == "esriExecutionTypeAsynchronous"
    assert [p.name for p in task.parameters] == ["in_features", "distance", "out_feature_class"]

    (call,) = task.plan.report.calls
    assert call.qualified_name == "arcpy.analysis.Buffer"
    assert call.status == "translatable"
    assert call.process_id == "buffer"
    assert call.job_process_id in EXECUTABLE_PROCESS_IDS
    # Input parameters become kwargs; the output parameter is excluded.
    assert call.kwargs["distance"] == "100 Meters"
    assert "out_feature_class" not in call.kwargs


def test_parse_gp_task_definition_unknown_is_unsupported() -> None:
    task = parse_gp_task_definition({"name": "TotallyCustomTask"})
    (call,) = task.plan.report.calls
    assert call.status == "unsupported"
    assert call.process_id is None


def test_parse_gp_service_definition_classifies_all_tasks() -> None:
    service = parse_gp_service_definition(
        {"tasks": ["Buffer", "SymDiff", "MysteryTask"]},
        url="https://example.test/arcgis/rest/services/GP/GPServer",
        task_definitions={"Buffer": BUFFER_TASK_DEF},
    )
    assert isinstance(service, GpService)
    statuses = {t.name: t.plan.report.calls[0].status for t in service.tasks}
    assert statuses == {
        "Buffer": "translatable",
        "SymDiff": "manual-review",
        "MysteryTask": "unsupported",
    }


def test_parse_gp_service_definition_accepts_task_objects() -> None:
    # The GPServer catalog sometimes lists tasks as objects, not strings.
    service = parse_gp_service_definition({"tasks": [{"name": "Buffer"}]})
    (task,) = service.tasks
    assert task.name == "Buffer"
    assert task.plan.report.calls[0].status == "translatable"


def test_gp_service_aggregated_evidence() -> None:
    service = parse_gp_service_definition(
        {"tasks": ["Buffer", "SymDiff", "MysteryTask"]},
        task_definitions={"Buffer": BUFFER_TASK_DEF},
    )
    evidence = build_gp_service_parity_evidence(service)
    assert evidence["schema"] == "honua.migration.arcpy.gp-service-parity-evidence/v1"
    summary = evidence["summary"]
    assert summary["taskCount"] == 3
    assert summary["translatableCalls"] == 1
    assert summary["manualReviewCalls"] == 1
    assert summary["unsupportedCalls"] == 1
    assert summary["coveragePercent"] == 33.33


def test_parse_gp_service_definition_rejects_non_object() -> None:
    with pytest.raises(UnsupportedModelFormatError):
        parse_gp_service_definition(json.dumps(["a", "b"]))


# ---------------------------------------------------------------------------
# Serialization (to_dict) + tolerant-shape coverage
# ---------------------------------------------------------------------------


def test_model_to_dict_is_json_serializable() -> None:
    model = parse_model_definition(MODEL_DEFINITION)
    payload = model.to_dict()
    assert payload["schema"] == "honua.migration.arcpy.modelbuilder-model/v1"
    # Round-trips through json without raising.
    json.dumps(payload)
    assert payload["steps"][0]["status"] == "translatable"
    assert payload["parityEvidence"]["summary"]["totalCalls"] == 3


def test_atbx_toolbox_to_dict_records_parse_error(tmp_path) -> None:
    bad = tmp_path / "broken.atbx"
    bad.write_text("not a zip", encoding="utf-8")
    payload = parse_atbx_toolbox(bad).to_dict()
    assert payload["parseError"] is not None
    json.dumps(payload)


def test_gp_service_and_task_to_dict_are_serializable() -> None:
    service = parse_gp_service_definition(
        {"tasks": ["Buffer"]}, task_definitions={"Buffer": BUFFER_TASK_DEF}
    )
    payload = service.to_dict()
    assert payload["schema"] == "honua.migration.arcpy.gp-service/v1"
    task_payload = payload["tasks"][0]
    assert task_payload["schema"] == "honua.migration.arcpy.gp-task/v1"
    assert task_payload["parameters"][1]["defaultValue"] == "100 Meters"
    json.dumps(payload)


def test_model_step_parameters_accept_list_form() -> None:
    # ModelBuilder also expresses parameters as a list of {name, value} objects.
    model = parse_model_definition(
        {
            "name": "ListParams",
            "processes": [
                {
                    "toolName": "Buffer",
                    "toolbox": "analysis",
                    "parameters": [
                        {"name": "in_features", "value": "a"},
                        {"name": "out_feature_class", "value": "b"},
                        {"name": "buffer_distance_or_field", "value": "5 Meters"},
                    ],
                }
            ],
        }
    )
    (step,) = model.steps
    assert step.inputs["in_features"] == "a"
    assert step.call.status == "translatable"


def test_atbx_model_detected_by_tool_type(tmp_path) -> None:
    # A tool whose JSON only declares a model type (no inline process list yet)
    # is recognized as a model but yields no steps -> excluded from models.
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "EmptyModel.tool/tool.content",
            json.dumps({"type": "ModelTool", "processes": []}),
        )
    atbx = tmp_path / "empty.atbx"
    atbx.write_bytes(buffer.getvalue())

    toolbox = parse_atbx_toolbox(atbx)
    assert toolbox.models == ()
    assert toolbox.parse_error is None
