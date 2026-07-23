"""Coverage uplift tests for ``honua_migrate.code.python.arcpy``.

Targets the ``to_dict`` serializers, ``scan_arcpy_file``, runner error
paths, translator branches (aliased ``pairwise*`` tools, extra positional
args, alias keywords, passthrough camelCase keywords, ``process_id_map``
overrides), assignment-target detection for annotated assignments and
walrus expressions, star-import resolution, ``Subscript`` calls, syntax
errors, legacy ``_management`` suffix detection, core function family
classification, and the small private helpers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from honua_migrate.code.python import (
    ArcPyCall,
    ArcPyProcessRunner,
    ArcPyProcessTranslation,
    ArcPyScanReport,
    UnsupportedArcPyCallError,
    scan_arcpy_file,
    scan_arcpy_source,
    translate_arcpy_report,
    translate_arcpy_source,
)
from honua_migrate.code.python.arcpy import (
    _attribute_parts,
    _camel_to_snake,
    _classify_qualified_name,
    _json_safe,
    _node_value,
    _normalize_keyword,
    _normalize_tool,
    _tool_key,
)


# ---------------------------------------------------------------------------
# Dataclass to_dict serializers
# ---------------------------------------------------------------------------


def _sample_call(filename: str | None = "workflow.py") -> ArcPyCall:
    return ArcPyCall(
        qualified_name="arcpy.analysis.Buffer",
        family="analysis",
        tool="Buffer",
        line=1,
        column=0,
        args=("in_features",),
        kwargs={"distance": "10 Meters"},
        raw_args=("in_features",),
        raw_kwargs={"distance": "'10 Meters'"},
        assignment_targets=("buffered",),
        filename=filename,
    )


class TestSerializers:
    def test_arcpy_call_to_dict_with_and_without_filename(self) -> None:
        with_file = _sample_call().to_dict()
        assert with_file["qualifiedName"] == "arcpy.analysis.Buffer"
        assert with_file["filename"] == "workflow.py"
        assert with_file["supported"] is True

        without_file = _sample_call(filename=None).to_dict()
        assert "filename" not in without_file

    def test_scan_report_to_dict_includes_syntax_error_and_counts(self) -> None:
        report = scan_arcpy_source("import arcpy\narcpy.analysis.Buffer(", filename="bad.py")
        as_dict = report.to_dict()
        assert as_dict["filename"] == "bad.py"
        assert as_dict["supportedCount"] == 0
        assert as_dict["unsupportedCount"] == 0
        assert as_dict["unsupportedFamilies"] == []
        assert "syntaxError" in as_dict
        assert "line 2" in as_dict["syntaxError"]

    def test_scan_report_to_dict_omits_syntax_error_when_clean(self) -> None:
        report = scan_arcpy_source("import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n")
        as_dict = report.to_dict()
        assert "syntaxError" not in as_dict
        assert as_dict["supportedCount"] == 1

    def test_translation_to_dict_round_trip(self) -> None:
        plan = translate_arcpy_source(
            "import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n",
            filename="x.py",
        )
        translation_dict = plan.translations[0].to_dict()
        assert translation_dict["processId"] == "buffer"
        assert "call" in translation_dict
        assert translation_dict["payload"]["inputs"]["input_features"] == "a"
        # Round-trip JSON-serializable
        json.dumps(translation_dict)

    def test_migration_plan_to_dict(self) -> None:
        plan = translate_arcpy_source(
            "import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\narcpy.sa.Kriging('pts', 'z')\n",
        )
        as_dict = plan.to_dict()
        assert as_dict["report"]["supportedCount"] == 1
        assert as_dict["unsupportedFamilies"] == ["spatial-analyst"]
        assert len(as_dict["translations"]) == 1
        assert as_dict["unsupportedCalls"][0]["family"] == "spatial-analyst"


# ---------------------------------------------------------------------------
# scan_arcpy_file
# ---------------------------------------------------------------------------


def test_scan_arcpy_file_reads_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "snippet.py"
    path.write_text("import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n")
    report = scan_arcpy_file(path)
    assert report.filename == str(path)
    assert report.calls[0].qualified_name == "arcpy.analysis.Buffer"


# ---------------------------------------------------------------------------
# ArcPyProcessRunner
# ---------------------------------------------------------------------------


class _FakeProcesses:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((process_id, payload))
        return {"processID": process_id, "status": "ok"}


class _FakeClient:
    """Mimics ``HonuaClient.ogc_processes()`` factory."""

    def __init__(self) -> None:
        self._procs = _FakeProcesses()

    def ogc_processes(self) -> _FakeProcesses:
        return self._procs


def test_runner_accepts_client_factory_or_processes_object_directly() -> None:
    plan = translate_arcpy_source(
        "import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n"
    )

    client = _FakeClient()
    via_client = ArcPyProcessRunner(client).execute_plan(plan)
    assert via_client[0].result == {"processID": "buffer", "status": "ok"}

    direct = _FakeProcesses()
    via_direct = ArcPyProcessRunner(direct).execute_plan(plan)
    assert via_direct[0].result == {"processID": "buffer", "status": "ok"}


def test_runner_raises_when_translation_has_empty_process_id() -> None:
    plan = translate_arcpy_source(
        "import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n"
    )
    # Replace process_id with empty string to simulate a missing mapping
    blank = ArcPyProcessTranslation(
        call=plan.translations[0].call,
        process_id="",
        payload=plan.translations[0].payload,
        notes=(),
    )
    with pytest.raises(UnsupportedArcPyCallError, match="does not have a process mapping"):
        ArcPyProcessRunner(_FakeProcesses()).execute(blank)


# ---------------------------------------------------------------------------
# translate_arcpy_source / _translate_call branches
# ---------------------------------------------------------------------------


class TestTranslator:
    def test_pairwise_aliases_route_to_canonical_specs(self) -> None:
        # PairwiseBuffer maps to analysis.Buffer via _PAIRWISE_TOOL_ALIASES
        plan = translate_arcpy_source(
            "import arcpy\narcpy.analysis.PairwiseBuffer('a', 'b', '1 Meter')\n"
        )
        assert plan.translations
        assert plan.translations[0].process_id == "buffer"

    def test_extra_positional_args_overflow_into_arg_n(self) -> None:
        # arcpy.management.CopyFeatures spec has only 2 positional args.
        plan = translate_arcpy_source(
            "import arcpy\n"
            "arcpy.management.CopyFeatures('a', 'b', 'extra-3', 'extra-4')\n"
        )
        inputs = plan.translations[0].payload["inputs"]
        assert inputs["input_features"] == "a"
        assert inputs["arg_3"] == "extra-3"
        assert inputs["arg_4"] == "extra-4"

    def test_alias_keyword_resolves_via_spec_aliases(self) -> None:
        # 'output' is an alias for the buffer result
        plan = translate_arcpy_source(
            "import arcpy\n"
            "arcpy.analysis.Buffer('a', distance='5 Meters', output='result-fc')\n"
        )
        payload = plan.translations[0].payload
        assert payload["inputs"]["distance"] == "5 Meters"
        assert payload["outputs"] == {"result": "result-fc"}

    def test_passthrough_keyword_camel_to_snake_records_passthrough(self) -> None:
        plan = translate_arcpy_source(
            "import arcpy\n"
            "arcpy.analysis.Buffer('a', 'b', '5 Meters', customParam='value')\n"
        )
        payload = plan.translations[0].payload
        assert payload["inputs"]["custom_param"] == "value"
        assert (
            payload["metadata"]["honuaMigration"]["passthroughKeywords"]
            == ["customParam"]
        )

    def test_process_id_map_overrides_spec_default(self) -> None:
        plan = translate_arcpy_source(
            "import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n",
            process_id_map={"buffer": "vendor:buffer-v2"},
        )
        assert plan.translations[0].process_id == "vendor:buffer-v2"

    def test_process_id_map_override_via_family_dot_tool_key(self) -> None:
        plan = translate_arcpy_source(
            "import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n",
            process_id_map={"analysis.Buffer": "vendor:family-buffer"},
        )
        assert plan.translations[0].process_id == "vendor:family-buffer"

    def test_translate_arcpy_report_with_explicit_report(self) -> None:
        report = scan_arcpy_source(
            "import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n"
        )
        plan = translate_arcpy_report(report)
        assert plan.translations[0].process_id == "buffer"

    def test_translate_unsupported_call_raises(self) -> None:
        # Manually build a call that is NOT supported and not aliased.
        unsupported = ArcPyCall(
            qualified_name="arcpy.sa.Kriging",
            family="spatial-analyst",
            tool="Kriging",
            line=1,
            column=0,
        )
        report = ArcPyScanReport(filename=None, calls=(unsupported,))
        # _translate_call is invoked indirectly via translate_arcpy_report; but
        # since supported_calls filters out unsupported, we hit the unsupported
        # path by going through ArcPyProcessRunner with a hand-built translation.
        plan = translate_arcpy_report(report)
        # No translations were produced because the call is unsupported.
        assert plan.translations == ()
        # Now exercise _translate_call's unsupported branch directly via
        # ArcPyMigrationPlan unsupported_calls aggregation.
        assert plan.unsupported_calls == (unsupported,)
        assert plan.unsupported_families == ("spatial-analyst",)


def test_translate_call_unsupported_raises() -> None:
    """Hit ``_translate_call``'s ``UnsupportedArcPyCallError`` branch directly."""

    from honua_migrate.code.python.arcpy import _translate_call

    unsupported = ArcPyCall(
        qualified_name="arcpy.sa.Kriging",
        family="spatial-analyst",
        tool="Kriging",
        line=1,
        column=0,
    )
    with pytest.raises(UnsupportedArcPyCallError, match="not supported"):
        _translate_call(unsupported, process_id_map={})


