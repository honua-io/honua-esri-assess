#!/usr/bin/env python3
"""Fail closed unless a publish tag matches package and checkout metadata."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

PYTHON_PROJECT = "honua-migrate"
PYTHON_TAG_PREFIX = f"{PYTHON_PROJECT}-v"
_SAFE_VERSION = re.compile(
    r"[0-9]+(?:\.[0-9]+){2}(?:[.-][0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?"
)


def python_project() -> tuple[str, str]:
    with Path("pyproject.toml").open("rb") as fh:
        project = tomllib.load(fh)["project"]
    return str(project["name"]), str(project["version"])


def project_version() -> str:
    name, version = python_project()
    if name != PYTHON_PROJECT:
        raise ValueError(
            f"Expected Python project {PYTHON_PROJECT!r}, found {name!r}."
        )
    return version


def javascript_version() -> str:
    manifest = Path("packages/javascript/package.json")
    if not manifest.is_file():
        raise ValueError("JavaScript package is absent; refusing a JavaScript release.")
    return str(json.loads(manifest.read_text(encoding="utf-8"))["version"])


def maui_version() -> str:
    tool_projects: list[tuple[Path, ET.Element]] = []
    for project in sorted(Path("packages/maui").rglob("*.csproj")):
        root = ET.parse(project).getroot()
        pack_as_tool = next(
            (
                (element.text or "").strip().lower()
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "PackAsTool"
            ),
            "",
        )
        if pack_as_tool == "true":
            tool_projects.append((project, root))
    if len(tool_projects) != 1:
        raise ValueError(
            f"Expected exactly one MAUI PackAsTool project, found {len(tool_projects)}."
        )
    project, root = tool_projects[0]
    version = next(
        (
            (element.text or "").strip()
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "Version" and element.text
        ),
        "",
    )
    if not version:
        raise ValueError(f"{project}: Version is required for publishing.")
    return version


PACKAGE_SPECS: dict[str, tuple[str, Callable[[], str], str]] = {
    "python": (PYTHON_TAG_PREFIX, project_version, PYTHON_PROJECT),
    "javascript": ("javascript-v", javascript_version, "JavaScript package"),
    "maui": ("maui-v", maui_version, "MAUI dotnet tool"),
}


def _source_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    matches = re.findall(
        r'^\s*__version__\s*=\s*["\']([^"\']+)["\']\s*$',
        text,
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise ValueError(f"{path}: expected exactly one literal __version__ assignment.")
    return matches[0]


def validate_python_source_versions(expected: str) -> None:
    for path in (
        Path("src/honua_migrate/__init__.py"),
        Path("src/honua_esri_assess/__init__.py"),
    ):
        actual = _source_version(path)
        if actual != expected:
            raise ValueError(
                f"{path}: source version {actual!r} does not match project version "
                f"{expected!r}."
            )


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git failed"
        raise ValueError(detail)
    return result.stdout.strip()


def validate_git_release_context(tag: str, expected_sha: str | None = None) -> None:
    """Prove the checked-out commit is exactly the workflow's release tag."""

    ref_type = os.environ.get("GITHUB_REF_TYPE")
    ref = os.environ.get("GITHUB_REF")
    workflow_sha = expected_sha or os.environ.get("GITHUB_SHA")
    if ref_type != "tag":
        raise ValueError(f"Expected GITHUB_REF_TYPE='tag', got {ref_type!r}.")
    expected_ref = f"refs/tags/{tag}"
    if ref != expected_ref:
        raise ValueError(f"Expected GITHUB_REF={expected_ref!r}, got {ref!r}.")
    if not workflow_sha:
        raise ValueError("GITHUB_SHA is required for a release publish.")

    head = _git("rev-parse", "HEAD^{commit}")
    tag_commit = _git("rev-parse", f"refs/tags/{tag}^{{commit}}")
    workflow_commit = _git("rev-parse", f"{workflow_sha}^{{commit}}")
    if len({head, tag_commit, workflow_commit}) != 1:
        raise ValueError(
            "Release tag, checked-out HEAD, and GITHUB_SHA must resolve to the "
            f"same commit (tag={tag_commit}, head={head}, workflow={workflow_commit})."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", nargs="?")
    parser.add_argument("--allow-untagged", action="store_true")
    parser.add_argument("--package", choices=tuple(PACKAGE_SPECS), default="python")
    parser.add_argument(
        "--require-git-ref",
        action="store_true",
        help="Require the GitHub tag ref, checkout, and workflow SHA to match.",
    )
    args = parser.parse_args(argv)

    try:
        tag_prefix, version_reader, project = PACKAGE_SPECS[args.package]
        expected = version_reader()
        if not _SAFE_VERSION.fullmatch(expected):
            raise ValueError(f"Unsafe or unsupported package version {expected!r}.")
        if args.package == "python":
            validate_python_source_versions(expected)

        tag = args.tag
        if tag is None and not args.allow_untagged:
            tag = os.environ.get("GITHUB_REF_NAME")
        if not tag:
            if args.allow_untagged:
                print(
                    f"Validated {project} {expected}; untagged build-only run allowed."
                )
                return 0
            raise ValueError("Missing release tag.")

        expected_tag = f"{tag_prefix}{expected}"
        if tag != expected_tag:
            raise ValueError(f"Expected tag {expected_tag!r}, got {tag!r}.")
        if args.require_git_ref:
            validate_git_release_context(tag)
    except (
        ET.ParseError,
        KeyError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    location = f" at {_git('rev-parse', 'HEAD')}" if args.require_git_ref else ""
    print(f"Validated {tag} for {project} {expected}{location}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
