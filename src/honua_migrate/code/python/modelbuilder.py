"""ModelBuilder (``.atbx``) + GP-service task-definition translation slice.

This module extends the ArcPy migration codemod beyond standalone ``.py``
scripts and ``.pyt`` Python toolboxes (see :mod:`honua_migrate.code.python.pyt`) to
two more inventory sources:

* **ModelBuilder models** packaged in ArcGIS Pro ``.atbx`` toolboxes. The
  ``.atbx`` format is a published, open, **zip-of-JSON** container (Esri
  documents it as "JSON-based with an open specification"); each model tool is
  stored as a JSON model definition listing its geoprocessing process steps.
  We read those JSON definitions **clean-room** -- we never decompile or run
  licensed Esri software, and we never parse the proprietary binary ``.tbx``
  format (kept an explicit stub in :func:`honua_migrate.code.python.pyt`).

* **GP-service task definitions** -- the JSON returned by an ArcGIS REST
  ``GPServer`` service (``.../GPServer?f=json`` and each task's
  ``.../GPServer/<task>?f=json``). These are public REST API documents (fair
  use; Google v. Oracle) describing a geoprocessing task's name and parameters.

Both readers reuse the registry-driven classification in
:mod:`honua_migrate.code.python.arcpy`: each discovered geoprocessing step is mapped
to its Honua OGC API - Processes target (or flagged ``manual-review`` /
``unsupported`` with a reason) so the parity-evidence story is identical across
script / toolbox / model / service inputs.

Because ModelBuilder models and GP tasks reference tools by their *toolbox
tool name* (e.g. ``Buffer``, ``analysis.Buffer``, ``Buffer_analysis``) rather
than a fully-qualified ``arcpy.analysis.Buffer`` call, this module normalizes
those forms to an :class:`~honua_migrate.code.python.arcpy.ArcPyCall` and runs it
through the same spec lookup.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .arcpy import (
    _SUPPORTED_TOOL_SPECS,
    ArcPyCall,
    ArcPyMigrationPlan,
    ArcPyProcessTranslation,
    ArcPyScanReport,
    JsonObject,
    JsonValue,
    _classify_qualified_name,
    _lookup_spec,
    _normalize_tool,
    _translate_call,
    build_parity_evidence,
)

_BINARY_TOOLBOX_SUFFIXES = frozenset({".tbx"})
_ATBX_SUFFIX = ".atbx"


class UnsupportedModelFormatError(NotImplementedError):
    """Raised for toolbox/model formats that are not clean-room parseable."""


# ---------------------------------------------------------------------------
# Tool-reference normalization
# ---------------------------------------------------------------------------


def _qualified_name_for_tool_reference(tool_name: str, *, toolbox: str | None = None) -> str:
    """Map a ModelBuilder / GP tool reference to an ``arcpy.<family>.<Tool>`` name.

    Accepts the common toolbox-tool reference spellings:

    * ``"Buffer"`` with a toolbox alias (``toolbox="analysis"``) ->
      ``"arcpy.analysis.Buffer"``,
    * ``"analysis.Buffer"`` / ``"Buffer_analysis"`` (legacy underscore form),
    * already-qualified ``"arcpy.analysis.Buffer"`` (passed through).

    The result is fed to the shared classifier so registry lookup matches the
    same specs the ``.py`` scanner uses. Unknown families simply fail spec
    lookup later and classify as ``unsupported`` -- never a crash.
    """

    name = tool_name.strip()
    if name.startswith("arcpy."):
        return name
    if "." in name:
        # "analysis.Buffer" -> "arcpy.analysis.Buffer"
        return f"arcpy.{name}"
    if "_" in name:
        # Legacy "Buffer_analysis" -> "arcpy.analysis.Buffer".
        base, _, suffix = name.rpartition("_")
        if base and suffix:
            return f"arcpy.{suffix.lower()}.{base}"
    if toolbox:
        alias = toolbox.strip().lower()
        # Tolerate a ".tbx"/".atbx" suffix on the toolbox alias.
        for suffix in (".atbx", ".tbx"):
            if alias.endswith(suffix):
                alias = alias[: -len(suffix)]
        if alias:
            return f"arcpy.{alias}.{name}"
    return f"arcpy.{name}"


def _families_by_tool() -> dict[str, list[str]]:
    """Reverse index: normalized tool name -> registered families.

    GP-service tasks and some ModelBuilder steps reference a tool by its bare
    name (``"Buffer"``) with no toolbox alias. The fully-qualified classifier
    would file a bare 2-part name under ``"core"`` and miss the registry. This
    index lets :func:`_call_from_tool_reference` recover the registered family
    for an unambiguous bare tool name.
    """

    index: dict[str, list[str]] = {}
    for family, normalized_tool in _SUPPORTED_TOOL_SPECS:
        index.setdefault(normalized_tool, []).append(family)
    return index


def _call_from_tool_reference(
    tool_name: str,
    *,
    toolbox: str | None,
    inputs: Mapping[str, JsonValue] | None,
    line: int,
    filename: str | None,
) -> ArcPyCall:
    """Build an :class:`ArcPyCall` for a model/GP step, keyed by tool reference."""

    qualified_name = _qualified_name_for_tool_reference(tool_name, toolbox=toolbox)
    family, tool = _classify_qualified_name(qualified_name)

    # When a bare tool reference (no toolbox alias) classified to a family that
    # has no registered spec, recover the registered family if the tool name is
    # unambiguous across the registry. This keeps GP-service tasks named only
    # "Buffer" resolvable without forcing callers to know the toolbox alias.
    if _lookup_spec(family, tool) is None:
        candidates = _families_by_tool().get(_normalize_tool(tool), [])
        if len(candidates) == 1:
            family = candidates[0]
            qualified_name = f"arcpy.{family}.{tool}"
    kwargs: dict[str, JsonValue] = dict(inputs or {})
    return ArcPyCall(
        qualified_name=qualified_name,
        family=family,
        tool=tool,
        line=line,
        column=0,
        args=(),
        kwargs=kwargs,
        raw_kwargs={key: repr(value) for key, value in kwargs.items()},
        filename=filename,
    )


def _plan_from_calls(
    calls: Sequence[ArcPyCall], *, filename: str | None
) -> ArcPyMigrationPlan:
    """Build a scan report + translation plan from pre-built calls.

    Mirrors :func:`honua_migrate.code.python.arcpy.translate_arcpy_report`: every
    *supported* call (one with a registered Honua mapping) is translated;
    coverage gating to job-executable tools is handled by the parity-evidence
    builder, not by dropping translations here.
    """

    report = ArcPyScanReport(filename=filename, calls=tuple(calls))
    translations: list[ArcPyProcessTranslation] = []
    for call in report.supported_calls:
        translations.append(_translate_call(call, process_id_map={}))
    return ArcPyMigrationPlan(report=report, translations=tuple(translations))


# ---------------------------------------------------------------------------
# ModelBuilder model definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelStep:
    """One geoprocessing step (tool execution) inside a ModelBuilder model."""

    tool_name: str
    toolbox: str | None
    label: str | None
    inputs: Mapping[str, JsonValue]
    call: ArcPyCall

    def to_dict(self) -> JsonObject:
        return {
            "toolName": self.tool_name,
            "toolbox": self.toolbox,
            "label": self.label,
            "inputs": dict(self.inputs),
            "qualifiedName": self.call.qualified_name,
            "family": self.call.family,
            "tool": self.call.tool,
            "status": self.call.status,
            "processId": self.call.process_id,
            "jobProcessId": self.call.job_process_id,
        }


@dataclass(frozen=True)
class ModelBuilderModel:
    """A ModelBuilder model translated to a Honua migration plan."""

    name: str
    label: str | None
    steps: tuple[ModelStep, ...]
    plan: ArcPyMigrationPlan
    filename: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "schema": "honua.migration.arcpy.modelbuilder-model/v1",
            "name": self.name,
            "label": self.label,
            "filename": self.filename,
            "steps": [step.to_dict() for step in self.steps],
            "plan": self.plan.to_dict(),
            "parityEvidence": build_parity_evidence(self.plan),
        }


@dataclass(frozen=True)
class ModelBuilderToolbox:
    """All ModelBuilder models parsed clean-room from a ``.atbx`` toolbox."""

    filename: str | None
    models: tuple[ModelBuilderModel, ...]
    script_tool_names: tuple[str, ...] = field(default_factory=tuple)
    parse_error: str | None = None

    def to_dict(self) -> JsonObject:
        result: JsonObject = {
            "schema": "honua.migration.arcpy.modelbuilder-toolbox/v1",
            "filename": self.filename,
            "scriptToolNames": list(self.script_tool_names),
            "models": [model.to_dict() for model in self.models],
        }
        if self.parse_error is not None:
            result["parseError"] = self.parse_error
        return result


def _coerce_inputs(raw: Any) -> dict[str, JsonValue]:
    """Best-effort coercion of a model/GP step's parameter map to JSON values."""

    inputs: dict[str, JsonValue] = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            inputs[str(key)] = _json_value(value)
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            if isinstance(value, Mapping) and "name" in value:
                inputs[str(value["name"])] = _json_value(value.get("value"))
            else:
                inputs[f"arg_{index + 1}"] = _json_value(value)
    return inputs


