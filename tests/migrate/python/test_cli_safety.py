from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from honua_migrate.cli import main as canonical_main
from honua_migrate.code.python._cli import main as module_main
from honua_migrate.contracts import (
    EXIT_SAFETY_REFUSAL,
    EXIT_SUCCESS,
    EXIT_VALIDATION_ERROR,
)


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "workflow.py"
    path.write_text(
        "import arcpy\n"
        "arcpy.analysis.Buffer('roads', 'buffered', '10 Meters')\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("entrypoint", "prefix"),
    [
        (module_main, []),
        (canonical_main, ["code", "python"]),
    ],
)
def test_ack_refusal_precedes_file_url_output_and_sdk_resolution(
    entrypoint,
    prefix: list[str],
    tmp_path: Path,
    capsys,
) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("original", encoding="utf-8")
    unsafe = "https://alice:secret@example.test/?token=raw-secret"

    result = entrypoint(
        [
            *prefix,
            "run",
            str(tmp_path / "missing.py"),
            "--server",
            unsafe,
            "--output",
            str(existing),
        ]
    )

    captured = capsys.readouterr()
    assert result == EXIT_SAFETY_REFUSAL
    assert existing.read_text(encoding="utf-8") == "original"
    assert "alice" not in captured.err
    assert "secret" not in captured.err
    assert "token" not in captured.err


def test_dry_run_needs_no_ack_and_does_not_import_sdk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "honua_sdk" or name.startswith("honua_sdk."):
            raise AssertionError("dry-run must remain SDK-free")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert (
        module_main(
            [
                "run",
                str(_script(tmp_path)),
                "--server",
                "https://example.test",
                "--dry-run",
            ]
        )
        == EXIT_SUCCESS
    )


def test_existing_output_refuses_then_force_replaces(tmp_path: Path) -> None:
    output = tmp_path / "scan.json"
    output.write_text("original", encoding="utf-8")
    base = ["scan", str(_script(tmp_path)), "--output", str(output)]

    assert module_main(base) == EXIT_VALIDATION_ERROR
    assert output.read_text(encoding="utf-8") == "original"
    assert module_main([*base, "--force"]) == EXIT_SUCCESS
    assert '"translatableCount": 1' in output.read_text(encoding="utf-8")


def test_all_outputs_are_preflighted_before_any_artifact_is_written(
    tmp_path: Path,
) -> None:
    output = tmp_path / "plan.json"
    evidence = tmp_path / "evidence.json"
    evidence.write_text("original", encoding="utf-8")

    result = module_main(
        [
            "translate",
            str(_script(tmp_path)),
            "--output",
            str(output),
            "--evidence",
            str(evidence),
        ]
    )

    assert result == EXIT_VALIDATION_ERROR
    assert not output.exists()
    assert evidence.read_text(encoding="utf-8") == "original"


def test_invalid_server_url_is_rejected_without_reflection(
    tmp_path: Path,
    capsys,
) -> None:
    unsafe = "https://alice:secret@example.test/path?token=raw-secret#fragment"

    result = module_main(
        [
            "run",
            str(tmp_path / "missing.py"),
            "--server",
            unsafe,
            "--yes",
        ]
    )

    captured = capsys.readouterr()
    assert result == EXIT_VALIDATION_ERROR
    assert captured.err.strip() == "invalid server URL"
    assert unsafe not in captured.out
    assert unsafe not in captured.err


def test_atomic_write_failure_preserves_existing_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import honua_esri_assess.output_io

    output = tmp_path / "scan.json"
    output.write_text("original", encoding="utf-8")

    def fail_replace(source, destination):
        del source, destination
        raise OSError("simulated replace failure")

    monkeypatch.setattr(honua_esri_assess.output_io.os, "replace", fail_replace)
    result = module_main(
        [
            "scan",
            str(_script(tmp_path)),
            "--output",
            str(output),
            "--force",
        ]
    )

    assert result == EXIT_VALIDATION_ERROR
    assert output.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".scan.json.*.tmp")) == []
