"""Release metadata checks."""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_project_metadata_declares_release_contract() -> None:
    pyproject = _pyproject()
    project = pyproject["project"]

    assert project["name"] == "honua-migrate"
    assert project["license"] == "Apache-2.0"
    assert project["requires-python"] == ">=3.11"
    assert project["scripts"]["honua-migrate"] == "honua_migrate.cli:main"
    assert project["scripts"]["honua-esri-assess"] == "honua_esri_assess.cli:main"
    assert set(project["urls"].values()) == {
        "https://github.com/honua-io/honua-migrate",
        "https://github.com/honua-io/honua-migrate/issues",
        "https://github.com/honua-io/honua-migrate/blob/trunk/CHANGELOG.md",
    }
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
        "src/honua_esri_assess",
        "src/honua_migrate",
    ]


def test_runtime_dependencies_are_pinned_with_lower_bounds() -> None:
    project = _pyproject()["project"]
    dependencies = set(project["dependencies"])

    assert "typer>=0.12,<1" in dependencies
    assert "jsonschema>=4.21,<5" in dependencies
    assert "requests>=2.31,<3" in dependencies
    assert "tenacity>=8.2,<10" in dependencies
    all_requirements = dependencies | {
        requirement
        for requirements in project["optional-dependencies"].values()
        for requirement in requirements
    }
    assert not any(
        re.match(r"(?i)honua[-_.]sdk(?:\s|\[|[<>=!~;]|$)", requirement)
        for requirement in all_requirements
    ), "honua-sdk 0.x owns a colliding honua-migrate console script"


def test_release_please_manifest_matches_project_version() -> None:
    manifest = json.loads(
        (REPO_ROOT / ".release-please-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["."] == _pyproject()["project"]["version"]
    javascript_package = json.loads(
        (REPO_ROOT / "packages" / "javascript" / "package.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["packages/javascript"] == javascript_package["version"]
    assert manifest["packages/maui"] == "0.0.0"


def test_release_please_config_uses_component_tags() -> None:
    config = json.loads(
        (REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8")
    )
    package = config["packages"]["."]

    assert package["release-type"] == "python"
    assert package["component"] == "honua-migrate"
    assert package["tag-separator"] == "-"
    assert package["include-component-in-tag"] is True
    assert package["bump-minor-pre-major"] is True
    assert package["extra-files"] == [
        "src/honua_migrate/__init__.py",
        "src/honua_esri_assess/__init__.py",
    ]
    javascript_release_type = (
        "node"
        if (REPO_ROOT / "packages/javascript/package.json").is_file()
        else "simple"
    )
    assert (
        config["packages"]["packages/javascript"]["release-type"]
        == javascript_release_type
    )
    assert config["packages"]["packages/javascript"]["component"] == "javascript"
    assert config["packages"]["packages/maui"]["release-type"] == "simple"
    assert config["packages"]["packages/maui"]["component"] == "maui"


def test_publish_workflow_publishes_only_from_validated_release_tags() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert 'tags:\n      - "honua-migrate-v*"' in workflow
    assert "github.event_name == 'push'" in workflow
    assert "startsWith(github.ref, 'refs/tags/honua-migrate-v')" in workflow
    assert "inputs.release_tag != ''" in workflow
    assert 'test "$RELEASE_TAG" = "$GITHUB_REF_NAME"' in workflow
    assert 'test "$RELEASE_SHA" = "$GITHUB_SHA"' in workflow
    assert "--require-git-ref" in workflow
    assert "environment:\n      name: pypi-honua-migrate" in workflow
    assert "id-token: write" in workflow
    assert "gh release upload" in workflow
    assert "validate_python_dist.py" in workflow
    assert "--compare" in workflow
    assert "honua-migrate\" assess --help" in workflow
    assert "honua-esri-assess\" --help" in workflow
    assert "skip-existing" not in workflow
    assert "password:" not in workflow
    assert "dry_run" not in workflow

    release_please = (
        REPO_ROOT / ".github" / "workflows" / "release-please.yml"
    ).read_text(encoding="utf-8")
    assert "actions: write" in release_please
    assert "steps.release.outputs.release_created == 'true'" in release_please
    assert "gh workflow run publish.yml --ref \"$RELEASE_TAG\"" in release_please
    assert '-f release_tag="$RELEASE_TAG"' in release_please
    assert '-f release_sha="$RELEASE_SHA"' in release_please


def test_release_workflows_pin_third_party_actions_to_commits() -> None:
    for relative in (
        Path(".github/workflows/publish.yml"),
        Path(".github/workflows/release-please.yml"),
    ):
        workflow = (REPO_ROOT / relative).read_text(encoding="utf-8")
        uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)
        assert uses, relative
        for action in uses:
            ref = action.rsplit("@", 1)[-1]
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{relative}: {action}"


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

    version = _pyproject()["project"]["version"]
    assert module.main([f"honua-migrate-v{version}"]) == 0
    assert module.main([f"honua-esri-assess-v{version}"]) == 1
    assert module.main(["main"]) == 1
    assert module.main([]) == 1
    assert module.main(["--allow-untagged"]) == 0


def test_runtime_release_tags_follow_checked_out_package_state(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "validate_runtime_publish_tag",
        REPO_ROOT / "scripts" / "validate_publish_tag.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.chdir(REPO_ROOT)
    javascript_present = (REPO_ROOT / "packages/javascript/package.json").is_file()
    javascript_version = module.javascript_version() if javascript_present else "0.1.0"
    assert module.main(
        [f"javascript-v{javascript_version}", "--package", "javascript"]
    ) == (0 if javascript_present else 1)
    if javascript_present:
        assert (
            module.main(
                ["javascript-v0.1.2-beta.0", "--package", "javascript"]
            )
            == 1
        )

    maui_present = any((REPO_ROOT / "packages/maui").rglob("*.csproj"))
    maui_version = module.maui_version() if maui_present else "0.1.0"
    assert module.main([f"maui-v{maui_version}", "--package", "maui"]) == (
        0 if maui_present else 1
    )
    assert module.main(["--allow-untagged", "--package", "javascript"]) == 0


def test_publish_tag_validator_requires_one_tag_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "validate_publish_git_context",
        REPO_ROOT / "scripts" / "validate_publish_tag.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tag = "honua-migrate-v0.7.1"
    sha = "a" * 40
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF", f"refs/tags/{tag}")
    monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setattr(module, "_git", lambda *args: sha)
    module.validate_git_release_context(tag)

    monkeypatch.setenv("GITHUB_REF", "refs/tags/honua-migrate-v9.9.9")
    with pytest.raises(ValueError, match="GITHUB_REF"):
        module.validate_git_release_context(tag)
