"""Tests for migration status classification and parity-evidence emission.

These cover the reconciled-server mappings (honua-server#1228): the
job-executable namespaced process catalog, executable-gated coverage, the
SpatialJoin one-to-one gate, and the Erase semantics-mismatch manual-review.
"""

from __future__ import annotations

import pytest

from honua_migrate.code.python import (
    EXECUTABLE_PROCESS_IDS,
    build_parity_evidence,
    build_parity_evidence_for_source,
    scan_arcpy_source,
    translate_arcpy_source,
)

# Mix of: executable geometry targets (buffer, simplify, dissolve, make-valid),
# an executable managed analytics target (spatial-join, one-to-one form), a
# known-but-not-job-executable target (Erase -> manual-review due to
# feature-class-vs-single-geometry semantics), and a wholly unmapped tool
# (sa.Slope).
MIXED_SOURCE = """
import arcpy

arcpy.analysis.Buffer("roads", "rb", "25 Meters")
arcpy.cartography.SimplifyPolygon("poly", "poly_s", "POINT_REMOVE", "10 Meters")
arcpy.management.Dissolve("rb", "rb_d", "CLASS")
arcpy.management.RepairGeometry("rb_d")
arcpy.analysis.SpatialJoin("a", "b", "joined")
arcpy.analysis.Erase("a", "b", "c")
arcpy.sa.Slope("dem")
"""


def test_migration_is_reachable_from_top_level_package() -> None:
    import honua_sdk
    from honua_sdk import migration

    assert migration is honua_migrate.code.python
    assert hasattr(migration, "scan_arcpy_source")
    assert hasattr(migration, "build_parity_evidence")
    assert hasattr(migration, "parse_pyt_source")
    assert isinstance(migration.EXECUTABLE_PROCESS_IDS, frozenset)


def test_executable_set_is_the_reconciled_server_job_catalog() -> None:
    # The executable set is the reconciled server's namespaced job-process
    # catalog -- NOT the bare OGC ids. Guards against coverage inflation.
    assert EXECUTABLE_PROCESS_IDS == frozenset(
        {
            "geometry.buffer",
            "geometry.project",
            "geometry.simplify",
            "geometry.clip",
            "geometry.intersect",
            "geometry.union",
            "geometry.dissolve",
            "geometry.make-valid",
            "analytics.spatial-join-managed",
        }
    )


def test_translations_keep_bare_ogc_ids_and_carry_job_ids() -> None:
    plan = translate_arcpy_source(MIXED_SOURCE, filename="mixed.py")

    # The OGC run path keeps bare process ids for every supported call.
    assert [t.process_id for t in plan.translations] == [
        "buffer",
        "simplify",
        "dissolve",
        "make-valid",
        "spatial-join",
        "erase",
    ]
    # Translatable calls carry a reconciled-server job id; non-executable ones
    # (Erase) carry job_process_id=None.
    by_tool = {t.call.tool: t for t in plan.translations}
    assert by_tool["Buffer"].job_process_id == "geometry.buffer"
    assert by_tool["SimplifyPolygon"].job_process_id == "geometry.simplify"
    assert by_tool["Dissolve"].job_process_id == "geometry.dissolve"
    assert by_tool["RepairGeometry"].job_process_id == "geometry.make-valid"
    assert by_tool["SpatialJoin"].job_process_id == "analytics.spatial-join-managed"
    assert by_tool["Erase"].job_process_id is None
    # Every emitted job id is in the reconciled executable catalog.
    for translation in plan.translations:
        if translation.job_process_id is not None:
            assert translation.job_process_id in EXECUTABLE_PROCESS_IDS


