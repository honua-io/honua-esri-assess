#!/usr/bin/env python3
"""Fail when installed runtime dependencies advertise incompatible licenses."""

from __future__ import annotations

import importlib.metadata as metadata
import sys

from packaging.requirements import Requirement

PROJECT = "honua-esri-assess"
INCOMPATIBLE = ("AGPL", "GPL", "LGPL", "ELV2", "SSPL", "PROPRIETARY")


def requirement_name(requirement: str) -> str | None:
    parsed = Requirement(requirement)
    if parsed.marker is not None and not parsed.marker.evaluate({"extra": ""}):
        return None
    return parsed.name.replace("_", "-").lower()


def runtime_dependency_names() -> set[str]:
    seen: set[str] = set()
    pending = [
        name
        for req in metadata.requires(PROJECT) or []
        if (name := requirement_name(req)) is not None
    ]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            requirements = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        for requirement in requirements:
            child = requirement_name(requirement)
            if child is not None and child not in seen:
                pending.append(child)
    return seen


def advertised_license(dist_name: str) -> str:
    dist = metadata.distribution(dist_name)
    meta = dist.metadata
    license_text = meta.get("License-Expression") or meta.get("License") or ""
    classifiers = " ".join(meta.get_all("Classifier") or [])
    return f"{license_text} {classifiers}".upper()


def main() -> int:
    failures: list[str] = []
    for name in sorted(runtime_dependency_names()):
        try:
            license_text = advertised_license(name)
        except metadata.PackageNotFoundError:
            failures.append(f"{name}: package is not installed")
            continue
        if any(token in license_text for token in INCOMPATIBLE):
            failures.append(f"{name}: incompatible license metadata {license_text!r}")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    print("Runtime dependency license metadata is Apache-2.0-compatible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
