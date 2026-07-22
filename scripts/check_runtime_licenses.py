#!/usr/bin/env python3
"""Reject incompatible or unverifiable JavaScript and NuGet licenses."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INCOMPATIBLE = ("AGPL", "GPL", "LGPL", "SSPL", "BUSL", "ELV2", "PROPRIETARY")
LEGACY_NUGET_LICENSES = {
    (
        "xunit.abstractions",
        "2.0.3",
        "https://raw.githubusercontent.com/xunit/xunit/master/license.txt",
    ): "Apache-2.0",
}


def _compatible(expression: str) -> bool:
    normalized = expression.upper()
    return bool(normalized.strip()) and not any(
        token in normalized for token in INCOMPATIBLE
    )


def check_javascript() -> list[str]:
    lock_path = REPO_ROOT / "packages" / "javascript" / "package-lock.json"
    if not lock_path.is_file():
        return ["packages/javascript/package-lock.json is required"]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for path, package in sorted(lock.get("packages", {}).items()):
        if not path or package.get("link"):
            continue
        license_expression = str(package.get("license", "")).strip()
        if not license_expression:
            failures.append(f"{path}: missing license metadata")
        elif not _compatible(license_expression):
            failures.append(f"{path}: incompatible license {license_expression!r}")
    return failures


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _nuspec_license(nuspec: Path) -> tuple[str | None, str | None]:
    root = ET.parse(nuspec).getroot()
    license_url = None
    for element in root.iter():
        if _local_name(element.tag) == "license" and element.text:
            if element.attrib.get("type", "").lower() == "expression":
                return element.text.strip(), license_url
        if _local_name(element.tag) == "licenseUrl" and element.text:
            license_url = element.text.strip()
    return None, license_url


def check_maui() -> list[str]:
    assets_files = sorted((REPO_ROOT / "packages" / "maui").rglob("project.assets.json"))
    if not assets_files:
        return ["No restored project.assets.json files found under packages/maui"]

    packages: dict[tuple[str, str], Path] = {}
    failures: list[str] = []
    for assets_path in assets_files:
        assets = json.loads(assets_path.read_text(encoding="utf-8-sig"))
        package_folders = [Path(path) for path in assets.get("packageFolders", {})]
        if not package_folders:
            failures.append(f"{assets_path}: no NuGet package folder recorded")
            continue
        for identity, details in assets.get("libraries", {}).items():
            if details.get("type") != "package":
                continue
            package_id, version = identity.rsplit("/", 1)
            packages[(package_id, version)] = package_folders[0]

    for (package_id, version), package_folder in sorted(packages.items()):
        package_dir = package_folder / package_id.lower() / version.lower()
        candidates = sorted(package_dir.glob("*.nuspec"))
        if len(candidates) != 1:
            failures.append(f"{package_id} {version}: expected one local .nuspec")
            continue
        expression, license_url = _nuspec_license(candidates[0])
        if expression is None and license_url is not None:
            expression = LEGACY_NUGET_LICENSES.get(
                (package_id.lower(), version, license_url)
            )
        if expression is None:
            failures.append(f"{package_id} {version}: missing SPDX license expression")
        elif not _compatible(expression):
            failures.append(f"{package_id} {version}: incompatible license {expression!r}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", choices=("javascript", "maui"))
    args = parser.parse_args(argv)
    try:
        failures = check_javascript() if args.runtime == "javascript" else check_maui()
    except (ET.ParseError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"{args.runtime} dependency licenses passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
