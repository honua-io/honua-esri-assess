"""Smoke test for the Markdown report renderer (E8 surface)."""

from __future__ import annotations

import json
from pathlib import Path

from honua_esri_assess.cli import main as cli_main


def _required_headings() -> list[str]:
    path = Path(__file__).parent / "expected" / "report-required-headings.json"
    return json.loads(path.read_text(encoding="utf-8"))["headings"]


def test_report_renders_against_agol_happy_footprint(
    mocked_routes,
    tmp_output_dir: Path,
) -> None:
    footprint_path = tmp_output_dir / "EsriFootprint.json"
    with mocked_routes("agol/happy"):
        scan_exit = cli_main(
            [
                "scan",
                "agol",
                "--target",
                "https://fixture.local/sharing/rest",
                "--output",
                str(footprint_path),
            ]
        )
    assert scan_exit == 0

    report_path = tmp_output_dir / "report.md"
    report_exit = cli_main(
        [
            "report",
            "--input",
            str(footprint_path),
            "--output",
            str(report_path),
        ]
    )
    assert report_exit == 0
    assert report_path.exists()

    markdown = report_path.read_text(encoding="utf-8")
    for heading in _required_headings():
        assert heading in markdown, f"required heading missing: {heading!r}"

    footprint = json.loads(footprint_path.read_text(encoding="utf-8"))
    for kind, count in footprint["counts"]["items"].items():
        assert f"| {kind} | {count} |" in markdown, (
            f"counts row mismatch for kind={kind}: expected {count}"
        )
    total = sum(footprint["counts"]["items"].values())
    assert f"Total inventory items: **{total}**" in markdown