def _json_value(value: Any) -> JsonValue:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return {"python": repr(value)}


def _model_steps_from_definition(
    definition: Mapping[str, Any], *, filename: str | None
) -> list[ModelStep]:
    """Extract ordered GP steps from a tolerant model-definition JSON shape.

    The ``.atbx`` model JSON stores its processes under a few possible keys
    across ArcGIS Pro releases. We accept any of ``processes`` / ``steps`` /
    ``tools`` (a list of step objects). Each step object may carry its tool name
    under ``toolName`` / ``tool`` / ``name`` / ``toolID``, an optional toolbox
    alias under ``toolbox`` / ``toolboxAlias``, a label under ``label`` /
    ``displayName``, and parameters under ``parameters`` / ``inputs`` /
    ``arguments``. Unknown shapes simply yield no steps rather than crashing.
    """

    steps_raw: Any = None
    for key in ("processes", "steps", "tools"):
        candidate = definition.get(key)
        if isinstance(candidate, list):
            steps_raw = candidate
            break
    if not isinstance(steps_raw, list):
        return []

    steps: list[ModelStep] = []
    for index, raw in enumerate(steps_raw):
        if not isinstance(raw, Mapping):
            continue
        tool_name = _first_str(raw, ("toolName", "tool", "name", "toolID"))
        if not tool_name:
            continue
        toolbox = _first_str(raw, ("toolbox", "toolboxAlias", "toolboxalias"))
        label = _first_str(raw, ("label", "displayName"))
        parameters: Any = None
        for pkey in ("parameters", "inputs", "arguments"):
            if pkey in raw:
                parameters = raw[pkey]
                break
        inputs = _coerce_inputs(parameters)
        call = _call_from_tool_reference(
            tool_name,
            toolbox=toolbox,
            inputs=inputs,
            line=index + 1,
            filename=filename,
        )
        steps.append(
            ModelStep(
                tool_name=tool_name,
                toolbox=toolbox,
                label=label,
                inputs=inputs,
                call=call,
            )
        )
    return steps


