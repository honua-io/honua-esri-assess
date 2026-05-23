#!/usr/bin/env python3
"""Validate that a release tag matches the pyproject version."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

PROJECT = "honua-esri-assess"
TAG_PREFIX = f"{PROJECT}-v"


def project_version() -> str:
    with Path("pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    return str(pyproject["project"]["version"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", nargs="?")
    parser.add_argument("--allow-untagged", action="store_true")
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

    if not tag.startswith(TAG_PREFIX):
        print(f"Expected tag prefix {TAG_PREFIX!r}, got {tag!r}.", file=sys.stderr)
        return 1

    expected = project_version()
    actual = tag.removeprefix(TAG_PREFIX)
    if actual != expected:
        print(
            f"Tag version {actual!r} does not match pyproject version {expected!r}.",
            file=sys.stderr,
        )
        return 1

    print(f"Validated {tag} for {PROJECT} {expected}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
