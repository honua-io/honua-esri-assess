#!/usr/bin/env python3
"""Print only the Python distribution's runtime requirements for auditing."""

from __future__ import annotations

import tomllib
from pathlib import Path


def main() -> int:
    with Path("pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    for requirement in project.get("dependencies", []):
        print(requirement)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
