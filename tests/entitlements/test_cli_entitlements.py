"""Smoke tests for the interim ``entitlements`` CLI subcommand."""

from __future__ import annotations

import json
from typing import Mapping

import pytest

from honua_esri_assess import cli
from honua_esri_assess.entitlements.http import HttpResponse

from .conftest import StubHttpClient, load_fixture


def _portal_stub() -> StubHttpClient:
    return StubHttpClient(
        handlers={
            "portals/self/subscriptionInfo": _const_response(
                200, load_fixture("portal_subscription_info.json")
            ),
            "portals/self/userLicenseTypes": _const_response(
                200, load_fixture("portal_user_license_types.json")
            ),
            "portals/self": _const_response(200, load_fixture("portal_self.json")),
            "/users": _const_response(200, load_fixture("portal_users.json")),
        }
    )


def _server_stub() -> StubHttpClient:
    return StubHttpClient(
        handlers={
            "rest/info": _const_response(200, load_fixture("server_rest_info.json")),
            "admin/info": _const_response(200, load_fixture("server_admin_info.json")),
            "admin/system/licenses": _const_response(
                200, load_fixture("server_admin_licenses.json")
            ),
        }
    )


def _const_response(status: int, body: object):
    def handler(url: str, params: Mapping[str, str]) -> HttpResponse:
        return HttpResponse(status_code=status, body=body)

    return handler


def test_cli_entitlements_agol_emits_licensing_facet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = _portal_stub()
    monkeypatch.setattr(cli, "RequestsHttpClient", lambda **kw: stub)

    rc = cli.main(
        [
            "entitlements",
            "agol",
            "--target",
            "https://www.arcgis.com",
            "--token",
            "TOKEN",
        ]
    )
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    assert out["target"] == "agol"
    portal = out["licensing"]["portal"]["licensing"]
    assert portal["tier"] == "online"
    assert any(ut["name"] == "creatorUT" for ut in portal["userTypes"])
    assert isinstance(out["diagnostics"], list)


def test_cli_entitlements_server_emits_licensing_facet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = _server_stub()
    monkeypatch.setattr(cli, "RequestsHttpClient", lambda **kw: stub)

    rc = cli.main(
        [
            "entitlements",
            "server",
            "--target",
            "https://example.com/arcgis",
            "--token",
            "TOKEN",
            "--no-service-extensions",
        ]
    )
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    server = out["licensing"]["server"]["licensing"]
    assert server["currentVersion"] == "11.3"
    assert server["edition"] == "Advanced"
    codes = {ext["code"] for ext in server["extensions"]}
    assert {"Spatial", "Network"} <= codes


def test_cli_entitlements_typed_error_returns_exit_code_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = StubHttpClient(
        handlers={},
        raise_on={"rest/info": ConnectionError("DNS lookup failed")},
    )
    monkeypatch.setattr(cli, "RequestsHttpClient", lambda **kw: stub)

    rc = cli.main(
        ["entitlements", "server", "--target", "https://example.com/arcgis"]
    )
    assert rc == 3
    err = capsys.readouterr().err
    assert "could not reach host" in err
    assert "Traceback" not in err  # prospect-safe: no stack traces


def test_cli_entitlements_no_subcommand_prints_help_and_returns_usage_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.main(["entitlements"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "honua-esri-assess" in captured.out


def test_cli_entitlements_invalid_service_returns_usage_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.main(
        [
            "entitlements",
            "server",
            "--target",
            "https://example.com/arcgis",
            "--service",
            "noDotHere",
        ]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "--service expects" in captured.err
    assert "unexpected failure" not in captured.err


def test_cli_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--version"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_cli_parse_service_ref_root_folder() -> None:
    ref = cli._parse_service_ref("World.MapServer")
    assert ref.folder == ""
    assert ref.name == "World"
    assert ref.type == "MapServer"


def test_cli_parse_service_ref_with_folder() -> None:
    ref = cli._parse_service_ref("Hosted/Parcels.MapServer")
    assert ref.folder == "Hosted"
    assert ref.name == "Parcels"
    assert ref.type == "MapServer"


def test_cli_parse_service_ref_rejects_bad_input() -> None:
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        cli._parse_service_ref("noDotHere")
