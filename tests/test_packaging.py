"""Packaging tests for release artifacts."""

from __future__ import annotations

import hashlib
import os
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
            ".venv",
            "build",
            "dist",
            "node_modules",
            "*.egg-info",
        ),
    )
    first_dist = tmp_path / "dist-a"
    second_dist = tmp_path / "dist-b"
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = "1787198400"

    for dist_dir in (first_dist, second_dist):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(dist_dir),
            ],
            cwd=build_root,
            env=env,
            check=True,
        )

    validation = subprocess.run(
        [
            sys.executable,
            "scripts/validate_python_dist.py",
            str(first_dist),
            "--compare",
            str(second_dist),
        ],
        cwd=build_root,
        capture_output=True,
        check=False,
        text=True,
    )
    assert validation.returncode == 0, validation.stderr

    first_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(first_dist.iterdir())
    }
    second_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(second_dist.iterdir())
    }
    assert first_hashes == second_hashes

    wheels = sorted(first_dist.glob("*.whl"))
    sdists = sorted(first_dist.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())

    assert "honua_esri_assess/cli.py" in names
    assert "honua_migrate/cli.py" in names
    assert "honua_migrate/py.typed" in names
    assert "honua_esri_assess/schemas/esri-footprint-v0.1.json" in names
    assert "honua_esri_assess/schemas/esri-footprint-v0.2.json" in names
    assert wheels[0].name.endswith("-py3-none-any.whl")
