"""ArcPy migration scanner and OGC Processes translation helpers.

The scanner works from Python source text only. It does not import ``arcpy``
or require an ArcGIS Pro installation, which makes it suitable for CI and
inventory work on developer machines without licensed Esri software.
"""

from __future__ import annotations

import ast
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

JsonObject = dict[str, Any]
JsonValue = str | int | float | bool | None | JsonObject | list[Any]
InputKind = Literal["input", "output", "parameter"]
MigrationStatus = Literal["translatable", "manual-review", "unsupported"]


#: Honua process identifiers the reconciled honua-server geoprocessing runtime
#: can actually *job-execute* today (honua-server#1228). These are the
#: namespaced job/run-path process ids -- distinct from the bare OGC API
#: Processes ids used by :class:`ArcPyProcessRunner`. A registered ArcPy tool
#: spec is only classified ``"translatable"`` (a clean, server-runnable
#: migration) when its ``job_process_id`` is in this set. Tools whose Honua
#: target is not job-executable are emitted as ``"manual-review"`` so the
#: codemod never claims a migration the server cannot run.
#:
#: IMPORTANT (coverage<=server-execution coupling): grow this set ONLY when the
#: reconciled server gains a corresponding job-executable process. Migration
#: coverage is gated on it, not on how many ArcPy tools we can parse.
EXECUTABLE_PROCESS_IDS: frozenset[str] = frozenset(
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


@dataclass(frozen=True)
class ArcPyCall:
    """One ArcPy call discovered in Python source text."""

    qualified_name: str
    family: str
    tool: str
    line: int
    column: int
    args: tuple[JsonValue, ...] = ()
    kwargs: Mapping[str, JsonValue] = field(default_factory=dict)
    expanded_kwargs: tuple[JsonValue, ...] = ()
    raw_args: tuple[str, ...] = ()
    raw_kwargs: Mapping[str, str] = field(default_factory=dict)
    raw_expanded_kwargs: tuple[str, ...] = ()
    assignment_targets: tuple[str, ...] = ()
    filename: str | None = None

    @property
    def _spec(self) -> _ToolSpec | None:
        return _lookup_spec(self.family, self.tool)

    @property
    def supported(self) -> bool:
        """Return whether the call has a first-slice Honua process mapping.

        ``supported`` means "we know which Honua OGC process this maps to",
        which is broader than :attr:`translatable`. A supported-but-not-yet
        -job-executable tool is classified ``"manual-review"``.
        """

        return _tool_key(self.family, self.tool) in _SUPPORTED_TOOL_SPECS

    @property
    def status(self) -> MigrationStatus:
        """Migration status for this call.

        * ``"translatable"`` -- a registered tool whose Honua job target is
          executable by the reconciled server today (see
          :data:`EXECUTABLE_PROCESS_IDS`).
        * ``"manual-review"`` -- a registered tool whose job target is not yet
          executable, so it is emitted for human migration rather than a
          server-runnable claim.
        * ``"unsupported"`` -- no Honua mapping exists for this ArcPy call.
        """

        spec = self._spec
        if spec is None:
            return "unsupported"
        return spec.status_for(self)[0]

    @property
    def manual_review_reason(self) -> str | None:
        """Why this call is manual-review (or ``None`` when not manual-review)."""

        spec = self._spec
        if spec is None:
            return None
        status, reason = spec.status_for(self)
        return reason if status == "manual-review" else None

    @property
    def translatable(self) -> bool:
        """Whether this call maps to a Honua process the server can job-execute."""

        return self.status == "translatable"

    @property
    def process_id(self) -> str | None:
        """Target Honua OGC API Processes id, when a mapping exists."""

        spec = self._spec
        return spec.process_id if spec is not None else None

    @property
    def job_process_id(self) -> str | None:
        """Reconciled-server job-executable process id, when one exists."""

        spec = self._spec
        return spec.job_process_id if spec is not None else None

    def to_dict(self) -> JsonObject:
        """Return a JSON-serializable call inventory entry."""

        result: JsonObject = {
            "qualifiedName": self.qualified_name,
            "family": self.family,
            "tool": self.tool,
            "line": self.line,
            "column": self.column,
            "supported": self.supported,
            "status": self.status,
            "processId": self.process_id,
            "jobProcessId": self.job_process_id,
            "args": list(self.args),
            "kwargs": dict(self.kwargs),
            "rawArgs": list(self.raw_args),
            "rawKwargs": dict(self.raw_kwargs),
            "assignmentTargets": list(self.assignment_targets),
        }
        if self.expanded_kwargs:
            result["expandedKwargs"] = list(self.expanded_kwargs)
            result["rawExpandedKwargs"] = list(self.raw_expanded_kwargs)
        if self.filename is not None:
            result["filename"] = self.filename
        return result


@dataclass(frozen=True)
class ArcPyScanReport:
    """ArcPy source inventory produced by :func:`scan_arcpy_source`."""

    filename: str | None
    calls: tuple[ArcPyCall, ...]
    imports: Mapping[str, str] = field(default_factory=dict)
    syntax_error: str | None = None

    @property
    def supported_calls(self) -> tuple[ArcPyCall, ...]:
        """Calls with any known Honua OGC process mapping (registered)."""

        return tuple(call for call in self.calls if call.supported)

    @property
    def translatable_calls(self) -> tuple[ArcPyCall, ...]:
        """Calls mapping to a Honua process the reconciled server can run."""

        return tuple(call for call in self.calls if call.translatable)

    @property
    def manual_review_calls(self) -> tuple[ArcPyCall, ...]:
        """Calls with a known mapping whose job target is not yet executable."""

        return tuple(call for call in self.calls if call.status == "manual-review")

    @property
    def unsupported_calls(self) -> tuple[ArcPyCall, ...]:
        """Calls that were classified but do not have a process mapping yet."""

        return tuple(call for call in self.calls if call.status == "unsupported")

    @property
    def unsupported_families(self) -> tuple[str, ...]:
        """Sorted unsupported ArcPy families represented in the scan."""

        return tuple(sorted({call.family for call in self.unsupported_calls}))

    def to_dict(self) -> JsonObject:
        """Return a JSON-serializable scan report."""

        result: JsonObject = {
            "filename": self.filename,
            "imports": dict(self.imports),
            "calls": [call.to_dict() for call in self.calls],
            "supportedCount": len(self.supported_calls),
            "translatableCount": len(self.translatable_calls),
            "manualReviewCount": len(self.manual_review_calls),
            "unsupportedCount": len(self.unsupported_calls),
            "unsupportedFamilies": list(self.unsupported_families),
        }
        if self.syntax_error is not None:
            result["syntaxError"] = self.syntax_error
        return result


@dataclass(frozen=True)
class ArcPyProcessTranslation:
    """A supported ArcPy call expressed as an OGC API Processes execution.

    ``process_id`` is the bare OGC API Processes id that
    :class:`ArcPyProcessRunner` executes against ``/ogc/processes``.
    ``job_process_id`` is the reconciled server's namespaced job-executable id
    (honua-server#1228) for GP/run-path targeting; it is ``None`` for tools the
    server cannot job-execute.
    """

    call: ArcPyCall
    process_id: str
    payload: JsonObject
    notes: tuple[str, ...] = ()
    job_process_id: str | None = None

    def to_dict(self) -> JsonObject:
        """Return a JSON-serializable translation entry."""

        return {
            "call": self.call.to_dict(),
            "processId": self.process_id,
            "jobProcessId": self.job_process_id,
            "payload": self.payload,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ArcPyMigrationPlan:
    """Scan report plus supported process translations."""

    report: ArcPyScanReport
    translations: tuple[ArcPyProcessTranslation, ...]

    @property
    def manual_review_calls(self) -> tuple[ArcPyCall, ...]:
        """Calls with a Honua mapping the reconciled server cannot yet run."""

        return self.report.manual_review_calls

    @property
    def unsupported_calls(self) -> tuple[ArcPyCall, ...]:
        """Calls left for manual migration or later translator slices."""

        return self.report.unsupported_calls

    @property
    def unsupported_families(self) -> tuple[str, ...]:
        """Sorted unsupported ArcPy families represented in the plan."""

        return self.report.unsupported_families

    def to_dict(self) -> JsonObject:
        """Return a JSON-serializable migration plan."""

        return {
            "report": self.report.to_dict(),
            "translations": [translation.to_dict() for translation in self.translations],
            "manualReviewCalls": [call.to_dict() for call in self.manual_review_calls],
            "unsupportedCalls": [call.to_dict() for call in self.unsupported_calls],
            "unsupportedFamilies": list(self.unsupported_families),
        }


# OGC API - Processes job status values (Part 1, /req/job-list/job-list-success).
JOB_STATUS_ACCEPTED = "accepted"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCESSFUL = "successful"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_DISMISSED = "dismissed"

_TERMINAL_JOB_STATUSES = frozenset(
    {JOB_STATUS_SUCCESSFUL, JOB_STATUS_FAILED, JOB_STATUS_DISMISSED}
)
_SYNC_COMPLETE_STATUSES = frozenset({JOB_STATUS_SUCCESSFUL, "succeeded", "ok", "complete", "completed"})


@dataclass(frozen=True)
class ArcPyProcessExecution:
    """Result returned after executing one translated OGC process.

    For synchronous execution ``result`` holds the immediate process response
    and ``job_id``/``status``/``results`` stay ``None``. For asynchronous
    execution ``job_id`` is the polled job identifier, ``status`` is the final
    OGC job status, ``result`` is the terminal job status document, and
    ``results`` is the downloaded results document when the job succeeded.
    """

    translation: ArcPyProcessTranslation
    result: JsonObject
    job_id: str | None = None
    status: str | None = None
    results: JsonObject | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether the execution reached a successful terminal state."""

        if self.status is None:
            return _job_status(self.result) in _SYNC_COMPLETE_STATUSES or _job_status(self.result) is None
        return _normalize_status(self.status) == JOB_STATUS_SUCCESSFUL

    def to_dict(self) -> JsonObject:
        """Return a JSON-serializable execution evidence record."""

        record: JsonObject = {
            "translation": self.translation.to_dict(),
            "result": self.result,
            "succeeded": self.succeeded,
        }
        if self.job_id is not None:
            record["jobId"] = self.job_id
        if self.status is not None:
            record["status"] = self.status
        if self.results is not None:
            record["results"] = self.results
        return record


class UnsupportedArcPyCallError(ValueError):
    """Raised when a runner is asked to execute an unsupported ArcPy call."""


class ArcPyJobError(RuntimeError):
    """Raised when a translated process job ends in a failed/dismissed state."""

    def __init__(self, job_id: str | None, status: str, document: JsonObject) -> None:
        self.job_id = job_id
        self.status = status
        self.document = document
        label = f"job {job_id!r}" if job_id else "process job"
        super().__init__(f"ArcPy migration {label} ended with status {status!r}.")


class ArcPyJobTimeoutError(RuntimeError):
    """Raised when a translated process job does not reach a terminal state."""

    def __init__(self, job_id: str | None, status: str | None, polls: int) -> None:
        self.job_id = job_id
        self.status = status
        self.polls = polls
        label = f"job {job_id!r}" if job_id else "process job"
        super().__init__(
            f"ArcPy migration {label} did not finish after {polls} poll(s) "
            f"(last status {status!r})."
        )


@dataclass(frozen=True)
class _ArgSpec:
    arcpy_name: str
    process_name: str
    kind: InputKind = "parameter"


#: A per-call gate may downgrade an otherwise-executable tool to manual-review
#: for argument forms the reconciled server cannot job-execute. It returns a
#: ``(status, reason)`` pair; ``reason`` is ``None`` when the call passes.
_GateResult = tuple[MigrationStatus, "str | None"]


@dataclass(frozen=True)
class _ToolSpec:
    family: str
    tool: str
    process_id: str
    args: tuple[_ArgSpec, ...]
    aliases: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    #: Reconciled-server job-executable process id (honua-server#1228), or
    #: ``None`` when the server cannot job-execute this tool yet. Distinct from
    #: ``process_id`` (the bare OGC API Processes id the runner POSTs to).
    job_process_id: str | None = None
    #: Optional per-call gate. When set and the spec is otherwise executable,
    #: the gate may downgrade specific argument forms to ``"manual-review"``.
    gate: "Callable[[ArcPyCall], _GateResult] | None" = None

    @property
    def executable(self) -> bool:
        """Whether the reconciled server can job-execute the target process."""

        return self.job_process_id is not None and self.job_process_id in EXECUTABLE_PROCESS_IDS

    @property
    def status(self) -> MigrationStatus:
        """Spec-level status from reconciled-server job-executability.

        This ignores any per-call :attr:`gate`; use :meth:`status_for` for the
        call-aware status that drives translation/coverage.
        """

        return "translatable" if self.executable else "manual-review"

    def status_for(self, call: ArcPyCall) -> _GateResult:
        """Call-aware ``(status, reason)`` honoring any per-call gate."""

        if not self.executable:
            return "manual-review", (
                f"Honua process {self.job_process_id!r} is not job-executable by "
                "the reconciled server yet."
                if self.job_process_id is not None
                else "No job-executable Honua process is mapped for this ArcPy tool yet."
            )
        if self.gate is not None:
            return self.gate(call)
        return "translatable", None


def _arg(arcpy_name: str, process_name: str | None = None, *, kind: InputKind = "parameter") -> _ArgSpec:
    return _ArgSpec(arcpy_name=arcpy_name, process_name=process_name or arcpy_name, kind=kind)


_PAIRWISE_TOOL_ALIASES: Mapping[tuple[str, str], tuple[str, str]] = {}


def _normalize_tool(tool: str) -> str:
    return "".join(character for character in tool.lower() if character.isalnum())


def _normalize_keyword(keyword: str) -> str:
    return "".join(character for character in keyword.lower() if character.isalnum())


def _tool_key(family: str, tool: str) -> tuple[str, str]:
    normalized = (family, _normalize_tool(tool))
    return _PAIRWISE_TOOL_ALIASES.get(normalized, normalized)


def _aliases(*pairs: tuple[str, str]) -> dict[str, str]:
    return {_normalize_keyword(arcpy): process for arcpy, process in pairs}


_SUPPORTED_TOOL_SPECS: dict[tuple[str, str], _ToolSpec] = {}


def _register(spec: _ToolSpec) -> _ToolSpec:
    _SUPPORTED_TOOL_SPECS[_tool_key(spec.family, spec.tool)] = spec
    return spec


def _call_argument(call: ArcPyCall, position: int, *arcpy_names: str) -> JsonValue:
    """Resolve a call argument by positional index or any of its keyword names."""

    for name in arcpy_names:
        normalized = _normalize_keyword(name)
        for raw_name, value in call.kwargs.items():
            if _normalize_keyword(raw_name) == normalized:
                return value
    if 0 <= position < len(call.args):
        return call.args[position]
    return None


def _spatial_join_gate(call: ArcPyCall) -> _GateResult:
    """Gate ``SpatialJoin`` to the one-to-one summarizing form.

    The reconciled server's ``analytics.spatial-join-managed`` job-executes the
    one-to-one summarizing join. ArcGIS ``JOIN_ONE_TO_MANY`` fan-out and
    ``KEEP_COMMON`` (inner) join forms are not inlinable into the managed
    process, so they are downgraded to manual-review with a reason.
    """

    join_operation = _call_argument(call, 3, "join_operation")
    if isinstance(join_operation, str) and join_operation.strip().upper() == "JOIN_ONE_TO_MANY":
        return "manual-review", (
            "SpatialJoin JOIN_ONE_TO_MANY fans out rows and is not inlinable into "
            "analytics.spatial-join-managed (one-to-one summarizing) -- migrate manually."
        )

    join_type = _call_argument(call, 4, "join_type")
    if isinstance(join_type, str) and join_type.strip().upper() == "KEEP_COMMON":
        return "manual-review", (
            "SpatialJoin KEEP_COMMON (inner) join is a non-inlinable join input for "
            "analytics.spatial-join-managed -- migrate manually."
        )

    return "translatable", None


_register(
    _ToolSpec(
        family="analysis",
        tool="Buffer",
        process_id="buffer",
        job_process_id="geometry.buffer",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("buffer_distance_or_field", "distance"),
            _arg("line_side", "line_side"),
            _arg("line_end_type", "line_end_type"),
            _arg("dissolve_option", "dissolve_option"),
            _arg("dissolve_field", "dissolve_fields"),
            _arg("method", "method"),
        ),
        aliases=_aliases(
            ("input_features", "input_features"),
            ("distance", "distance"),
            ("output", "result"),
            ("out_features", "result"),
        ),
    )
)
_register(
    _ToolSpec(
        family="analysis",
        tool="Clip",
        process_id="clip",
        job_process_id="geometry.clip",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("clip_features", "clip_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("cluster_tolerance", "cluster_tolerance"),
        ),
        aliases=_aliases(("output", "result"), ("out_features", "result")),
    )
)
_register(
    _ToolSpec(
        family="analysis",
        tool="Intersect",
        process_id="intersect",
        job_process_id="geometry.intersect",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("join_attributes", "join_attributes"),
            _arg("cluster_tolerance", "cluster_tolerance"),
            _arg("output_type", "output_type"),
        ),
        aliases=_aliases(("inputs", "input_features"), ("output", "result"), ("out_features", "result")),
    )
)
_register(
    _ToolSpec(
        family="analysis",
        tool="Erase",
        process_id="erase",
        # Intentionally NOT job-executable: ArcGIS Erase subtracts the *union of
        # the whole erase feature class* from each input feature, whereas the
        # reconciled server's geometry.difference is a single-geometry pairwise
        # subtract. The feature-class-vs-single-geometry semantics differ, so
        # Erase stays manual-review rather than claiming a false migration.
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("erase_features", "erase_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("cluster_tolerance", "cluster_tolerance"),
        ),
        aliases=_aliases(("output", "result"), ("out_features", "result")),
        notes=(
            "ArcGIS Erase subtracts the union of the erase feature class from "
            "each input feature; geometry.difference is single-geometry subtract. "
            "Semantics differ -- migrate manually (per honua-server#1228 review).",
        ),
    )
)
_register(
    _ToolSpec(
        family="analysis",
        tool="Union",
        process_id="union",
        job_process_id="geometry.union",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("join_attributes", "join_attributes"),
            _arg("cluster_tolerance", "cluster_tolerance"),
            _arg("gaps", "gaps"),
        ),
        aliases=_aliases(("inputs", "input_features"), ("output", "result"), ("out_features", "result")),
    )
)
_register(
    _ToolSpec(
        family="analysis",
        tool="SpatialJoin",
        # OGC bare id stays "spatial-join" (PostGIS-protocol path). The reconciled
        # server job-executes spatial joins only via the NEW managed process
        # analytics.spatial-join-managed (honua-server#1228); trunk's plain
        # analytics.spatial-join is protocol-only and NOT reachable by run/job.
        process_id="spatial-join",
        job_process_id="analytics.spatial-join-managed",
        args=(
            _arg("target_features", "target_features", kind="input"),
            _arg("join_features", "join_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("join_operation", "join_operation"),
            _arg("join_type", "join_type"),
            _arg("field_mapping", "field_mapping"),
            _arg("match_option", "match_option"),
            _arg("search_radius", "search_radius"),
            _arg("distance_field_name", "distance_field_name"),
            _arg("match_fields", "match_fields"),
        ),
        aliases=_aliases(("output", "result"), ("out_features", "result")),
        # Only the one-to-one summarizing form maps cleanly onto the managed
        # process. One-to-many fan-out and non-inlinable (KEEP_COMMON) joins are
        # downgraded to manual-review with a reason by _spatial_join_gate.
        gate=_spatial_join_gate,
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="Dissolve",
        process_id="dissolve",
        job_process_id="geometry.dissolve",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("dissolve_field", "dissolve_fields"),
            _arg("statistics_fields", "statistics_fields"),
            _arg("multi_part", "multi_part"),
            _arg("unsplit_lines", "unsplit_lines"),
        ),
        aliases=_aliases(("output", "result"), ("out_features", "result")),
        notes=("geometry.dissolve is group-aware: dissolve_field maps to grouping fields.",),
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="CopyFeatures",
        process_id="copy-features",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
        ),
        aliases=_aliases(("output", "result"), ("out_features", "result")),
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="Project",
        process_id="project",
        job_process_id="geometry.project",
        args=(
            _arg("in_dataset", "input_features", kind="input"),
            _arg("out_dataset", "result", kind="output"),
            _arg("out_coor_system", "out_crs"),
            _arg("transform_method", "transform_method"),
            _arg("in_coor_system", "in_crs"),
            _arg("preserve_shape", "preserve_shape"),
            _arg("max_deviation", "max_deviation"),
            _arg("vertical", "vertical"),
        ),
        aliases=_aliases(
            ("in_features", "input_features"),
            ("out_feature_class", "result"),
            ("output", "result"),
            ("out_features", "result"),
        ),
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="RepairGeometry",
        process_id="make-valid",
        job_process_id="geometry.make-valid",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("delete_null", "delete_null"),
            _arg("validation_method", "validation_method"),
        ),
        aliases=_aliases(("input_layer", "input_features")),
        notes=(
            "ArcGIS RepairGeometry mutates in_features in place; geometry.make-valid "
            "returns a repaired feature result. delete_null/validation_method are "
            "passed through for server-side review.",
        ),
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="MakeFeatureLayer",
        process_id="make-feature-layer",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("out_layer", "layer", kind="output"),
            _arg("where_clause", "where"),
            _arg("workspace", "workspace"),
            _arg("field_info", "field_info"),
        ),
        aliases=_aliases(("filter", "where"), ("output", "layer")),
        notes=("Layer outputs are translated as process outputs; review ephemeral ArcPy layer semantics manually.",),
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="SelectLayerByAttribute",
        process_id="select-by-attribute",
        args=(
            _arg("in_layer_or_view", "input_features", kind="input"),
            _arg("selection_type", "selection_type"),
            _arg("where_clause", "where"),
            _arg("invert_where_clause", "invert_where_clause"),
        ),
        aliases=_aliases(("filter", "where"), ("input_layer", "input_features")),
        notes=("ArcPy selection mutates layer state; Honua process execution returns a selected feature result.",),
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="SelectLayerByLocation",
        process_id="select-by-location",
        args=(
            _arg("in_layer", "input_features", kind="input"),
            _arg("overlap_type", "relationship"),
            _arg("select_features", "select_features", kind="input"),
            _arg("search_distance", "search_distance"),
            _arg("selection_type", "selection_type"),
            _arg("invert_spatial_relationship", "invert_spatial_relationship"),
        ),
        aliases=_aliases(("input_layer", "input_features"), ("relationship", "relationship")),
        notes=("ArcPy selection mutates layer state; Honua process execution returns a selected feature result.",),
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="Merge",
        process_id="merge",
        args=(
            _arg("inputs", "input_features", kind="input"),
            _arg("output", "result", kind="output"),
            _arg("field_mappings", "field_mappings"),
            _arg("add_source", "add_source"),
        ),
        aliases=_aliases(("out_feature_class", "result"), ("out_features", "result")),
    )
)
_register(
    _ToolSpec(
        family="management",
        tool="Append",
        process_id="append",
        args=(
            _arg("inputs", "input_features", kind="input"),
            _arg("target", "target_features", kind="input"),
            _arg("schema_type", "schema_type"),
            _arg("field_mapping", "field_mapping"),
            _arg("subtype", "subtype"),
            _arg("expression", "where"),
            _arg("match_fields", "match_fields"),
            _arg("update_geometry", "update_geometry"),
        ),
        aliases=_aliases(("where_clause", "where")),
        notes=("Append is translated as a process request; review write behavior before running against production data.",),
    )
)

# ---------------------------------------------------------------------------
# Re-pointed hardening coverage: ArcPy tools mapped to the reconciled server's
# job-executable geometry.simplify process (honua-server#1228). Tools whose
# closest Honua target is NOT job-executable on the reconciled server are
# intentionally left unregistered rather than mapped to a non-runnable id, so
# executable coverage never overstates what the server can run.
# ---------------------------------------------------------------------------
_register(
    _ToolSpec(
        family="cartography",
        tool="SimplifyPolygon",
        process_id="simplify",
        job_process_id="geometry.simplify",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("algorithm", "algorithm"),
            _arg("tolerance", "tolerance"),
            _arg("minimum_area", "minimum_area"),
            _arg("error_option", "error_option"),
            _arg("collapsed_point_option", "collapsed_point_option"),
        ),
        aliases=_aliases(("output", "result"), ("out_features", "result"), ("simplification_tolerance", "tolerance")),
        notes=("Geometry simplification; ArcPy topology-preservation flags are passed through for server-side review.",),
    )
)
_register(
    _ToolSpec(
        family="cartography",
        tool="SimplifyLine",
        process_id="simplify",
        job_process_id="geometry.simplify",
        args=(
            _arg("in_features", "input_features", kind="input"),
            _arg("out_feature_class", "result", kind="output"),
            _arg("algorithm", "algorithm"),
            _arg("tolerance", "tolerance"),
            _arg("error_resolving_option", "error_option"),
            _arg("collapsed_point_option", "collapsed_point_option"),
        ),
        aliases=_aliases(("output", "result"), ("out_features", "result"), ("simplification_tolerance", "tolerance")),
        notes=("Geometry simplification; ArcPy topology-preservation flags are passed through for server-side review.",),
    )
)

_PAIRWISE_TOOL_ALIASES = {
    ("analysis", "pairwisebuffer"): ("analysis", "buffer"),
    ("analysis", "pairwiseclip"): ("analysis", "clip"),
    ("analysis", "pairwiseintersect"): ("analysis", "intersect"),
    ("analysis", "pairwiseerase"): ("analysis", "erase"),
    ("analysis", "pairwisedissolve"): ("management", "dissolve"),
}

_LEGACY_SUFFIX_FAMILIES: Mapping[str, str] = {
    "analysis": "analysis",
    "management": "management",
    "conversion": "conversion",
    "cartography": "cartography",
    "editing": "editing",
    "stats": "statistics",
    "statistics": "statistics",
    "ddd": "3d-analyst",
    "na": "network-analyst",
    "sa": "spatial-analyst",
}

_MODULE_FAMILIES: Mapping[str, str] = {
    "analysis": "analysis",
    "management": "management",
    "conversion": "conversion",
    "cartography": "cartography",
    "editing": "editing",
    "stats": "statistics",
    "statistics": "statistics",
    "ddd": "3d-analyst",
    "na": "network-analyst",
    "sa": "spatial-analyst",
    "ia": "image-analyst",
    "da": "data-access",
    "mp": "arcgis-pro",
    "mapping": "mapping",
    "env": "environment",
}

_CORE_FUNCTION_FAMILIES: Mapping[str, str] = {
    "AddError": "messaging",
    "AddMessage": "messaging",
    "AddWarning": "messaging",
    "CheckExtension": "licensing",
    "CheckInExtension": "licensing",
    "CheckOutExtension": "licensing",
    "Describe": "describe",
    "Exists": "catalog",
    "GetCount": "management",
    "GetParameter": "parameters",
    "GetParameterAsText": "parameters",
    "ListDatasets": "catalog",
    "ListFeatureClasses": "catalog",
    "ListFields": "catalog",
    "ListRasters": "catalog",
    "SetParameter": "parameters",
    "SetParameterAsText": "parameters",
}


class _ImportCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.star_modules: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "arcpy" or alias.name.startswith("arcpy."):
                visible_name = alias.asname or alias.name.split(".")[-1]
                self.aliases[visible_name] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module != "arcpy" and not module.startswith("arcpy."):
            return
        for alias in node.names:
            if alias.name == "*":
                self.star_modules.append(module)
                continue
            visible_name = alias.asname or alias.name
            self.aliases[visible_name] = f"{module}.{alias.name}"


class _CallCollector(ast.NodeVisitor):
    def __init__(self, aliases: Mapping[str, str], star_modules: Sequence[str], parents: Mapping[ast.AST, ast.AST], filename: str | None) -> None:
        self.aliases = aliases
        self.star_modules = star_modules
        self.parents = parents
        self.filename = filename
        self.calls: list[ArcPyCall] = []

    def visit_Call(self, node: ast.Call) -> None:
        qualified_name = _resolve_qualified_name(node.func, self.aliases, self.star_modules)
        if qualified_name is not None:
            family, tool = _classify_qualified_name(qualified_name)
            named_keywords = [kw for kw in node.keywords if kw.arg is not None]
            expanded_keywords = [kw for kw in node.keywords if kw.arg is None]
            self.calls.append(
                ArcPyCall(
                    qualified_name=qualified_name,
                    family=family,
                    tool=tool,
                    line=node.lineno,
                    column=node.col_offset,
                    args=tuple(_node_value(arg) for arg in node.args),
                    kwargs={kw.arg or "": _node_value(kw.value) for kw in named_keywords},
                    expanded_kwargs=tuple(_node_value(kw.value) for kw in expanded_keywords),
                    raw_args=tuple(_node_source(arg) for arg in node.args),
                    raw_kwargs={kw.arg or "": _node_source(kw.value) for kw in named_keywords},
                    raw_expanded_kwargs=tuple(_node_source(kw.value) for kw in expanded_keywords),
                    assignment_targets=_assignment_targets(node, self.parents),
                    filename=self.filename,
                )
            )
        self.generic_visit(node)


def scan_arcpy_source(source: str, *, filename: str | None = None) -> ArcPyScanReport:
    """Scan Python source text for ArcPy calls.

    The function parses source with :mod:`ast`, resolves common ``arcpy``
    import aliases, classifies call families, and returns literal arguments
    when they can be represented safely as JSON-like values. Non-literal
    arguments are preserved as ``{"python": "..."}`` expression records.
    """

    try:
        tree = ast.parse(source, filename=filename or "<arcpy-source>")
    except SyntaxError as exc:
        message = f"{exc.msg} at line {exc.lineno}, column {exc.offset}"
        return ArcPyScanReport(filename=filename, calls=(), imports={}, syntax_error=message)

    import_collector = _ImportCollector()
    import_collector.visit(tree)
    aliases = {"arcpy": "arcpy", **import_collector.aliases}
    parents = _parent_map(tree)
    call_collector = _CallCollector(aliases, import_collector.star_modules, parents, filename)
    call_collector.visit(tree)
    return ArcPyScanReport(
        filename=filename,
        calls=tuple(call_collector.calls),
        imports=aliases,
    )


def scan_arcpy_file(path: str | Path) -> ArcPyScanReport:
    """Read and scan a Python file for ArcPy calls."""

    file_path = Path(path)
    return scan_arcpy_source(file_path.read_text(encoding="utf-8"), filename=str(file_path))


def translate_arcpy_source(source: str, *, filename: str | None = None, process_id_map: Mapping[str, str] | None = None) -> ArcPyMigrationPlan:
    """Scan source and translate supported vector ArcPy calls."""

    return translate_arcpy_report(scan_arcpy_source(source, filename=filename), process_id_map=process_id_map)


def translate_arcpy_report(report: ArcPyScanReport, *, process_id_map: Mapping[str, str] | None = None) -> ArcPyMigrationPlan:
    """Translate supported calls from a scan report to OGC Processes payloads.

    Every *supported* call (one with a registered Honua OGC mapping) is
    translated, preserving the OGC API Processes run path. Each translation
    additionally carries the reconciled-server ``job_process_id`` when the tool
    is job-executable; coverage gating to job-executable tools is reported via
    :func:`build_parity_evidence`, not by dropping translations here.
    """

    translations = []
    for call in report.supported_calls:
        translations.append(_translate_call(call, process_id_map=process_id_map or {}))
    return ArcPyMigrationPlan(report=report, translations=tuple(translations))


def build_parity_evidence(plan: ArcPyMigrationPlan) -> JsonObject:
    """Build the parity-evidence JSON report for one source/plan.

    The report is the migration-story artifact: for every discovered ArcPy
    call it records the mapped Honua OGC process and reconciled-server job
    process (or ``manual-review`` / ``unsupported`` with a reason), an overall
    coverage percentage, and a per-tool status rollup. Coverage is computed
    against the set of classified calls and is gated by reconciled-server
    job-executability -- see :data:`EXECUTABLE_PROCESS_IDS`.
    """

    report = plan.report
    calls = report.calls
    total = len(calls)
    translatable = report.translatable_calls
    manual = report.manual_review_calls
    unsupported = report.unsupported_calls

    translation_by_call: dict[int, ArcPyProcessTranslation] = {
        id(translation.call): translation for translation in plan.translations
    }

    call_entries: list[JsonObject] = []
    for call in calls:
        entry: JsonObject = {
            "qualifiedName": call.qualified_name,
            "family": call.family,
            "tool": call.tool,
            "line": call.line,
            "column": call.column,
            "status": call.status,
            "processId": call.process_id,
            "jobProcessId": call.job_process_id,
        }
        translation = translation_by_call.get(id(call))
        if call.translatable and translation is not None:
            entry["payload"] = translation.payload
            if translation.notes:
                entry["notes"] = list(translation.notes)
        elif call.status == "manual-review":
            entry["reason"] = call.manual_review_reason or (
                "Honua process target is not job-executable by the reconciled server yet."
            )
            spec = _lookup_spec(call.family, call.tool)
            if spec is not None and spec.notes:
                entry["notes"] = list(spec.notes)
        else:
            entry["reason"] = "No Honua process mapping is registered for this ArcPy call."
        call_entries.append(entry)

    # Per-tool status rollup keyed by family.tool.
    tools: dict[str, JsonObject] = {}
    for call in calls:
        key = f"{call.family}.{call.tool}"
        bucket = tools.setdefault(
            key,
            {
                "family": call.family,
                "tool": call.tool,
                "status": call.status,
                "processId": call.process_id,
                "jobProcessId": call.job_process_id,
                "count": 0,
            },
        )
        bucket["count"] = int(bucket["count"]) + 1

    coverage_pct = round(100.0 * len(translatable) / total, 2) if total else 0.0

    return {
        "schema": "honua.migration.arcpy.parity-evidence/v1",
        "source": report.filename,
        "syntaxError": report.syntax_error,
        "summary": {
            "totalCalls": total,
            "translatableCalls": len(translatable),
            "manualReviewCalls": len(manual),
            "unsupportedCalls": len(unsupported),
            "coveragePercent": coverage_pct,
            "executableProcessIds": sorted(EXECUTABLE_PROCESS_IDS),
            "unsupportedFamilies": list(report.unsupported_families),
        },
        "calls": call_entries,
        "toolStatus": [tools[key] for key in sorted(tools)],
    }


def build_parity_evidence_for_source(
    source: str, *, filename: str | None = None, process_id_map: Mapping[str, str] | None = None
) -> JsonObject:
    """Scan + translate ``source`` and return its parity-evidence report."""

    plan = translate_arcpy_source(source, filename=filename, process_id_map=process_id_map)
    return build_parity_evidence(plan)


class ArcPyProcessRunner:
    """Execute translated ArcPy migration steps with ``client.ogc_processes()``.

    Pass either a :class:`honua_sdk.HonuaClient` or an object exposing an
    ``execute(process_id, payload)`` method with the same shape as
    :class:`honua_sdk.protocols.OgcProcessesClient`.
    """

    def __init__(
        self,
        client_or_processes: Any,
        *,
        poll_interval: float = 1.0,
        max_polls: int = 120,
        sleep: Any = None,
    ) -> None:
        self._processes = client_or_processes.ogc_processes() if hasattr(client_or_processes, "ogc_processes") else client_or_processes
        self._poll_interval = poll_interval
        self._max_polls = max_polls
        self._sleep = sleep if sleep is not None else _default_sleep

    def execute(self, translation: ArcPyProcessTranslation) -> ArcPyProcessExecution:
        """Execute one translated ArcPy call as a synchronous OGC process."""

        process_id, payload = self._execution_args(translation)
        result = self._processes.execute(process_id, payload)
        return ArcPyProcessExecution(translation=translation, result=result)

    def execute_plan(self, plan: ArcPyMigrationPlan) -> tuple[ArcPyProcessExecution, ...]:
        """Execute all supported translations synchronously, in plan order."""

        return tuple(self.execute(translation) for translation in plan.translations)

    def execute_async(self, translation: ArcPyProcessTranslation) -> ArcPyProcessExecution:
        """Submit a translated call, poll its job, and download results.

        The first response is treated as an OGC API - Processes status document.
        When it carries a job id, the runner polls ``job(job_id)`` until the job
        reaches a terminal status, then fetches ``job_results(job_id)`` on
        success. A synchronous (non-job) response is returned as-is so callers
        can use a single entry point regardless of server execution mode.
        """

        process_id, payload = self._execution_args(translation)
        submission = self._processes.execute(process_id, payload)
        job_id = _job_id(submission)
        if job_id is None:
            # Server ran the process synchronously; no job to poll.
            return ArcPyProcessExecution(translation=translation, result=submission)

        document = submission
        status = _normalize_status(_job_status(submission))
        polls = 0
        while status not in _TERMINAL_JOB_STATUSES:
            if polls >= self._max_polls:
                raise ArcPyJobTimeoutError(job_id, status, polls)
            self._sleep(self._poll_interval)
            polls += 1
            document = self._processes.job(job_id)
            status = _normalize_status(_job_status(document))

        if status != JOB_STATUS_SUCCESSFUL:
            raise ArcPyJobError(job_id, status, document)

        results = self._processes.job_results(job_id)
        return ArcPyProcessExecution(
            translation=translation,
            result=document,
            job_id=job_id,
            status=status,
            results=results,
        )

    def execute_plan_async(self, plan: ArcPyMigrationPlan) -> tuple[ArcPyProcessExecution, ...]:
        """Execute all supported translations as polled jobs, in plan order."""

        return tuple(self.execute_async(translation) for translation in plan.translations)

    def _execution_args(self, translation: ArcPyProcessTranslation) -> tuple[str, JsonObject]:
        if not translation.process_id:
            raise UnsupportedArcPyCallError(
                f"ArcPy call {translation.call.qualified_name!r} does not have a process mapping."
            )
        return translation.process_id, translation.payload


def _lookup_spec(family: str, tool: str) -> _ToolSpec | None:
    key = _tool_key(family, tool)
    spec = _SUPPORTED_TOOL_SPECS.get(key)
    if spec is None:
        aliased = _PAIRWISE_TOOL_ALIASES.get(key)
        spec = _SUPPORTED_TOOL_SPECS.get(aliased) if aliased is not None else None
    return spec


def _translate_call(call: ArcPyCall, *, process_id_map: Mapping[str, str]) -> ArcPyProcessTranslation:
    spec = _lookup_spec(call.family, call.tool)
    if spec is None:
        raise UnsupportedArcPyCallError(f"ArcPy call {call.qualified_name!r} is not supported by the translator.")

    inputs: JsonObject = {}
    outputs: JsonObject = {}
    consumed_keywords: set[str] = set()

    for index, value in enumerate(call.args):
        if index >= len(spec.args):
            inputs[f"arg_{index + 1}"] = value
            continue
        _assign_process_value(spec.args[index], value, inputs=inputs, outputs=outputs)

    spec_by_keyword = {_normalize_keyword(arg.arcpy_name): arg for arg in spec.args}
    for raw_name, value in call.kwargs.items():
        normalized = _normalize_keyword(raw_name)
        process_name = spec.aliases.get(normalized)
        arg_spec = spec_by_keyword.get(normalized)
        if process_name is not None:
            kind = _kind_for_process_name(process_name, spec)
            _assign_process_value(_ArgSpec(raw_name, process_name, kind), value, inputs=inputs, outputs=outputs)
            consumed_keywords.add(raw_name)
        elif arg_spec is not None:
            _assign_process_value(arg_spec, value, inputs=inputs, outputs=outputs)
            consumed_keywords.add(raw_name)
        else:
            inputs[_camel_to_snake(raw_name)] = value

    metadata: JsonObject = {
        "source": "arcpy",
        "qualifiedName": call.qualified_name,
        "family": call.family,
        "tool": call.tool,
        "line": call.line,
        "column": call.column,
    }
    if call.filename is not None:
        metadata["filename"] = call.filename
    if call.assignment_targets:
        metadata["assignmentTargets"] = list(call.assignment_targets)
    if call.expanded_kwargs:
        metadata["expandedKeywords"] = [
            {"value": value, "raw": raw}
            for value, raw in zip(call.expanded_kwargs, call.raw_expanded_kwargs, strict=False)
        ]
    passthrough_keywords = sorted(set(call.kwargs) - consumed_keywords)
    if passthrough_keywords:
        metadata["passthroughKeywords"] = passthrough_keywords

    payload: JsonObject = {"inputs": inputs, "metadata": {"honuaMigration": metadata}}
    if outputs:
        payload["outputs"] = outputs

    process_key = f"{call.family}.{call.tool}"
    process_id = process_id_map.get(process_key, process_id_map.get(spec.process_id, spec.process_id))
    job_process_id = spec.job_process_id if call.translatable else None
    return ArcPyProcessTranslation(
        call=call,
        process_id=process_id,
        payload=payload,
        notes=spec.notes,
        job_process_id=job_process_id,
    )


def _assign_process_value(arg_spec: _ArgSpec, value: JsonValue, *, inputs: JsonObject, outputs: JsonObject) -> None:
    target = outputs if arg_spec.kind == "output" else inputs
    target[arg_spec.process_name] = value


def _kind_for_process_name(process_name: str, spec: _ToolSpec) -> InputKind:
    for arg in spec.args:
        if arg.process_name == process_name:
            return arg.kind
    return "parameter"


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _assignment_targets(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> tuple[str, ...]:
    parent = parents.get(node)
    if isinstance(parent, ast.Assign) and parent.value is node:
        return tuple(_node_source(target) for target in parent.targets)
    if isinstance(parent, ast.AnnAssign) and parent.value is node:
        return (_node_source(parent.target),)
    if isinstance(parent, ast.NamedExpr) and parent.value is node:
        return (_node_source(parent.target),)
    return ()


def _resolve_qualified_name(node: ast.AST, aliases: Mapping[str, str], star_modules: Sequence[str]) -> str | None:
    parts = _attribute_parts(node)
    if not parts:
        return None

    base = parts[0]
    if base in aliases:
        resolved = aliases[base]
        if len(parts) > 1:
            resolved = ".".join((resolved, *parts[1:]))
        if resolved == "arcpy" or resolved.startswith("arcpy."):
            return resolved

    if len(parts) == 1:
        for module in star_modules:
            candidate = f"{module}.{base}"
            family, tool = _classify_qualified_name(candidate)
            if _tool_key(family, tool) in _SUPPORTED_TOOL_SPECS or family != "unknown":
                return candidate

    return None


def _attribute_parts(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _attribute_parts(node.value)
        if parent:
            return (*parent, node.attr)
    return ()


def _classify_qualified_name(qualified_name: str) -> tuple[str, str]:
    parts = qualified_name.split(".")
    if not parts or parts[0] != "arcpy":
        return "unknown", parts[-1] if parts else qualified_name

    if len(parts) >= 3:
        module = parts[1]
        family = _MODULE_FAMILIES.get(module, module.replace("_", "-"))
        return family, parts[-1]

    if len(parts) == 2:
        name = parts[1]
        for suffix, family in _LEGACY_SUFFIX_FAMILIES.items():
            marker = f"_{suffix}"
            if name.lower().endswith(marker):
                return family, name[: -len(marker)]
        return _CORE_FUNCTION_FAMILIES.get(name, "core"), name

    return "core", "arcpy"


def _node_value(node: ast.AST) -> JsonValue:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        return {"python": _node_source(node)}
    return _json_safe(value)


def _json_safe(value: Any) -> JsonValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, bytes | bytearray | str):
        return [_json_safe(item) for item in value]
    return {"python": repr(value)}


def _node_source(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse should be available on supported Python
        return node.__class__.__name__


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)


def _job_id(document: Any) -> str | None:
    if not isinstance(document, Mapping):
        return None
    for key in ("jobID", "jobId", "job_id", "id"):
        value = document.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int):
            return str(value)
    return None


def _job_status(document: Any) -> str | None:
    if not isinstance(document, Mapping):
        return None
    value = document.get("status")
    return value if isinstance(value, str) and value else None


def _normalize_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = status.strip().lower()
    return _STATUS_ALIASES.get(normalized, normalized)


_STATUS_ALIASES: Mapping[str, str] = {
    "succeeded": JOB_STATUS_SUCCESSFUL,
    "success": JOB_STATUS_SUCCESSFUL,
    "complete": JOB_STATUS_SUCCESSFUL,
    "completed": JOB_STATUS_SUCCESSFUL,
    "failure": JOB_STATUS_FAILED,
    "error": JOB_STATUS_FAILED,
    "dismiss": JOB_STATUS_DISMISSED,
    "cancelled": JOB_STATUS_DISMISSED,
    "canceled": JOB_STATUS_DISMISSED,
    "pending": JOB_STATUS_ACCEPTED,
    "queued": JOB_STATUS_ACCEPTED,
    "in_progress": JOB_STATUS_RUNNING,
    "inprogress": JOB_STATUS_RUNNING,
}


def _camel_to_snake(value: str) -> str:
    if "_" in value:
        return value
    result = []
    for index, character in enumerate(value):
        if character.isupper() and index > 0:
            result.append("_")
        result.append(character.lower())
    return "".join(result)
