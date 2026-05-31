"""Python toolbox (``.pyt``) parsing slice for the ArcPy migration codemod.

A ``.pyt`` file is ordinary Python source: a module defining a ``Toolbox``
class whose ``self.tools`` attribute lists tool classes, where each tool class
exposes ``label`` / ``description`` attributes, a ``getParameterInfo`` method
that builds ``arcpy.Parameter(...)`` objects, and an ``execute`` method that
runs the geoprocessing logic.

Because ``.pyt`` files are plain Python, we can reuse the AST-only ArcPy
scanner: this module extracts the toolbox/tool/parameter structure and feeds
each tool's ``execute`` body through :func:`scan_arcpy_source` /
:func:`translate_arcpy_source` to classify the GP calls inside it.

Binary ``.tbx`` / ``.atbx`` toolboxes are NOT parsed here -- see
:func:`parse_binary_toolbox` for the explicit stub + TODO.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .arcpy import (
    ArcPyMigrationPlan,
    ArcPyScanReport,
    JsonObject,
    JsonValue,
    build_parity_evidence,
    scan_arcpy_source,
    translate_arcpy_source,
)


class UnsupportedToolboxError(NotImplementedError):
    """Raised when a binary toolbox format is not parseable as source."""


@dataclass(frozen=True)
class PytParameter:
    """One ``arcpy.Parameter(...)`` discovered in ``getParameterInfo``."""

    name: str | None
    display_name: str | None = None
    datatype: str | None = None
    parameter_type: str | None = None
    direction: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "name": self.name,
            "displayName": self.display_name,
            "datatype": self.datatype,
            "parameterType": self.parameter_type,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class PytTool:
    """A single tool class within a Python toolbox."""

    class_name: str
    label: str | None
    description: str | None
    parameters: tuple[PytParameter, ...]
    execute_source: str | None
    report: ArcPyScanReport
    plan: ArcPyMigrationPlan

    def to_dict(self) -> JsonObject:
        return {
            "className": self.class_name,
            "label": self.label,
            "description": self.description,
            "parameters": [param.to_dict() for param in self.parameters],
            "plan": self.plan.to_dict(),
            "parityEvidence": build_parity_evidence(self.plan),
        }


@dataclass(frozen=True)
class PytToolbox:
    """Parsed Python toolbox: a toolbox label and its tool classes."""

    filename: str | None
    label: str | None
    alias: str | None
    tools: tuple[PytTool, ...]
    syntax_error: str | None = None
    declared_tool_names: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> JsonObject:
        result: JsonObject = {
            "schema": "honua.migration.arcpy.pyt-toolbox/v1",
            "filename": self.filename,
            "label": self.label,
            "alias": self.alias,
            "declaredToolNames": list(self.declared_tool_names),
            "tools": [tool.to_dict() for tool in self.tools],
        }
        if self.syntax_error is not None:
            result["syntaxError"] = self.syntax_error
        return result


def parse_pyt_source(source: str, *, filename: str | None = None) -> PytToolbox:
    """Parse Python-toolbox source into a :class:`PytToolbox`.

    Each tool's ``execute`` method body is fed through the ArcPy scanner and
    translator so its GP calls are classified just like a standalone script.
    """

    try:
        tree = ast.parse(source, filename=filename or "<pyt-source>")
    except SyntaxError as exc:
        message = f"{exc.msg} at line {exc.lineno}, column {exc.offset}"
        return PytToolbox(filename=filename, label=None, alias=None, tools=(), syntax_error=message)

    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

    toolbox_class = _find_toolbox_class(classes)
    label = alias = None
    declared_tool_names: tuple[str, ...] = ()
    if toolbox_class is not None:
        label = _string_attr_assignment(toolbox_class, "label")
        alias = _string_attr_assignment(toolbox_class, "alias")
        declared_tool_names = _tool_class_names(toolbox_class)

    # If the toolbox did not declare self.tools (or we could not resolve it),
    # fall back to every class that looks like a tool (has an execute method).
    toolbox_name = toolbox_class.name if toolbox_class else None
    candidate_names = declared_tool_names or tuple(
        name
        for name, node in classes.items()
        if name != toolbox_name and _has_method(node, "execute")
    )

    tools: list[PytTool] = []
    for name in candidate_names:
        node = classes.get(name)
        if node is None:
            continue
        tools.append(_parse_tool(node, filename=filename))

    return PytToolbox(
        filename=filename,
        label=label,
        alias=alias,
        tools=tuple(tools),
        declared_tool_names=declared_tool_names,
    )


def parse_pyt_file(path: str | Path) -> PytToolbox:
    """Read and parse a ``.pyt`` Python toolbox file."""

    file_path = Path(path)
    return parse_pyt_source(file_path.read_text(encoding="utf-8"), filename=str(file_path))


def parse_binary_toolbox(path: str | Path) -> PytToolbox:
    """Parse a binary ``.tbx`` / ``.atbx`` toolbox.

    NOT IMPLEMENTED. ``.tbx`` (XML-in-a-zip / proprietary) and ``.atbx``
    (zipped JSON + ArcGIS Pro toolbox content) are binary formats that cannot
    be AST-scanned as Python source.

    TODO(honua-sdk-python#59): implement a ``.atbx``/``.tbx`` reader that
    unzips the archive, reads each tool's ``tool.content.rc`` / ``*.tool``
    JSON for parameter metadata, and resolves the referenced script tool
    (often a ``.py`` validated against arcpy) before reusing the
    source-based scanner. Until then, callers should export the toolbox to a
    ``.pyt`` or point the codemod at the underlying script tools.
    """

    suffix = Path(path).suffix
    raise UnsupportedToolboxError(
        f"Binary toolbox parsing for {suffix!r} is not implemented yet "
        "(see TODO honua-sdk-python#59). Use a .pyt Python toolbox or the "
        "underlying script tools."
    )


def build_pyt_parity_evidence(toolbox: PytToolbox) -> JsonObject:
    """Aggregate a parity-evidence report across all tools in a toolbox."""

    per_tool: list[JsonObject] = []
    total = translatable = manual = unsupported = 0
    for tool in toolbox.tools:
        evidence = build_parity_evidence(tool.plan)
        summary = evidence["summary"]
        total += int(summary["totalCalls"])
        translatable += int(summary["translatableCalls"])
        manual += int(summary["manualReviewCalls"])
        unsupported += int(summary["unsupportedCalls"])
        per_tool.append(
            {
                "className": tool.class_name,
                "label": tool.label,
                "evidence": evidence,
            }
        )

    coverage_pct = round(100.0 * translatable / total, 2) if total else 0.0
    return {
        "schema": "honua.migration.arcpy.pyt-parity-evidence/v1",
        "filename": toolbox.filename,
        "label": toolbox.label,
        "alias": toolbox.alias,
        "summary": {
            "toolCount": len(toolbox.tools),
            "totalCalls": total,
            "translatableCalls": translatable,
            "manualReviewCalls": manual,
            "unsupportedCalls": unsupported,
            "coveragePercent": coverage_pct,
        },
        "tools": per_tool,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _parse_tool(node: ast.ClassDef, *, filename: str | None) -> PytTool:
    label = _string_attr_assignment(node, "label")
    description = _string_attr_assignment(node, "description")
    parameters = _parse_parameters(node)
    execute_source = _method_body_source(node, "execute")
    if execute_source:
        report = scan_arcpy_source(execute_source, filename=filename)
        plan = translate_arcpy_source(execute_source, filename=filename)
    else:
        report = ArcPyScanReport(filename=filename, calls=())
        plan = ArcPyMigrationPlan(report=report, translations=())
    return PytTool(
        class_name=node.name,
        label=label,
        description=description,
        parameters=parameters,
        execute_source=execute_source,
        report=report,
        plan=plan,
    )


def _find_toolbox_class(classes: dict[str, ast.ClassDef]) -> ast.ClassDef | None:
    # Prefer a class literally named Toolbox, then any class assigning self.tools.
    if "Toolbox" in classes:
        return classes["Toolbox"]
    for node in classes.values():
        if _tool_class_names(node):
            return node
    return None


def _has_method(node: ast.ClassDef, name: str) -> bool:
    return any(isinstance(item, ast.FunctionDef) and item.name == name for item in node.body)


def _method(node: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == name:
            return item
    return None


def _method_body_source(node: ast.ClassDef, name: str) -> str | None:
    method = _method(node, name)
    if method is None or not method.body:
        return None
    statements = [stmt for stmt in method.body if not _is_docstring(stmt)]
    if not statements:
        return None
    rendered = "\n".join(ast.unparse(stmt) for stmt in statements)
    return rendered


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _string_attr_assignment(node: ast.ClassDef, attr: str) -> str | None:
    """Find ``self.<attr> = "..."`` or class-level ``<attr> = "..."``."""

    # self.<attr> = "..." inside __init__ (or anywhere in the class methods).
    for method in node.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        for stmt in ast.walk(method):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == attr
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        value = _const_str(stmt.value)
                        if value is not None:
                            return value
    # class-level <attr> = "..."
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == attr:
                    value = _const_str(stmt.value)
                    if value is not None:
                        return value
    return None


def _tool_class_names(node: ast.ClassDef) -> tuple[str, ...]:
    """Resolve the class names listed in ``self.tools = [...]``."""

    for method in node.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        for stmt in ast.walk(method):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "tools"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    return _names_in_sequence(stmt.value)
    return ()


def _names_in_sequence(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.List | ast.Tuple):
        names: list[str] = []
        for element in node.elts:
            if isinstance(element, ast.Name):
                names.append(element.id)
            elif isinstance(element, ast.Attribute):
                names.append(element.attr)
        return tuple(names)
    return ()


def _parse_parameters(node: ast.ClassDef) -> tuple[PytParameter, ...]:
    method = _method(node, "getParameterInfo")
    if method is None:
        return ()
    parameters: list[PytParameter] = []
    for call in ast.walk(method):
        if not isinstance(call, ast.Call):
            continue
        if not _is_parameter_constructor(call.func):
            continue
        kwargs: dict[str, JsonValue] = {}
        for keyword in call.keywords:
            if keyword.arg is not None:
                kwargs[keyword.arg] = _const_value(keyword.value)
        parameters.append(
            PytParameter(
                name=_as_str(kwargs.get("name")),
                display_name=_as_str(kwargs.get("displayName")),
                datatype=_as_str(kwargs.get("datatype")),
                parameter_type=_as_str(kwargs.get("parameterType")),
                direction=_as_str(kwargs.get("direction")),
            )
        )
    return tuple(parameters)


def _is_parameter_constructor(func: ast.AST) -> bool:
    # Match arcpy.Parameter(...), arcpy.management.Parameter? -> only Parameter.
    if isinstance(func, ast.Attribute):
        return func.attr == "Parameter"
    if isinstance(func, ast.Name):
        return func.id == "Parameter"
    return False


def _const_str(node: ast.AST) -> str | None:
    value = _const_value(node)
    return value if isinstance(value, str) else None


def _const_value(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