def _first_str(data: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_model_definition(
    definition: Mapping[str, Any] | str,
    *,
    name: str | None = None,
    filename: str | None = None,
) -> ModelBuilderModel:
    """Translate a single ModelBuilder model-definition JSON to a plan.

    ``definition`` may be a parsed mapping or a JSON string. The model name is
    taken from ``name``, then the definition's ``name`` / ``label`` keys.
    """

    if isinstance(definition, str):
        definition = json.loads(definition)
    if not isinstance(definition, Mapping):
        raise UnsupportedModelFormatError("Model definition must be a JSON object.")

    model_name = name or _first_str(definition, ("name", "label")) or "model"
    label = _first_str(definition, ("label", "displayName"))
    steps = _model_steps_from_definition(definition, filename=filename)
    plan = _plan_from_calls([step.call for step in steps], filename=filename)
    return ModelBuilderModel(
        name=model_name,
        label=label,
        steps=tuple(steps),
        plan=plan,
        filename=filename,
    )


def parse_atbx_toolbox(path: str | Path) -> ModelBuilderToolbox:
    """Parse a ``.atbx`` toolbox clean-room and translate its ModelBuilder models.

    ``.atbx`` is a zip container of JSON definitions. This reader unzips the
    archive in memory and, for every ``*.tool`` whose ``*.content``/``*.rc``
    JSON describes a *model* (carries a process/step list), extracts the GP
    steps and translates them through the shared registry. Script tools (which
    reference an external ``.py``) are surfaced by name under
    :attr:`ModelBuilderToolbox.script_tool_names` for the caller to scan via the
    ``.py`` path; their bodies are not in the ``.atbx`` JSON.

    The proprietary binary ``.tbx`` format is **not** handled here (see
    :func:`honua_migrate.code.python.pyt.parse_binary_toolbox`); pass an exported
    ``.atbx`` instead.
    """

    file_path = Path(path)
    if file_path.suffix.lower() in _BINARY_TOOLBOX_SUFFIXES:
        raise UnsupportedModelFormatError(
            f"Binary toolbox parsing for {file_path.suffix!r} is not supported "
            "(proprietary format -- not clean-room parseable). Export to .atbx "
            "and re-run."
        )

    try:
        archive = zipfile.ZipFile(file_path)
    except (zipfile.BadZipFile, OSError) as exc:
        return ModelBuilderToolbox(
            filename=str(file_path),
            models=(),
            parse_error=f"Could not open .atbx archive: {exc}",
        )

    models: list[ModelBuilderModel] = []
    script_tool_names: list[str] = []
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            entry = info.filename
            lowered = entry.lower()
            tool_name = _tool_name_from_entry(entry)
            # ArcGIS Pro stores tool definitions as JSON in files whose
            # extension varies by release (``.content``, ``.content.rc``,
            # ``.rc``, ``.json``). Be tolerant: try to JSON-decode any text
            # entry inside a ``*.tool`` folder (or any ``.json``/.rc/.content
            # file) and skip whatever does not parse as a JSON object.
            in_tool_folder = tool_name is not None
            json_like = lowered.endswith((".rc", ".json", ".content"))
            if not (in_tool_folder or json_like):
                continue
            try:
                payload = json.loads(archive.read(info).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            if _looks_like_script_tool(payload):
                if tool_name and tool_name not in script_tool_names:
                    script_tool_names.append(tool_name)
                continue
            if not _looks_like_model(payload):
                continue
            model = parse_model_definition(
                payload,
                name=tool_name or _first_str(payload, ("name", "label")),
                filename=f"{file_path}!{entry}",
            )
            if model.steps:
                models.append(model)

    return ModelBuilderToolbox(
        filename=str(file_path),
        models=tuple(models),
        script_tool_names=tuple(sorted(script_tool_names)),
    )


def _tool_name_from_entry(entry: str) -> str | None:
    """Derive a tool name from a ``.../<ToolName>.tool/...`` archive path."""

    for part in Path(entry).parts:
        if part.lower().endswith(".tool"):
            return part[: -len(".tool")]
    return None


def _looks_like_model(payload: Mapping[str, Any]) -> bool:
    for key in ("processes", "steps", "tools"):
        if isinstance(payload.get(key), list):
            return True
    tool_type = payload.get("type") or payload.get("toolType")
    return isinstance(tool_type, str) and "model" in tool_type.lower()


def _looks_like_script_tool(payload: Mapping[str, Any]) -> bool:
    tool_type = payload.get("type") or payload.get("toolType")
    if isinstance(tool_type, str) and "script" in tool_type.lower():
        return True
    script = payload.get("script") or payload.get("scriptFile")
    return isinstance(script, str) and script.lower().endswith(".py")


def build_model_parity_evidence(model: ModelBuilderModel) -> JsonObject:
    """Parity-evidence report for one ModelBuilder model (delegates to the core)."""

    evidence = build_parity_evidence(model.plan)
    evidence["modelName"] = model.name
    return evidence


def build_atbx_parity_evidence(toolbox: ModelBuilderToolbox) -> JsonObject:
    """Aggregate parity-evidence across every model in a ``.atbx`` toolbox."""

    per_model: list[JsonObject] = []
    total = translatable = manual = unsupported = 0
    for model in toolbox.models:
        evidence = build_parity_evidence(model.plan)
        summary = evidence["summary"]
        total += int(summary["totalCalls"])
        translatable += int(summary["translatableCalls"])
        manual += int(summary["manualReviewCalls"])
        unsupported += int(summary["unsupportedCalls"])
        per_model.append({"name": model.name, "label": model.label, "evidence": evidence})

    coverage_pct = round(100.0 * translatable / total, 2) if total else 0.0
    return {
        "schema": "honua.migration.arcpy.atbx-parity-evidence/v1",
        "filename": toolbox.filename,
        "scriptToolNames": list(toolbox.script_tool_names),
        "summary": {
            "modelCount": len(toolbox.models),
            "totalCalls": total,
            "translatableCalls": translatable,
            "manualReviewCalls": manual,
            "unsupportedCalls": unsupported,
            "coveragePercent": coverage_pct,
        },
        "models": per_model,
    }


# ---------------------------------------------------------------------------
# GP-service task definitions (ArcGIS REST GPServer)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GpTaskParameter:
    """One parameter of a GP-service task definition."""

    name: str | None
    data_type: str | None = None
    direction: str | None = None
    parameter_type: str | None = None
    default_value: JsonValue = None

    def to_dict(self) -> JsonObject:
        result: JsonObject = {
            "name": self.name,
            "dataType": self.data_type,
            "direction": self.direction,
            "parameterType": self.parameter_type,
        }
        if self.default_value is not None:
            result["defaultValue"] = self.default_value
        return result


@dataclass(frozen=True)
class GpTask:
    """A single ArcGIS REST GPServer task translated to a Honua plan."""

    name: str
    display_name: str | None
    execution_type: str | None
    parameters: tuple[GpTaskParameter, ...]
    plan: ArcPyMigrationPlan

    def to_dict(self) -> JsonObject:
        return {
            "schema": "honua.migration.arcpy.gp-task/v1",
            "name": self.name,
            "displayName": self.display_name,
            "executionType": self.execution_type,
            "parameters": [param.to_dict() for param in self.parameters],
            "plan": self.plan.to_dict(),
            "parityEvidence": build_parity_evidence(self.plan),
        }


@dataclass(frozen=True)
class GpService:
    """A parsed ArcGIS REST GPServer service: its tasks and their plans."""

    url: str | None
    tasks: tuple[GpTask, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema": "honua.migration.arcpy.gp-service/v1",
            "url": self.url,
            "tasks": [task.to_dict() for task in self.tasks],
        }


def _gp_task_parameters(definition: Mapping[str, Any]) -> tuple[GpTaskParameter, ...]:
    raw = definition.get("parameters")
    params: list[GpTaskParameter] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            params.append(
                GpTaskParameter(
                    name=_first_str(item, ("name",)),
                    data_type=_first_str(item, ("dataType", "datatype")),
                    direction=_first_str(item, ("direction",)),
                    parameter_type=_first_str(item, ("parameterType",)),
                    default_value=_json_value(item.get("defaultValue")),
                )
            )
    return tuple(params)


def _gp_task_input_kwargs(parameters: Sequence[GpTaskParameter]) -> dict[str, JsonValue]:
    """Build a kwargs map from a task's *input* parameters for classification."""

    kwargs: dict[str, JsonValue] = {}
    for param in parameters:
        if param.name is None:
            continue
        direction = (param.direction or "").lower()
        if direction.startswith("esrigpparameterdirectionoutput") or direction == "output":
            continue
        kwargs[param.name] = param.default_value
    return kwargs


def parse_gp_task_definition(
    definition: Mapping[str, Any] | str, *, name: str | None = None
) -> GpTask:
    """Translate one GPServer task definition JSON (``.../GPServer/<task>?f=json``).

    The task ``name`` is classified through the shared registry exactly like a
    ModelBuilder step, so a ``Buffer`` GP task maps to ``geometry.buffer`` (etc.)
    or flags ``manual-review`` / ``unsupported`` with a reason.
    """

    if isinstance(definition, str):
        definition = json.loads(definition)
    if not isinstance(definition, Mapping):
        raise UnsupportedModelFormatError("GP task definition must be a JSON object.")

    task_name = name or _first_str(definition, ("name", "displayName")) or "task"
    display_name = _first_str(definition, ("displayName",))
    execution_type = _first_str(definition, ("executionType",))
    parameters = _gp_task_parameters(definition)
    call = _call_from_tool_reference(
        task_name,
        toolbox=None,
        inputs=_gp_task_input_kwargs(parameters),
        line=1,
        filename=None,
    )
    plan = _plan_from_calls([call], filename=None)
    return GpTask(
        name=task_name,
        display_name=display_name,
        execution_type=execution_type,
        parameters=parameters,
        plan=plan,
    )


def parse_gp_service_definition(
    definition: Mapping[str, Any] | str,
    *,
    url: str | None = None,
    task_definitions: Mapping[str, Mapping[str, Any]] | None = None,
) -> GpService:
    """Translate a GPServer service catalog (``.../GPServer?f=json``).

    The service catalog lists task names under ``tasks``. When a per-task
    definition is available (fetched separately and supplied via
    ``task_definitions``), its parameters are used; otherwise the task is
    classified by name alone.
    """

    if isinstance(definition, str):
        definition = json.loads(definition)
    if not isinstance(definition, Mapping):
        raise UnsupportedModelFormatError("GP service definition must be a JSON object.")

    task_names: list[str] = []
    raw_tasks = definition.get("tasks")
    if isinstance(raw_tasks, list):
        for item in raw_tasks:
            if isinstance(item, str) and item.strip():
                task_names.append(item.strip())
            elif isinstance(item, Mapping):
                name = _first_str(item, ("name", "displayName"))
                if name:
                    task_names.append(name)

    tasks: list[GpTask] = []
    for name in task_names:
        task_def = (task_definitions or {}).get(name)
        if task_def is not None:
            tasks.append(parse_gp_task_definition(task_def, name=name))
        else:
            tasks.append(parse_gp_task_definition({"name": name}, name=name))

    return GpService(url=url, tasks=tuple(tasks))


def build_gp_service_parity_evidence(service: GpService) -> JsonObject:
    """Aggregate parity-evidence across every task in a GP service."""

    per_task: list[JsonObject] = []
    total = translatable = manual = unsupported = 0
    for task in service.tasks:
        evidence = build_parity_evidence(task.plan)
        summary = evidence["summary"]
        total += int(summary["totalCalls"])
        translatable += int(summary["translatableCalls"])
        manual += int(summary["manualReviewCalls"])
        unsupported += int(summary["unsupportedCalls"])
        per_task.append({"name": task.name, "evidence": evidence})

    coverage_pct = round(100.0 * translatable / total, 2) if total else 0.0
    return {
        "schema": "honua.migration.arcpy.gp-service-parity-evidence/v1",
        "url": service.url,
        "summary": {
            "taskCount": len(service.tasks),
            "totalCalls": total,
            "translatableCalls": translatable,
            "manualReviewCalls": manual,
            "unsupportedCalls": unsupported,
            "coveragePercent": coverage_pct,
        },
        "tasks": per_task,
    }