def test_status_partitions_into_translatable_manual_unsupported() -> None:
    report = scan_arcpy_source(MIXED_SOURCE, filename="mixed.py")

    translatable = {(c.family, c.tool) for c in report.translatable_calls}
    manual = {(c.family, c.tool) for c in report.manual_review_calls}
    unsupported = {(c.family, c.tool) for c in report.unsupported_calls}

    assert ("analysis", "Buffer") in translatable
    assert ("cartography", "SimplifyPolygon") in translatable
    assert ("management", "Dissolve") in translatable
    assert ("management", "RepairGeometry") in translatable
    # One-to-one SpatialJoin maps to the managed analytics process.
    assert ("analysis", "SpatialJoin") in translatable
    # Erase is mapped (supported) but not job-executable -> manual-review.
    assert ("analysis", "Erase") in manual
    # sa.Slope has no Honua mapping at all.
    assert ("spatial-analyst", "Slope") in unsupported
    # The three buckets are disjoint.
    assert translatable.isdisjoint(manual)
    assert translatable.isdisjoint(unsupported)
    assert manual.isdisjoint(unsupported)


def test_erase_is_manual_review_due_to_semantics_mismatch() -> None:
    report = scan_arcpy_source('import arcpy\narcpy.analysis.Erase("a", "b", "c")')
    (call,) = report.calls

    assert call.supported is True
    assert call.translatable is False
    assert call.status == "manual-review"
    assert call.process_id == "erase"
    assert call.job_process_id is None
    assert call.manual_review_reason is not None


def test_spatial_join_one_to_many_is_downgraded_to_manual_review() -> None:
    report = scan_arcpy_source(
        'import arcpy\n'
        'arcpy.analysis.SpatialJoin("t", "j", "o", join_operation="JOIN_ONE_TO_MANY")\n'
    )
    (call,) = report.calls
    assert call.status == "manual-review"
    assert call.job_process_id == "analytics.spatial-join-managed"
    assert "JOIN_ONE_TO_MANY" in (call.manual_review_reason or "")


def test_spatial_join_keep_common_is_downgraded_to_manual_review() -> None:
    report = scan_arcpy_source(
        'import arcpy\n'
        'arcpy.analysis.SpatialJoin("t", "j", "o", join_type="KEEP_COMMON")\n'
    )
    (call,) = report.calls
    assert call.status == "manual-review"
    assert "KEEP_COMMON" in (call.manual_review_reason or "")


def test_spatial_join_one_to_one_is_translatable() -> None:
    report = scan_arcpy_source(
        'import arcpy\n'
        'arcpy.analysis.SpatialJoin("t", "j", "o", join_operation="JOIN_ONE_TO_ONE", join_type="KEEP_ALL")\n'
    )
    (call,) = report.calls
    assert call.status == "translatable"
    assert call.job_process_id == "analytics.spatial-join-managed"


def test_parity_evidence_report_shape_and_coverage() -> None:
    evidence = build_parity_evidence_for_source(MIXED_SOURCE, filename="mixed.py")

    assert evidence["schema"] == "honua.migration.arcpy.parity-evidence/v1"
    assert evidence["source"] == "mixed.py"

    summary = evidence["summary"]
    assert summary["totalCalls"] == 7
    # Buffer, SimplifyPolygon, Dissolve, RepairGeometry, SpatialJoin (1:1) = 5.
    assert summary["translatableCalls"] == 5
    assert summary["manualReviewCalls"] == 1  # Erase
    assert summary["unsupportedCalls"] == 1  # Slope
    assert summary["coveragePercent"] == round(100.0 * 5 / 7, 2)
    assert summary["executableProcessIds"] == sorted(EXECUTABLE_PROCESS_IDS)

    by_tool = {(c["family"], c["tool"]): c for c in evidence["calls"]}
    # Translatable calls carry a runnable payload + the job id.
    assert "payload" in by_tool[("analysis", "Buffer")]
    assert by_tool[("analysis", "Buffer")]["jobProcessId"] == "geometry.buffer"
    assert by_tool[("analysis", "SpatialJoin")]["jobProcessId"] == "analytics.spatial-join-managed"
    # Manual-review calls carry a reason but no payload.
    erase = by_tool[("analysis", "Erase")]
    assert erase["status"] == "manual-review"
    assert "payload" not in erase
    assert erase["reason"]
    # Unsupported calls carry a reason explaining there is no mapping.
    slope = by_tool[("spatial-analyst", "Slope")]
    assert slope["status"] == "unsupported"
    assert slope["processId"] is None
    assert slope["jobProcessId"] is None
    assert "No Honua process mapping" in slope["reason"]

    tool_status = {(t["family"], t["tool"]): t for t in evidence["toolStatus"]}
    assert tool_status[("analysis", "Buffer")]["status"] == "translatable"
    assert tool_status[("analysis", "Erase")]["status"] == "manual-review"


