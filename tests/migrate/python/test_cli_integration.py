from __future__ import annotations

import builtins
import json
from pathlib import Path

from typer.testing import CliRunner

from honua_migrate.app import cli_app
from honua_migrate.cli import main


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "workflow.py"
    path.write_text(
        "import arcpy\n"
        "arcpy.analysis.Buffer('roads', 'buffered', '10 Meters')\n"
        "arcpy.sa.Kriging('stations', 'surface')\n",
        encoding="utf-8",
    )
    return path


def test_canonical_python_command_tree_exposes_all_operations() -> None:
    result = CliRunner().invoke(
        cli_app,
        ["code", "python", "--help"],
        env={"COLUMNS": "160"},
    )

    assert result.exit_code == 0
    for command in ("scan", "translate", "run", "pyt", "atbx", "gpservice"):
        assert command in result.output


def test_canonical_scan_reaches_python_engine(tmp_path: Path) -> None:
    output = tmp_path / "scan.json"

    assert (
        main(
            [
                "code",
                "python",
                "scan",
                str(_script(tmp_path)),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["translatableCount"] == 1
    assert report["unsupportedCount"] == 1


def test_canonical_dry_run_never_imports_public_sdk(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "dry-run.json"
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "honua_sdk" or name.startswith("honua_sdk."):
            raise AssertionError("dry-run must not import honua-sdk")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert (
        main(
            [
                "code",
                "python",
                "run",
                str(_script(tmp_path)),
                "--server",
                "https://example.invalid",
                "--output",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["dryRun"] is True
    assert len(result["executions"]) == 1
    assert result["skipped"] == []