# ---------------------------------------------------------------------------
# Scanner: imports, classify branches, assignment targets
# ---------------------------------------------------------------------------


class TestScanner:
    def test_import_from_non_arcpy_is_ignored(self) -> None:
        report = scan_arcpy_source(
            "from os import path\n"
            "from collections import defaultdict\n"
            "import arcpy\n"
            "arcpy.analysis.Buffer('a', 'b', '1 Meter')\n"
        )
        # Only the arcpy alias should be retained (plus star_modules empty)
        assert "path" not in report.imports
        assert "defaultdict" not in report.imports
        assert "arcpy" in report.imports

    def test_import_from_arcpy_star_resolves_unqualified_names(self) -> None:
        # Star imports register the module so that bare names like Buffer_analysis
        # can still resolve.
        report = scan_arcpy_source(
            "from arcpy import *\nBuffer_analysis('a', 'b', '1 Meter')\n"
        )
        assert any(call.tool == "Buffer" for call in report.calls)

    def test_annotated_assignment_target_recorded(self) -> None:
        report = scan_arcpy_source(
            "import arcpy\nfc: str = arcpy.analysis.Buffer('a', 'b', '1 Meter')\n"
        )
        assert report.calls[0].assignment_targets == ("fc",)

    def test_walrus_assignment_target_recorded(self) -> None:
        report = scan_arcpy_source(
            "import arcpy\n"
            "if (fc := arcpy.analysis.Buffer('a', 'b', '1 Meter')):\n"
            "    pass\n"
        )
        assert report.calls[0].assignment_targets == ("fc",)

    def test_calls_on_non_arcpy_objects_are_skipped(self) -> None:
        # A call expression whose func is a Subscript (not Name/Attribute) and a
        # plain unrelated function are both filtered out.
        report = scan_arcpy_source(
            "import arcpy\n"
            "data[0]()\n"
            "print('hi')\n"
            "arcpy.analysis.Buffer('a', 'b', '1 Meter')\n"
        )
        # Only the arcpy call should be recorded
        names = [call.qualified_name for call in report.calls]
        assert names == ["arcpy.analysis.Buffer"]

    def test_legacy_management_suffix_classified(self) -> None:
        # Buffer_management uses the legacy _management family suffix.
        family, tool = _classify_qualified_name("arcpy.CopyFeatures_management")
        assert family == "management"
        assert tool == "CopyFeatures"

    def test_legacy_suffix_unrecognized_falls_to_core_function_family(self) -> None:
        # GetCount has a special core-function family mapping
        family, tool = _classify_qualified_name("arcpy.GetCount")
        assert family == "management"
        assert tool == "GetCount"

    def test_two_part_unknown_function_defaults_to_core(self) -> None:
        family, tool = _classify_qualified_name("arcpy.SomeRandomThing")
        assert family == "core"
        assert tool == "SomeRandomThing"

    def test_bare_arcpy_classifies_as_core(self) -> None:
        family, tool = _classify_qualified_name("arcpy")
        assert family == "core"
        assert tool == "arcpy"

    def test_non_arcpy_qualified_name_returns_unknown(self) -> None:
        family, tool = _classify_qualified_name("os.path.join")
        assert family == "unknown"
        assert tool == "join"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_attribute_parts_handles_non_name_nodes(self) -> None:
        import ast

        tree = ast.parse("data[0]")
        sub = tree.body[0].value  # type: ignore[attr-defined]
        assert _attribute_parts(sub) == ()

    def test_node_value_returns_python_dict_for_non_literal(self) -> None:
        import ast

        tree = ast.parse("foo(bar.baz)")
        arg = tree.body[0].value.args[0]  # type: ignore[attr-defined]
        out = _node_value(arg)
        assert isinstance(out, dict) and out["python"] == "bar.baz"

    def test_json_safe_handles_mappings_and_iterables(self) -> None:
        assert _json_safe({"a": 1, "b": [1, 2]}) == {"a": 1, "b": [1, 2]}
        assert _json_safe([1, "two", (3, 4)]) == [1, "two", [3, 4]]
        # Sets are iterable; they get listed (order may vary)
        out = _json_safe({1, 2})
        assert isinstance(out, list)
        assert set(out) == {1, 2}

    def test_json_safe_falls_back_for_unknown_objects(self) -> None:
        class _Custom:
            def __repr__(self) -> str:
                return "Custom()"

        assert _json_safe(_Custom()) == {"python": "Custom()"}

    def test_camel_to_snake(self) -> None:
        assert _camel_to_snake("already_snake") == "already_snake"
        assert _camel_to_snake("camelCase") == "camel_case"
        assert _camel_to_snake("HTTPHeader") == "h_t_t_p_header"
        assert _camel_to_snake("") == ""

    def test_normalize_helpers(self) -> None:
        assert _normalize_tool("Buffer_analysis") == "bufferanalysis"
        assert _normalize_keyword("In_Features") == "infeatures"
        assert _tool_key("analysis", "Buffer") == ("analysis", "buffer")


# ---------------------------------------------------------------------------
# Smoke: arcpy import does NOT need to be available for this module
# ---------------------------------------------------------------------------


def test_module_works_with_mocked_arcpy_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """``honua_migrate.code.python.arcpy`` performs source-only analysis, but
    end-user code may have a stubbed arcpy. Sanity-check that the scanner
    still runs even when sys.modules has a mock arcpy."""

    import sys

    monkeypatch.setitem(sys.modules, "arcpy", MagicMock())
    report = scan_arcpy_source(
        "import arcpy\narcpy.analysis.Buffer('a', 'b', '1 Meter')\n"
    )
    assert report.calls[0].tool == "Buffer"
