#!/usr/bin/env python3
"""Detect optional runtime packages and read .NET tool metadata."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKERS = {".gitkeep"}


def _files_under(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(item for item in path.rglob("*") if item.is_file())


def _detect_javascript() -> tuple[bool, str]:
    root = REPO_ROOT / "packages" / "javascript"
    manifest = root / "package.json"
    files = _files_under(root)
    if manifest.is_file():
        return True, str(manifest.relative_to(REPO_ROOT))
    unexpected = [item for item in files if item.name not in MARKERS]
    if unexpected:
        names = ", ".join(str(item.relative_to(REPO_ROOT)) for item in unexpected)
        raise ValueError(f"JavaScript package files exist without package.json: {names}")
    return False, ""


def _detect_maui() -> tuple[bool, str]:
    root = REPO_ROOT / "packages" / "maui"
    projects = sorted(root.rglob("*.csproj")) if root.exists() else []
    files = _files_under(root)
    if projects:
        return True, str(projects[0].relative_to(REPO_ROOT))
    unexpected = [item for item in files if item.name not in MARKERS]
    if unexpected:
        names = ", ".join(str(item.relative_to(REPO_ROOT)) for item in unexpected)
        raise ValueError(f"MAUI package files exist without a .csproj: {names}")
    return False, ""


def detect(runtime: str) -> tuple[bool, str]:
    if runtime == "javascript":
        return _detect_javascript()
    return _detect_maui()


def _property(root: ET.Element, name: str) -> str | None:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == name and element.text:
            value = element.text.strip()
            if value:
                return value
    return None


def dotnet_tool_metadata() -> dict[str, str]:
    package_root = REPO_ROOT / "packages" / "maui"
    tools: list[tuple[Path, ET.Element]] = []
    for project in sorted(package_root.rglob("*.csproj")):
        root = ET.parse(project).getroot()
        if (_property(root, "PackAsTool") or "").lower() == "true":
            tools.append((project, root))
    if len(tools) != 1:
        raise ValueError(f"Expected exactly one PackAsTool project, found {len(tools)}.")

    project, root = tools[0]
    package_id = _property(root, "PackageId")
    version = _property(root, "Version")
    command = _property(root, "ToolCommandName")
    missing = [
        name
        for name, value in (
            ("PackageId", package_id),
            ("Version", version),
            ("ToolCommandName", command),
        )
        if value is None
    ]
    if missing:
        raise ValueError(f"{project}: missing required metadata: {', '.join(missing)}")
    return {
        "project": str(project.relative_to(REPO_ROOT)),
        "package_id": package_id or "",
        "version": version or "",
        "command": command or "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect")
    detect_parser.add_argument("runtime", choices=("javascript", "maui"))

    subparsers.add_parser("dotnet-tool-metadata")
    args = parser.parse_args(argv)

    try:
        if args.command == "detect":
            present, manifest = detect(args.runtime)
            print(f"present={str(present).lower()}")
            print(f"manifest={manifest}")
        else:
            for key, value in dotnet_tool_metadata().items():
                print(f"{key}={value}")
    except (ET.ParseError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
