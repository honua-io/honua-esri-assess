"""Overwrite-refusal and atomic-write tests (issue #76).

By default a ``scan``/``report`` must refuse to clobber an existing artifact
(requiring ``--force``), and any write it does perform must be atomic so a
mid-write failure can never replace a prior valid artifact with a truncated one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from honua_esri_assess.cli import main as cli_main
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.commands.scan_handlers import HANDLERS, ScanHandler, register
from honua_esri_assess.output_io import OutputExistsError, atomic_write_text


@pytest.fixture(autouse=True)
def restore_handlers() -> Iterator[None]:
    original = dict(HANDLERS)
    try:
        yield
    finally:
        HANDLERS.clear()
        HANDLERS.update(original)


def _sample_footprint() -> dict:
    return {
        "schemaVersion": "v0.1",
        "generatedAt": "2026-01-01T00:00:00Z",
        "tool": {"name": "honua-esri-assess", "version": "0.1.0"},
        "source": {
            "kind": "filegdb",
            "locator": "sha256:" + "0" * 64,
            "capturedAt": "2026-01-01T00:00:00Z",
        },
        "filegdb": {"featureClassCount": 1, "pathHash": "sha256:" + "0" * 64},
        "inventory": [
            {
                "kind": "filegdb-feature-class",
                "name": "Parcels",
                "geometryType": "esriGeometryPolygon",
                "sr": {"wkid": 4326},
            }
        ],
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": 0,
                "filegdb-feature-class": 1,
            },
            "layers": 0,
            "featureClasses": 1,
        },
        "diagnostics": [],
    }


def _stub_filegdb() -> None:
    def _fake_scan(options: ScanOptions) -> ScanResult:
        del options
        return ScanResult(footprint=_sample_footprint())

    register(ScanHandler(name="filegdb", run=_fake_scan))


def _run_scan(tmp_path: Path, output: Path, *force: str) -> int:
    return cli_main(
        [
            "scan",
            "filegdb",
            "--target",
            str(tmp_path),
            "--output",
            str(output),
            *force,
        ]
    )


# --- scan overwrite refusal ----------------------------------------------


def test_scan_refuses_to_overwrite_without_force(tmp_path: Path, capsys) -> None:
    _stub_filegdb()
    output = tmp_path / "EsriFootprint.json"
    output.write_text("PRIOR ARTIFACT", encoding="utf-8")

    exit_code = _run_scan(tmp_path, output)
    captured = capsys.readouterr()

    assert exit_code == 20
    assert "error[output-exists]" in captured.err
    # The prior artifact must be untouched.
    assert output.read_text(encoding="utf-8") == "PRIOR ARTIFACT"
    # Prospect-safe: no traceback, no absolute paths leaked.
    assert "Traceback" not in captured.err
    assert str(output) not in captured.err


def test_scan_overwrites_with_force(tmp_path: Path, capsys) -> None:
    _stub_filegdb()
    output = tmp_path / "EsriFootprint.json"
    output.write_text("PRIOR ARTIFACT", encoding="utf-8")

    exit_code = _run_scan(tmp_path, output, "--force")

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schemaVersion"] == "v0.1"


def test_scan_writes_fresh_output_without_force(tmp_path: Path) -> None:
    _stub_filegdb()
    output = tmp_path / "nested" / "EsriFootprint.json"

    exit_code = _run_scan(tmp_path, output)

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schemaVersion"] == "v0.1"


# --- atomicity ------------------------------------------------------------


def test_atomic_write_preserves_prior_file_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "EsriFootprint.json"
    target.write_text("PRIOR VALID", encoding="utf-8")

    # Drive a mid-write failure: a lone surrogate is not encodable as UTF-8, so
    # the temp-file write raises before os.replace can run.
    bad = "\ud800"
    with pytest.raises(UnicodeEncodeError):
        atomic_write_text(target, bad)

    # The original file survives and no temp files are left behind.
    assert target.read_text(encoding="utf-8") == "PRIOR VALID"
    leftovers = [p for p in tmp_path.iterdir() if p.name != "EsriFootprint.json"]
    assert leftovers == []


def test_atomic_write_leaves_no_tempfiles_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_text(target, "hello\n")

    assert target.read_text(encoding="utf-8") == "hello\n"
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_ensure_overwrite_allowed_raises_only_when_unforced(tmp_path: Path) -> None:
    existing = tmp_path / "f.json"
    existing.write_text("x", encoding="utf-8")

    with pytest.raises(OutputExistsError):
        from honua_esri_assess.output_io import ensure_overwrite_allowed

        ensure_overwrite_allowed(existing, force=False)

    # force=True and missing paths are both allowed.
    from honua_esri_assess.output_io import ensure_overwrite_allowed

    ensure_overwrite_allowed(existing, force=True)
    ensure_overwrite_allowed(tmp_path / "missing.json", force=False)


# --- report overwrite refusal --------------------------------------------


def test_report_refuses_to_overwrite_without_force(tmp_path: Path, capsys) -> None:
    footprint = _sample_footprint()
    footprint["inventory"] = []
    footprint["counts"]["items"]["filegdb-feature-class"] = 0
    footprint["counts"]["featureClasses"] = 0
    footprint["filegdb"]["featureClassCount"] = 0
    input_path = tmp_path / "EsriFootprint.json"
    input_path.write_text(json.dumps(footprint), encoding="utf-8")
    output = tmp_path / "report.md"
    output.write_text("PRIOR REPORT", encoding="utf-8")

    exit_code = cli_main(
        [
            "report",
            "--input",
            str(input_path),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "report.input.exists" in captured.err
    assert output.read_text(encoding="utf-8") == "PRIOR REPORT"


def test_report_overwrites_with_force(tmp_path: Path) -> None:
    footprint = _sample_footprint()
    footprint["inventory"] = []
    footprint["counts"]["items"]["filegdb-feature-class"] = 0
    footprint["counts"]["featureClasses"] = 0
    footprint["filegdb"]["featureClassCount"] = 0
    input_path = tmp_path / "EsriFootprint.json"
    input_path.write_text(json.dumps(footprint), encoding="utf-8")
    output = tmp_path / "report.md"
    output.write_text("PRIOR REPORT", encoding="utf-8")

    exit_code = cli_main(
        [
            "report",
            "--input",
            str(input_path),
            "--output",
            str(output),
            "--force",
        ]
    )

    assert exit_code == 0
    assert output.read_text(encoding="utf-8") != "PRIOR REPORT"
