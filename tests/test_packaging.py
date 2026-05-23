"""Packaging tests for release artifacts."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_build_artifacts_include_cli_and_schema(tmp_path: Path) -> None:
    build_root = tmp_path / "repo"
    shutil.copytree(
        REPO_ROOT,
        build_root,
        ignore=shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "build",
            "dist",
            "*.egg-info",
        ),
    )
    dist_dir = tmp_path / "dist"

    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(dist_dir)],
        cwd=build_root,
        check=True,
    )

    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())

    assert "honua_esri_assess/cli.py" in names
    assert "honua_esri_assess/schemas/esri-footprint-v0.1.json" in names
    assert wheels[0].name.endswith("-py3-none-any.whl")
