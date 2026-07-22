"""Tripwire for the built-in-process-only Python migration policy."""

from __future__ import annotations

import ast
from pathlib import Path

import honua_migrate.code.python

_PACKAGE_ROOT = Path(honua_migrate.code.python.__file__).resolve().parent
_FORBIDDEN_NAME_FRAGMENTS = ("customcode",)
_FORBIDDEN_PARAM_NAMES = frozenset(
    {
        "backend",
        "customcode",
        "executionbackend",
        "computebackend",
        "localbackend",
    }
)


def _normalize(name: str) -> str:
    return name.replace("_", "").replace("-", "").lower()


def _definitions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node


def _parameter_offenders(tree: ast.AST, label: str) -> list[str]:
    offenders: list[str] = []
    for node in _definitions(tree):
        if isinstance(node, ast.ClassDef):
            continue
        args = node.args
        parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        if args.vararg is not None:
            parameters.append(args.vararg)
        if args.kwarg is not None:
            parameters.append(args.kwarg)
        for parameter in parameters:
            if _normalize(parameter.arg) in _FORBIDDEN_PARAM_NAMES:
                offenders.append(f"{label}::{node.name}({parameter.arg})")
    return offenders


def _package_trees():
    for path in _PACKAGE_ROOT.rglob("*.py"):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_custom_code_named_api() -> None:
    offenders = [
        f"{path.relative_to(_PACKAGE_ROOT)}::{node.name}"
        for path, tree in _package_trees()
        for node in _definitions(tree)
        if any(
            fragment in _normalize(node.name)
            for fragment in _FORBIDDEN_NAME_FRAGMENTS
        )
    ]
    assert not offenders


def test_no_execution_backend_selector() -> None:
    offenders = [
        offender
        for path, tree in _package_trees()
        for offender in _parameter_offenders(tree, str(path.relative_to(_PACKAGE_ROOT)))
    ]
    assert not offenders


def test_tripwire_detects_backend_parameters() -> None:
    for source in (
        "def submit(inputs, execution_backend): ...",
        "def run(compute_backend=None): ...",
        "async def dispatch(*, backend): ...",
    ):
        assert _parameter_offenders(ast.parse(source), "<synthetic>")
    assert _parameter_offenders(
        ast.parse("def query(where, out_fields=None): ..."),
        "<synthetic>",
    ) == []
