"""Release metadata checks."""

from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_project_metadata_declares_release_contract() -> None:
    pyproject = _pyproject()
    project = pyproject["project"]

    assert project["license"] == "Apache-2.0"
    assert project["requires-python"] == ">=3.11"
    assert project["scripts"]["honua-esri-assess"] == "honua_esri_assess.cli:main"
    for classifier in (
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Scientific/Engineering :: GIS",
    ):
        assert classifier in project["classifiers"]


def test_build_backend_and_hatch_targets_are_configured() -> None:
    pyproject = _pyproject()

    assert pyproject["build-system"]["build-backend"] == "hatchling.build"
    assert pyproject["tool"]["hatch"]["build"]["reproducible"] is True
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/honua_esri_assess"
    ]


def test_runtime_dependencies_are_pinned_with_lower_bounds() -> None:
    dependencies = set(_pyproject()["project"]["dependencies"])

    assert "typer>=0.12,<1" in dependencies
    assert "jsonschema>=4.21,<5" in dependencies
    assert "requests>=2.31,<3" in dependencies
    assert "tenacity>=8.2,<10" in dependencies


def test_release_please_manifest_matches_initial_version() -> None:
    manifest = json.loads(
        (REPO_ROOT / ".release-please-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == {".": "0.1.0"}


def test_release_please_config_uses_component_tags() -> None:
    config = json.loads(
        (REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8")
    )
    package = config["packages"]["."]

    assert package["release-type"] == "python"
    assert package["component"] == "honua-esri-assess"
    assert package["tag-separator"] == "-"
    assert package["include-component-in-tag"] is True
    assert package["bump-minor-pre-major"] is True


def test_publish_workflow_publishes_only_from_validated_release_tags() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "github.event_name != 'workflow_dispatch' || inputs.dry_run == false"
        in workflow
    )
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.dry_run == true"
        in workflow
    )
    assert "startsWith(github.ref, 'refs/tags/honua-esri-assess-v')" in workflow


def test_publish_tag_validator_rejects_untagged_non_dry_run(
    monkeypatch,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "validate_publish_tag",
        REPO_ROOT / "scripts" / "validate_publish_tag.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    assert module.main(["honua-esri-assess-v0.1.0"]) == 0
    assert module.main(["main"]) == 1
    assert module.main([]) == 1
    assert module.main(["--allow-untagged"]) == 0
