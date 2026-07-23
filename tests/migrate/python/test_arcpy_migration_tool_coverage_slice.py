"""Focused tests for the expanded ArcPy tool-coverage slice (issue #82).

Covers the newly registered vector tools:

* ``analysis.GraphicBuffer`` -> ``geometry.buffer`` (translatable, like Buffer),
* ``management.MinimumBoundingGeometry`` -> ``geometry.convex-hull``
  (supported but not job-executable -> manual-review; the geometry_type caveat
  is surfaced via spec notes),
* ``management.FeatureToPoint`` -> ``geometry.centroid`` (manual-review),
* ``analysis.SymDiff`` -> ``symmetric-difference`` (manual-review),
* ``analysis.Update`` -> ``update`` (manual-review),

and confirms unmapped calls still emit ``unsupported`` verdicts.
"""

from __future__ import annotations

from honua_migrate.code.python import (
    EXECUTABLE_PROCESS_IDS,
    scan_arcpy_source,
    translate_arcpy_source,
)


def _only_call(source: str):
    report = scan_arcpy_source("import arcpy\n" + source)
    (call,) = report.calls
    return call


def test_graphic_buffer_is_translatable_to_geometry_buffer() -> None:
    call = _only_call('arcpy.analysis.GraphicBuffer("roads", "rb", "25 Meters")')
    assert call.supported is True
    assert call.status == "translatable"
    assert call.process_id == "buffer"
    assert call.job_process_id == "geometry.buffer"
    assert call.job_process_id in EXECUTABLE_PROCESS_IDS


def test_graphic_buffer_payload_carries_inputs_and_output() -> None:
    plan = translate_arcpy_source(
        'import arcpy\narcpy.analysis.GraphicBuffer("roads", "rb", "25 Meters", line_caps="SQUARE")'
    )
    (translation,) = plan.translations
    assert translation.process_id == "buffer"
    assert translation.job_process_id == "geometry.buffer"
    assert translation.payload["inputs"]["input_features"] == "roads"
    assert translation.payload["inputs"]["distance"] == "25 Meters"
    assert translation.payload["inputs"]["line_caps"] == "SQUARE"
    assert translation.payload["outputs"]["result"] == "rb"


def test_minimum_bounding_geometry_convex_hull_is_manual_review() -> None:
    call = _only_call(
        'arcpy.management.MinimumBoundingGeometry("in", "out", "CONVEX_HULL")'
    )
    assert call.supported is True
    assert call.translatable is False
    assert call.status == "manual-review"
    assert call.process_id == "convex-hull"
    assert call.job_process_id is None
    # Not job-executable -> generic manual-review reason (gate cannot run here).
    assert call.manual_review_reason is not None


def test_minimum_bounding_geometry_geometry_type_caveat_is_in_notes() -> None:
    # The geometry_type caveat is surfaced via spec notes (gates only run for
    # job-executable specs), so parity evidence carries it.
    from honua_migrate.code.python import build_parity_evidence_for_source

    evidence = build_parity_evidence_for_source(
        'import arcpy\narcpy.management.MinimumBoundingGeometry("in", "out", "ENVELOPE")'
    )
    (entry,) = evidence["calls"]
    assert entry["status"] == "manual-review"
    notes = " ".join(entry.get("notes", []))
    assert "CONVEX_HULL" in notes
    assert "ENVELOPE" in notes


def test_feature_to_point_is_manual_review_centroid() -> None:
    call = _only_call('arcpy.management.FeatureToPoint("in", "out", "INSIDE")')
    assert call.supported is True
    assert call.status == "manual-review"
    assert call.process_id == "centroid"
    assert call.job_process_id is None


def test_symdiff_is_manual_review() -> None:
    call = _only_call('arcpy.analysis.SymDiff("a", "b", "out")')
    assert call.supported is True
    assert call.status == "manual-review"
    assert call.process_id == "symmetric-difference"
    assert call.job_process_id is None


def test_update_is_manual_review() -> None:
    call = _only_call('arcpy.analysis.Update("a", "b", "out")')
    assert call.supported is True
    assert call.status == "manual-review"
    assert call.process_id == "update"
    assert call.job_process_id is None


def test_unmapped_tool_still_unsupported() -> None:
    call = _only_call('arcpy.management.AddField("in", "fld", "TEXT")')
    assert call.supported is False
    assert call.status == "unsupported"
    assert call.process_id is None
    assert call.job_process_id is None


def test_new_specs_do_not_inflate_executable_catalog() -> None:
    # The executable catalog is locked to the reconciled-server job processes;
    # new supported-but-not-executable tools must not leak into it.
    from honua_migrate.code.python.arcpy import _SUPPORTED_TOOL_SPECS

    for spec in _SUPPORTED_TOOL_SPECS.values():
        if spec.job_process_id is not None:
            assert spec.job_process_id in EXECUTABLE_PROCESS_IDS