def test_parity_evidence_counts_duplicate_calls_per_tool() -> None:
    src = """
import arcpy
arcpy.analysis.Buffer("a", "b", "1 Meters")
arcpy.analysis.Buffer("c", "d", "2 Meters")
"""
    evidence = build_parity_evidence(translate_arcpy_source(src))
    buffer_status = next(t for t in evidence["toolStatus"] if t["tool"] == "Buffer")
    assert buffer_status["count"] == 2
    assert evidence["summary"]["coveragePercent"] == 100.0


def test_parity_evidence_handles_syntax_error() -> None:
    evidence = build_parity_evidence_for_source("import arcpy\narcpy.analysis.Buffer(", filename="bad.py")
    assert evidence["syntaxError"] is not None
    assert evidence["summary"]["totalCalls"] == 0
    assert evidence["summary"]["coveragePercent"] == 0.0


# Exact ArcPy tool -> (OGC bare id, reconciled job id, job-executable?) table
# after re-pointing to the reconciled server catalog (honua-server#1228).
_REPOINTED_MAPPINGS = [
    ('arcpy.analysis.Buffer("a", "b", "1 Meter")', "Buffer", "buffer", "geometry.buffer", True),
    ('arcpy.management.Project("a", "b", 4326)', "Project", "project", "geometry.project", True),
    ('arcpy.cartography.SimplifyPolygon("a", "b", "POINT_REMOVE", "1 Meter")', "SimplifyPolygon", "simplify", "geometry.simplify", True),
    ('arcpy.cartography.SimplifyLine("a", "b", "POINT_REMOVE", "1 Meter")', "SimplifyLine", "simplify", "geometry.simplify", True),
    ('arcpy.analysis.Clip("a", "b", "c")', "Clip", "clip", "geometry.clip", True),
    ('arcpy.analysis.Intersect(["a", "b"], "c")', "Intersect", "intersect", "geometry.intersect", True),
    ('arcpy.analysis.Union(["a", "b"], "c")', "Union", "union", "geometry.union", True),
    ('arcpy.management.Dissolve("a", "b", "CLASS")', "Dissolve", "dissolve", "geometry.dissolve", True),
    ('arcpy.management.RepairGeometry("a")', "RepairGeometry", "make-valid", "geometry.make-valid", True),
    ('arcpy.analysis.SpatialJoin("a", "b", "c")', "SpatialJoin", "spatial-join", "analytics.spatial-join-managed", True),
    # Erase stays manual-review: semantics differ from geometry.difference.
    ('arcpy.analysis.Erase("a", "b", "c")', "Erase", "erase", None, False),
]


@pytest.mark.parametrize(
    "source_line,tool,ogc_id,job_id,executable",
    _REPOINTED_MAPPINGS,
)
def test_repointed_arcpy_to_process_mappings(source_line, tool, ogc_id, job_id, executable) -> None:
    report = scan_arcpy_source(f"import arcpy\n{source_line}\n")
    (call,) = report.calls
    assert call.tool == tool
    assert call.process_id == ogc_id, f"{tool} OGC id"
    assert call.job_process_id == job_id, f"{tool} job id"
    assert call.translatable is executable, f"{tool} executable"
    if executable:
        assert job_id in EXECUTABLE_PROCESS_IDS
    else:
        assert job_id is None or job_id not in EXECUTABLE_PROCESS_IDS
