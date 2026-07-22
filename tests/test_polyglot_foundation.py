"""Polyglot CI and placeholder-package safety checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_runtime_package():
    spec = importlib.util.spec_from_file_location(
        "runtime_package", REPO_ROOT / "scripts" / "runtime_package.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_marker_only_runtime_directories_are_genuinely_absent() -> None:
    module = _load_runtime_package()
    assert module.detect("javascript") == (False, "")
    assert module.detect("maui") == (False, "")


def test_partial_runtime_package_cannot_be_silently_skipped(tmp_path: Path) -> None:
    module = _load_runtime_package()
    module.REPO_ROOT = tmp_path
    package_root = tmp_path / "packages" / "javascript"
    package_root.mkdir(parents=True)
    (package_root / "index.js").write_text("export {};\n", encoding="utf-8")

    with pytest.raises(ValueError, match="without package.json"):
        module.detect("javascript")


def test_ci_preserves_python_and_self_activates_runtime_gates() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    for python_version in ('"3.11"', '"3.12"', '"3.13"'):
        assert python_version in workflow
    assert "pytest tests --ignore=tests/smoke" in workflow
    assert "pytest tests/smoke" in workflow
    assert "runtime_package.py detect javascript" in workflow
    assert "runtime_package.py detect maui" in workflow
    assert "npm audit --audit-level=high" in workflow
    assert "NuGetAuditMode=all" in workflow


def test_publish_lanes_are_tag_validated_and_dry_run_capable() -> None:
    for name, package in (
        ("publish.yml", "python"),
        ("publish-javascript.yml", "javascript"),
        ("publish-maui.yml", "maui"),
    ):
        workflow = (REPO_ROOT / ".github" / "workflows" / name).read_text(
            encoding="utf-8"
        )
        assert "dry_run:" in workflow
        assert "validate_publish_tag.py" in workflow
        if package != "python":
            assert f"--package {package}" in workflow
        assert "id-token: write" in workflow
