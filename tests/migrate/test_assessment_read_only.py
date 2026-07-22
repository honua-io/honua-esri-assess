"""Exhaustive source guard for assessment HTTP transport capabilities."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSESSMENT_SOURCE = REPO_ROOT / "src" / "honua_esri_assess"
WRITE_METHODS = {"post", "put", "patch", "delete", "request", "send"}


@pytest.mark.parametrize("path", sorted(ASSESSMENT_SOURCE.rglob("*.py")))
def test_assessment_source_has_no_write_capable_http_calls(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_urllib_request = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "Request"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "request"
        )
        if is_urllib_request:
            method_keywords = [kw.value for kw in node.keywords if kw.arg == "method"]
            if len(method_keywords) != 1:
                violations.append(
                    f"line {node.lineno}: urllib Request must declare method='GET'"
                )
            elif not (
                isinstance(method_keywords[0], ast.Constant)
                and method_keywords[0].value == "GET"
            ):
                violations.append(
                    f"line {node.lineno}: urllib Request method is not constant GET"
                )
        elif isinstance(node.func, ast.Attribute):
            method = node.func.attr.casefold()
            if method in WRITE_METHODS:
                violations.append(f"line {node.lineno}: .{node.func.attr}(...)")
            if method == "urlopen":
                data_keywords = [kw for kw in node.keywords if kw.arg == "data"]
                if len(node.args) > 1 or data_keywords:
                    violations.append(
                        f"line {node.lineno}: urlopen must not receive request data"
                    )

    assert not violations, f"{path.relative_to(REPO_ROOT)}: {violations}"
