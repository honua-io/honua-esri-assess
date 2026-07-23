#!/usr/bin/env python3
"""Validate that a release tag matches the pyproject version."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT = "honua-esri-assess"
TAG_PREFIX = f"{PROJECT}-v"


def project_version() -> str:
    with Path("pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    return str(pyproject["project"]["version"])


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


PACKAGE_SPECS = {
    "python": (TAG_PREFIX, project_version, PROJECT),
    "javascript": ("javascript-v", javascript_version, "JavaScript package"),
    "maui": ("maui-v", maui_version, "MAUI dotnet tool"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", nargs="?")
    parser.add_argument("--allow-untagged", action="store_true")
    parser.add_argument("--package", choices=tuple(PACKAGE_SPECS), default="python")
    args = parser.parse_args(argv)

    tag = args.tag
    if tag is None and not args.allow_untagged:
        tag = os.environ.get("GITHUB_REF_NAME")
    if not tag:
        if args.allow_untagged:
            print("No release tag supplied; untagged dry run allowed.")
            return 0
        print("Missing release tag.", file=sys.stderr)
        return 1

    tag_prefix, version_reader, project = PACKAGE_SPECS[args.package]
    if not tag.startswith(tag_prefix):
        print(f"Expected tag prefix {tag_prefix!r}, got {tag!r}.", file=sys.stderr)
        return 1

    try:
        expected = version_reader()
    except (ET.ParseError, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    actual = tag.removeprefix(tag_prefix)
    if actual != expected:
        print(
            f"Tag version {actual!r} does not match {project} version {expected!r}.",
            file=sys.stderr,
        )
        return 1

    print(f"Validated {tag} for {project} {expected}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
