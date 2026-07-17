"""CLI tests for the ``caps`` command (issue #84)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import responses

from honua_esri_assess import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "docs" / "samples" / "esri-footprint.sample.json"
UTILITY_NETWORK = REPO_ROOT / "tests" / "fixtures" / "esri-footprint-utility-network.json"


def test_caps_writes_json_and_markdown(tmp_path: Path, capsys) -> None:
    json_path = tmp_path / "honua-caps.json"
    md_path = tmp_path / "summary.md"

    exit_code = cli.main(
        [
            "caps",
            "--input",
            str(SAMPLE),
            "--json",
            str(json_path),
            "--output",
            str(md_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "honua-caps.v1"
    assert {entry["key"] for entry in payload["capabilities"]} == {
        "serve.geoservices-featureserver",
        "identity.portal-sharing",
        "fieldops.forms",
    }
    assert payload["unmapped"] == []  # every detected key in the sample now maps

    markdown = md_path.read_text(encoding="utf-8")
    assert markdown.startswith("# Honua Capability Crosswalk")

    captured = capsys.readouterr()
    assert captured.out.strip() == payload["url"]
    assert captured.err == ""


def test_caps_default_json_output_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(
        ["caps", "--input", str(SAMPLE), "--output", str(tmp_path / "summary.md")]
    )

    assert exit_code == 0
    default_json = tmp_path / "honua-caps.json"
    assert default_json.exists()
    payload = json.loads(default_json.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "honua-caps.v1"


def test_caps_reads_stdin_and_writes_json_to_stdout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(SAMPLE.read_text(encoding="utf-8"))
    )

    exit_code = cli.main(
        ["caps", "--input", "-", "--json", "-", "--output", "-"]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert '"schemaVersion": "honua-caps.v1"' in captured.out
    assert "# Honua Capability Crosswalk" in captured.out
    assert "https://honua.io/capabilities.html" in captured.out
    assert captured.err == ""


def test_caps_utility_network_reports_not_supported(capsys) -> None:
    exit_code = cli.main(
        ["caps", "--input", str(UTILITY_NETWORK), "--json", "-", "--output", "-"]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert '"assessKey": "utility-network"' in captured.out
    assert '"reason": "not-supported"' in captured.out
    assert "units=1" in captured.out


def test_caps_missing_input_file_is_prospect_safe(capsys) -> None:
    exit_code = cli.main(["caps", "--input", "does-not-exist.json"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.input.read]")
    assert "Traceback" not in captured.err


def test_caps_malformed_json_is_prospect_safe(tmp_path: Path, capsys) -> None:
    bad_json = tmp_path / "bad.json"
    bad_json.write_text('{"schemaVersion": ', encoding="utf-8")

    exit_code = cli.main(["caps", "--input", str(bad_json)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.input.parse]")


def test_caps_strict_schema_failure_is_typed(tmp_path: Path, capsys) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schemaVersion": "v0.1"}), encoding="utf-8")

    exit_code = cli.main(["caps", "--input", str(invalid), "--strict"])

    assert exit_code == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.schema.invalid]")


def test_caps_unknown_assess_key_in_crosswalk_fails_loudly(
    tmp_path: Path, capsys
) -> None:
    bad_crosswalk = tmp_path / "bad-crosswalk.json"
    bad_crosswalk.write_text(
        json.dumps(
            {
                "schemaVersion": "capability-keys.v1",
                "source": "test",
                "crosswalks": {
                    "esriAssessRegistry": {"not-a-real-registry-key": []}
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "caps",
            "--input",
            str(SAMPLE),
            "--crosswalk",
            str(bad_crosswalk),
            "--json",
            "-",
            "--output",
            "-",
        ]
    )

    assert exit_code == 5
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: [report.crosswalk.invalid]")
    assert "not-a-real-registry-key" in captured.err


def test_caps_missing_crosswalk_file_is_prospect_safe(capsys) -> None:
    exit_code = cli.main(
        ["caps", "--input", str(SAMPLE), "--crosswalk", "does-not-exist.json"]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("error: [report.input.read]")


def test_caps_never_fetches_network_by_default(monkeypatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError("caps must not make a network call by default")

    monkeypatch.setattr("requests.get", _fail)

    exit_code = cli.main(
        ["caps", "--input", str(SAMPLE), "--json", "-", "--output", "-"]
    )

    assert exit_code == 0


@responses.activate
def test_caps_crosswalk_url_override_is_explicit_opt_in(capsys) -> None:
    custom_crosswalk = {
        "schemaVersion": "capability-keys.v1",
        "source": "test-remote-crosswalk",
        "crosswalks": {"esriAssessRegistry": {"feature-service": ["serve.geoservices-featureserver"]}},
    }
    responses.add(
        responses.GET,
        "https://example.test/capability-keys.v1.json",
        json=custom_crosswalk,
        status=200,
    )

    exit_code = cli.main(
        [
            "caps",
            "--input",
            str(SAMPLE),
            "--crosswalk",
            "https://example.test/capability-keys.v1.json",
            "--json",
            "-",
            "--output",
            "-",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert '"source": "test-remote-crosswalk"' in captured.out


@responses.activate
def test_caps_crosswalk_url_fetch_failure_is_prospect_safe(capsys) -> None:
    responses.add(
        responses.GET,
        "https://example.test/down.json",
        status=503,
    )

    exit_code = cli.main(
        [
            "caps",
            "--input",
            str(SAMPLE),
            "--crosswalk",
            "https://example.test/down.json",
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("error: [report.input.read]")
    assert "Traceback" not in captured.err
