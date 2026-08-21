#!/usr/bin/env python3
"""Fail closed unless PyPI lacks the version or has exact artifact parity."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT = "honua-migrate"
PYPI_URL = "https://pypi.org/pypi/{project}/{version}/json"


class ParityError(ValueError):
    """The existing PyPI release does not match the built artifacts exactly."""


def project_version(repo_root: Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as fh:
        project = tomllib.load(fh)["project"]
    if project.get("name") != PROJECT:
        raise ParityError(
            f"Expected project name {PROJECT!r}, found {project.get('name')!r}."
        )
    return str(project["version"])


def distribution_hashes(dist_dir: Path) -> dict[str, str]:
    wheel = sorted(dist_dir.glob("*.whl"))
    sdist = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheel) != 1 or len(sdist) != 1:
        raise ParityError("Expected exactly one wheel and one source distribution.")
    expected_paths = wheel + sdist
    extra = sorted(
        path.name
        for path in dist_dir.iterdir()
        if path.is_file() and path not in expected_paths
    )
    if extra:
        raise ParityError(f"Unexpected distribution files: {extra}.")
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in expected_paths
    }


def fetch_pypi_release(project: str, version: str) -> dict[str, Any] | None:
    request = urllib.request.Request(
        PYPI_URL.format(project=project, version=version),
        headers={"Accept": "application/json", "User-Agent": "honua-migrate-release"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def publish_required(
    dist_dir: Path,
    repo_root: Path,
    fetch: Callable[[str, str], dict[str, Any] | None] = fetch_pypi_release,
) -> bool:
    version = project_version(repo_root)
    expected = distribution_hashes(dist_dir)
    release = fetch(PROJECT, version)
    if release is None:
        return True

    info = release.get("info")
    if not isinstance(info, dict):
        raise ParityError("PyPI response has no project metadata.")
    if info.get("name") != PROJECT or info.get("version") != version:
        raise ParityError("PyPI project name/version does not match the build.")

    urls = release.get("urls")
    if not isinstance(urls, list):
        raise ParityError("PyPI response has no release file list.")
    actual: dict[str, str] = {}
    for item in urls:
        if not isinstance(item, dict):
            raise ParityError("PyPI returned a malformed release file entry.")
        filename = item.get("filename")
        digests = item.get("digests")
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        if not isinstance(filename, str) or not isinstance(digest, str):
            raise ParityError("PyPI release file is missing its filename or SHA-256.")
        if filename in actual:
            raise ParityError(f"PyPI returned duplicate filename {filename!r}.")
        actual[filename] = digest

    if actual != expected:
        raise ParityError(
            f"PyPI version {version} differs from the build: "
            f"expected {expected!r}, found {actual!r}."
        )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        required = publish_required(args.dist, args.repo_root)
    except (OSError, KeyError, ParityError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"publish_required={str(required).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
