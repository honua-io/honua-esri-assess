"""Tests for the Python toolbox (.pyt) parsing slice."""

from __future__ import annotations

import pytest

from honua_migrate.code.python import (
    UnsupportedToolboxError,
    build_pyt_parity_evidence,
    parse_binary_toolbox,
    parse_pyt_source,
)

PYT_SOURCE = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "Roads Toolbox"
        self.alias = "roads"
        self.tools = [BufferRoads, EraseRivers]


class BufferRoads(object):
    def __init__(self):
        self.label = "Buffer Roads"
        self.description = "Buffer the road network."

    def getParameterInfo(self):
        in_fc = arcpy.Parameter(
            displayName="Input Features",
            name="in_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        distance = arcpy.Parameter(
            displayName="Distance",
            name="distance",
            datatype="GPLinearUnit",
            parameterType="Required",
            direction="Input",
        )
        out = arcpy.Parameter(
            displayName="Output",
            name="out_features",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
        )
        return [in_fc, distance, out]

    def execute(self, parameters, messages):
        """Run the buffer."""
        arcpy.analysis.Buffer(
            parameters[0].valueAsText, parameters[2].valueAsText, parameters[1].valueAsText
        )


class EraseRivers(object):
    def __init__(self):
        self.label = "Erase Rivers"

    def getParameterInfo(self):
        return []

    def execute(self, parameters, messages):
        # Erase is manual-review: feature-class subtract != geometry.difference.
        arcpy.analysis.Erase("roads", "rivers", "trimmed")
'''


def test_parse_pyt_source_extracts_toolbox_and_tools() -> None:
    toolbox = parse_pyt_source(PYT_SOURCE, filename="roads.pyt")

    assert toolbox.label == "Roads Toolbox"
    assert toolbox.alias == "roads"
    assert toolbox.declared_tool_names == ("BufferRoads", "EraseRivers")
    assert [tool.class_name for tool in toolbox.tools] == ["BufferRoads", "EraseRivers"]


def test_parse_pyt_source_extracts_parameters() -> None:
    toolbox = parse_pyt_source(PYT_SOURCE)
    buffer_tool = toolbox.tools[0]

    assert [p.name for p in buffer_tool.parameters] == ["in_features", "distance", "out_features"]
    in_param = buffer_tool.parameters[0]
    assert in_param.display_name == "Input Features"
    assert in_param.datatype == "GPFeatureLayer"
    assert in_param.parameter_type == "Required"
    assert in_param.direction == "Input"
    assert buffer_tool.parameters[2].direction == "Output"


def test_parse_pyt_source_feeds_execute_body_through_scanner() -> None:
    toolbox = parse_pyt_source(PYT_SOURCE)
    buffer_tool, erase_tool = toolbox.tools

    # Buffer maps to a job-executable process -> translatable.
    assert [t.process_id for t in buffer_tool.plan.translations] == ["buffer"]
    assert [c.tool for c in buffer_tool.plan.report.translatable_calls] == ["Buffer"]
    # Erase is supported (OGC bare id "erase") so it still translates on the OGC
    # path, but it is job manual-review (not job-executable).
    assert [t.process_id for t in erase_tool.plan.translations] == ["erase"]
    assert [(c.family, c.tool) for c in erase_tool.plan.manual_review_calls] == [
        ("analysis", "Erase")
    ]
    assert erase_tool.plan.report.translatable_calls == ()


def test_pyt_aggregated_parity_evidence() -> None:
    toolbox = parse_pyt_source(PYT_SOURCE, filename="roads.pyt")
    evidence = build_pyt_parity_evidence(toolbox)

    assert evidence["schema"] == "honua.migration.arcpy.pyt-parity-evidence/v1"
    assert evidence["label"] == "Roads Toolbox"
    summary = evidence["summary"]
    assert summary["toolCount"] == 2
    assert summary["totalCalls"] == 2
    assert summary["translatableCalls"] == 1
    assert summary["manualReviewCalls"] == 1
    assert summary["coveragePercent"] == 50.0


def test_parse_pyt_source_without_declared_tools_falls_back_to_execute_classes() -> None:
    source = """
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "Fallback"
        self.alias = "fb"


class Loner(object):
    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meters")
"""
    toolbox = parse_pyt_source(source)
    assert [tool.class_name for tool in toolbox.tools] == ["Loner"]
    assert [t.process_id for t in toolbox.tools[0].plan.translations] == ["buffer"]


def test_parse_pyt_source_reports_syntax_error() -> None:
    toolbox = parse_pyt_source("class Toolbox(:\n    pass", filename="bad.pyt")
    assert toolbox.tools == ()
    assert toolbox.syntax_error is not None


PYT_PARAM_ATTRS_SOURCE = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "Attrs Toolbox"
        self.alias = "attrs"
        self.tools = [Styled]


class Styled(object):
    def __init__(self):
        self.label = "Styled"

    def getParameterInfo(self):
        distance = arcpy.Parameter(
            displayName="Distance",
            name="distance",
            datatype="GPLinearUnit",
            parameterType="Required",
            direction="Input",
        )
        distance.value = "25 Meters"
        method = arcpy.Parameter(
            displayName="Method",
            name="method",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        method.filter.list = ["PLANAR", "GEODESIC"]
        method.value = "PLANAR"
        return [distance, method]

    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", parameters[0].valueAsText)
'''


def test_parse_pyt_captures_default_value_and_filter_list() -> None:
    toolbox = parse_pyt_source(PYT_PARAM_ATTRS_SOURCE, filename="attrs.pyt")
    (tool,) = toolbox.tools
    params = {p.name: p for p in tool.parameters}

    assert params["distance"].default_value == "25 Meters"
    assert params["distance"].filter_list is None

    assert params["method"].default_value == "PLANAR"
    assert params["method"].filter_list == ("PLANAR", "GEODESIC")


def test_pyt_parameter_to_dict_includes_attrs_only_when_present() -> None:
    toolbox = parse_pyt_source(PYT_PARAM_ATTRS_SOURCE)
    (tool,) = toolbox.tools
    params = {p.name: p.to_dict() for p in tool.parameters}

    method = params["method"]
    assert method["defaultValue"] == "PLANAR"
    assert method["filterList"] == ["PLANAR", "GEODESIC"]

    distance = params["distance"]
    assert distance["defaultValue"] == "25 Meters"
    assert "filterList" not in distance


def test_pyt_bound_parameters_are_not_double_counted() -> None:
    # PYT_SOURCE binds each Parameter to a local then returns the locals; the
    # parser must report exactly one parameter per constructor, not two.
    toolbox = parse_pyt_source(PYT_SOURCE)
    buffer_tool = toolbox.tools[0]
    assert [p.name for p in buffer_tool.parameters] == [
        "in_features",
        "distance",
        "out_features",
    ]


def test_parse_binary_toolbox_is_stubbed_with_todo(tmp_path) -> None:
    with pytest.raises(UnsupportedToolboxError) as excinfo:
        parse_binary_toolbox(tmp_path / "example.atbx")
    assert "not implemented" in str(excinfo.value)
    assert ".atbx" in str(excinfo.value)
