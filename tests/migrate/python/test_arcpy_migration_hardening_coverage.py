"""Coverage-uplift tests for the reconciled ArcPy migration hardening.

Targets the overlay branches added on top of trunk's canonical codemod: the
``_ToolSpec`` job-executability properties, the per-call SpatialJoin gate and
positional-argument resolution, expanded ``**kwargs`` capture, the parity
-evidence emitters, the ``.pyt`` toolbox parser internals, and the
``honua-migrate`` CLI edge paths (including ``python -m honua_migrate.code.python``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from honua_migrate.code.python import (
    ArcPyCall,
    build_parity_evidence,
    scan_arcpy_source,
    translate_arcpy_source,
)
from honua_migrate.code.python._cli import main
from honua_migrate.code.python.arcpy import (
    _call_argument,
    _kind_for_process_name,
    _lookup_spec,
    _spatial_join_gate,
)
from honua_migrate.code.python.pyt import (
    _const_value,
    parse_pyt_source,
)


# ---------------------------------------------------------------------------
# arcpy overlay internals
# ---------------------------------------------------------------------------


def test_unmapped_call_has_no_manual_review_reason() -> None:
    # arcpy.py:106 -- manual_review_reason returns None when there is no spec.
    call = ArcPyCall(qualified_name="arcpy.sa.Kriging", family="spatial-analyst", tool="Kriging", line=1, column=0)
    assert call.status == "unsupported"
    assert call.manual_review_reason is None
    assert call.process_id is None
    assert call.job_process_id is None


def test_tool_spec_status_property_ignores_gate() -> None:
    # arcpy.py:335 -- spec-level status (gate-independent).
    spec = _lookup_spec("analysis", "SpatialJoin")
    assert spec is not None
    assert spec.executable is True
    assert spec.status == "translatable"
    erase = _lookup_spec("analysis", "Erase")
    assert erase is not None
    assert erase.executable is False
    assert erase.status == "manual-review"


def test_call_argument_positional_fallback() -> None:
    # arcpy.py:393 -- positional resolution when no keyword is present.
    report = scan_arcpy_source(
        'import arcpy\narcpy.analysis.SpatialJoin("t", "j", "o", "JOIN_ONE_TO_MANY")\n'
    )
    (call,) = report.calls
    # join_operation is the 4th positional (index 3); the gate reads it.
    assert _call_argument(call, 3, "join_operation") == "JOIN_ONE_TO_MANY"
    assert call.status == "manual-review"
    assert "JOIN_ONE_TO_MANY" in (call.manual_review_reason or "")


def test_spatial_join_gate_passes_for_plain_call() -> None:
    call = ArcPyCall(qualified_name="arcpy.analysis.SpatialJoin", family="analysis", tool="SpatialJoin", line=1, column=0)
    assert _spatial_join_gate(call) == ("translatable", None)


def test_kind_for_process_name_defaults_to_parameter() -> None:
    # arcpy.py:1127 -- unknown process name falls back to "parameter".
    spec = _lookup_spec("analysis", "Buffer")
    assert spec is not None
    assert _kind_for_process_name("does-not-exist", spec) == "parameter"


def test_expanded_kwargs_captured_and_serialized() -> None:
    # arcpy.py:150-151 (to_dict) + 1094 (translation metadata).
    report = scan_arcpy_source(
        'import arcpy\nopts = {"method": "PLANAR"}\narcpy.analysis.Buffer("a", "b", "1 Meter", **opts)\n'
    )
    buffer_call = next(c for c in report.calls if c.tool == "Buffer")
    assert buffer_call.expanded_kwargs  # the **opts expansion was recorded
    as_dict = buffer_call.to_dict()
    assert "expandedKwargs" in as_dict
    assert "rawExpandedKwargs" in as_dict

    plan = translate_arcpy_source(
        'import arcpy\nopts = {"method": "PLANAR"}\narcpy.analysis.Buffer("a", "b", "1 Meter", **opts)\n'
    )
    translation = next(t for t in plan.translations if t.call.tool == "Buffer")
    expanded = translation.payload["metadata"]["honuaMigration"]["expandedKeywords"]
    assert expanded and "raw" in expanded[0]


def test_parity_evidence_translatable_call_with_notes() -> None:
    # Dissolve carries spec notes and is translatable -> notes attached to entry.
    evidence = build_parity_evidence(
        translate_arcpy_source('import arcpy\narcpy.management.Dissolve("a", "b", "CLASS")\n')
    )
    entry = next(c for c in evidence["calls"] if c["tool"] == "Dissolve")
    assert entry["status"] == "translatable"
    assert "payload" in entry
    assert entry["notes"]


# ---------------------------------------------------------------------------
# .pyt parser internals
# ---------------------------------------------------------------------------


def test_pyt_toolbox_to_dict_includes_syntax_error() -> None:
    toolbox = parse_pyt_source("class Toolbox(:\n    pass", filename="bad.pyt")
    as_dict = toolbox.to_dict()
    assert "syntaxError" in as_dict


def test_pyt_class_level_label_and_attribute_tool_refs() -> None:
    # Class-level `label = "..."` (pyt.py:313-317) and self.tools listing tool
    # classes via attribute references resolved by name (_names_in_sequence).
    source = '''
import arcpy
import mod


class Toolbox(object):
    label = "Class Level"
    alias = "cl"

    def __init__(self):
        self.tools = [mod.Aliased]


class Aliased(object):
    label = "Aliased Tool"

    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meter")
'''
    toolbox = parse_pyt_source(source)
    assert toolbox.label == "Class Level"
    # self.tools referenced mod.Aliased -> attribute name "Aliased".
    assert toolbox.declared_tool_names == ("Aliased",)


def test_pyt_toolbox_detected_by_self_tools_when_not_named_toolbox() -> None:
    # _find_toolbox_class fallback (pyt.py:255-257): a class assigning self.tools
    # but NOT named Toolbox is still recognized.
    source = '''
import arcpy


class MyBox(object):
    def __init__(self):
        self.label = "Box"
        self.tools = [Doer]


class Doer(object):
    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meter")
'''
    toolbox = parse_pyt_source(source)
    assert toolbox.label == "Box"
    assert [t.class_name for t in toolbox.tools] == ["Doer"]


def test_pyt_tool_without_execute_yields_empty_plan() -> None:
    # _parse_tool's no-execute branch (pyt.py:238-239).
    source = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.tools = [NoExec]


class NoExec(object):
    label = "No Exec"

    def getParameterInfo(self):
        return []
'''
    toolbox = parse_pyt_source(source)
    (tool,) = toolbox.tools
    assert tool.plan.translations == ()
    assert tool.report.calls == ()


def test_pyt_no_toolbox_class_returns_empty() -> None:
    # _find_toolbox_class returns None (pyt.py:258) when nothing looks like a box.
    source = "import arcpy\n\n\nclass Plain(object):\n    pass\n"
    toolbox = parse_pyt_source(source)
    assert toolbox.label is None
    assert toolbox.tools == ()


def test_pyt_parameter_with_non_constant_value_is_none() -> None:
    # _const_value error path (pyt.py:396-397) + non-string attr handling.
    source = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.tools = [P]


class P(object):
    def getParameterInfo(self):
        return [arcpy.Parameter(name=compute_name(), displayName="X")]

    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meter")
'''
    toolbox = parse_pyt_source(source)
    (param,) = toolbox.tools[0].parameters
    assert param.name is None  # compute_name() is not a constant
    assert param.display_name == "X"


def test_const_value_returns_none_for_non_literal() -> None:
    import ast

    node = ast.parse("foo()", mode="eval").body
    assert _const_value(node) is None


def test_pyt_declared_tool_name_without_class_is_skipped() -> None:
    # pyt.py:144 -- self.tools references a name with no matching class def.
    source = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.tools = [Missing]


class Present(object):
    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meter")
'''
    toolbox = parse_pyt_source(source)
    # "Missing" has no class def, so no tools are materialized for it.
    assert toolbox.declared_tool_names == ("Missing",)
    assert toolbox.tools == ()


def test_pyt_execute_with_only_docstring_has_empty_body() -> None:
    # pyt.py:278 -- _method_body_source returns None for a docstring-only body.
    source = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.tools = [DocOnly]


class DocOnly(object):
    def execute(self, parameters, messages):
        """Only a docstring, no statements."""
'''
    toolbox = parse_pyt_source(source)
    (tool,) = toolbox.tools
    assert tool.execute_source is None
    assert tool.report.calls == ()


def test_pyt_self_tools_non_sequence_yields_no_declared_names() -> None:
    # pyt.py:350 -- self.tools assigned a non-list/tuple expression.
    source = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.tools = build_tools()


class Doer(object):
    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meter")
'''
    toolbox = parse_pyt_source(source)
    # self.tools is a call, not a literal sequence -> no declared names, falls
    # back to execute-bearing classes.
    assert toolbox.declared_tool_names == ()
    assert [t.class_name for t in toolbox.tools] == ["Doer"]


def test_pyt_non_parameter_constructor_is_ignored() -> None:
    # pyt.py:385 -- a Parameter-like call whose func is neither Name nor
    # Attribute (e.g. a subscripted callable) is not treated as a Parameter.
    source = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.tools = [P]


class P(object):
    def getParameterInfo(self):
        factories[0](name="ignored")
        return [arcpy.Parameter(name="kept", displayName="Kept")]

    def execute(self, parameters, messages):
        arcpy.analysis.Buffer("a", "b", "1 Meter")
'''
    toolbox = parse_pyt_source(source)
    names = [p.name for p in toolbox.tools[0].parameters]
    assert names == ["kept"]


# ---------------------------------------------------------------------------
# CLI edge paths
# ---------------------------------------------------------------------------


def test_cli_translate_without_evidence_emits_plan_to_stdout(tmp_path: Path, capsys) -> None:
    # _cli.py:66 -- translate with no --evidence emits the plan only.
    script = tmp_path / "wf.py"
    script.write_text('import arcpy\narcpy.analysis.Buffer("a", "b", "1 Meter")\n', encoding="utf-8")

    rc = main(["translate", str(script)])

    assert rc == 0
    captured = capsys.readouterr()
    plan = json.loads(captured.out)
    assert [t["processId"] for t in plan["translations"]] == ["buffer"]
    assert "coverage:" in captured.err


def test_cli_pyt_syntax_error_exit_code(tmp_path: Path, capsys) -> None:
    # _cli.py:136-137 -- a .pyt with a syntax error returns rc 2.
    toolbox = tmp_path / "bad.pyt"
    toolbox.write_text("class Toolbox(:\n    pass", encoding="utf-8")

    rc = main(["pyt", str(toolbox)])

    assert rc == 2
    assert "syntax error" in capsys.readouterr().err


def test_module_main_entrypoint_runs(tmp_path: Path) -> None:
    # __main__.py -- `python -m honua_migrate.code.python scan ...` works end to end.
    script = tmp_path / "wf.py"
    script.write_text('import arcpy\narcpy.analysis.Buffer("a", "b", "1 Meter")\n', encoding="utf-8")

    result = subprocess.run(  # noqa: S603 -- sys.executable + literal args, trusted
        [sys.executable, "-m", "honua_migrate.code.python", "scan", str(script)],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)
    assert report["calls"][0]["tool"] == "Buffer"


@pytest.mark.parametrize("command", ["scan", "translate"])
def test_cli_commands_accept_stdout_default(tmp_path: Path, capsys, command: str) -> None:
    script = tmp_path / "wf.py"
    script.write_text('import arcpy\narcpy.analysis.Buffer("a", "b", "1 Meter")\n', encoding="utf-8")
    rc = main([command, str(script)])
    assert rc == 0
    assert capsys.readouterr().out
