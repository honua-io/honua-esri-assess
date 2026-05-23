"""Regression coverage for credential-free handoff artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from honua_esri_assess.cli import main as cli_main
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.commands.scan_handlers import HANDLERS, ScanHandler, register
from honua_esri_assess.footprint import build_footprint
from honua_esri_assess.scanners import agol as agol_scanner
from honua_esri_assess.scanners import server as server_scanner

SECRET_TARGET = (
    "https://alice:superpass@fixture.local/sharing/rest;jsessionid=session-secret"
    "?token=topsecret-token&password=hidden-password#session"
)


@pytest.fixture(autouse=True)
def restore_handlers() -> Iterator[None]:
    original = dict(HANDLERS)
    try:
        yield
    finally:
        HANDLERS.clear()
        HANDLERS.update(original)


def _assert_no_secrets(value: Any, *extra: str) -> None:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    for secret in (
        "alice:superpass",
        "superpass",
        "topsecret-token",
        "hidden-password",
        "session-secret",
        "jsessionid",
        "token=",
        "password=",
        "#session",
        *extra,
    ):
        assert secret not in text


def test_footprint_builder_sanitizes_source_target_credentials() -> None:
    footprint = build_footprint(
        source_kind="arcgis-online",
        target=SECRET_TARGET,
        inventory=[],
        diagnostics=[],
        portal={
            "orgId": "fixture-org",
            "orgUrl": "https://fixture.local",
            "itemCounts": {},
        },
    )

    assert footprint["source"]["locator"] == "fixture.local/fixture-org"
    assert footprint["portal"]["orgUrl"] == "https://fixture.local"
    _assert_no_secrets(footprint)


@pytest.mark.parametrize("backend", ["agol", "server"])
def test_scan_cli_uses_raw_target_but_writes_sanitized_handoff(
    backend: str,
    tmp_path: Path,
) -> None:
    seen: dict[str, str] = {}

    def _fake_scan(options: ScanOptions) -> ScanResult:
        seen["target"] = options.target
        source_kind = "arcgis-online" if backend == "agol" else "arcgis-server"
        kwargs: dict[str, Any]
        if backend == "agol":
            kwargs = {
                "portal": {
                    "orgId": "fixture-org",
                    "orgUrl": "https://fixture.local",
                    "itemCounts": {},
                }
            }
        else:
            kwargs = {"server": {"serviceCounts": {}, "folders": []}}
        return ScanResult(
            footprint=build_footprint(
                source_kind=source_kind,
                target=options.target,
                inventory=[],
                diagnostics=[],
                **kwargs,
            )
        )

    register(ScanHandler(name=backend, run=_fake_scan))

    output = tmp_path / "EsriFootprint.json"
    exit_code = cli_main(
        ["scan", backend, "--target", SECRET_TARGET, "--output", str(output)]
    )

    assert exit_code == 0
    assert seen["target"] == SECRET_TARGET
    footprint = json.loads(output.read_text(encoding="utf-8"))
    if backend == "agol":
        assert footprint["source"]["locator"] == "fixture.local/fixture-org"
    else:
        assert footprint["source"]["locator"] == "https://fixture.local/sharing/rest"
    _assert_no_secrets(footprint)


def test_report_over_scan_output_does_not_render_target_credentials(
    tmp_path: Path,
) -> None:
    def _fake_scan(options: ScanOptions) -> ScanResult:
        return ScanResult(
            footprint=build_footprint(
                source_kind="arcgis-online",
                target=options.target,
                inventory=[],
                diagnostics=[],
                portal={
                    "orgId": "fixture-org",
                    "orgUrl": "https://fixture.local",
                    "itemCounts": {},
                },
            )
        )

    register(ScanHandler(name="agol", run=_fake_scan))
    footprint_path = tmp_path / "EsriFootprint.json"
    scan_exit = cli_main(
        ["scan", "agol", "--target", SECRET_TARGET, "--output", str(footprint_path)]
    )
    assert scan_exit == 0

    report_path = tmp_path / "report.md"
    report_exit = cli_main(
        ["report", "--input", str(footprint_path), "--output", str(report_path)]
    )

    assert report_exit == 0
    markdown = report_path.read_text(encoding="utf-8")
    assert "fixture.local/fixture-org" in markdown
    _assert_no_secrets(markdown)


class _JsonResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class _AgolSession:
    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> _JsonResponse:
        path = urlsplit(url).path
        if path.endswith("/portals/self/users"):
            return _JsonResponse({"users": []})
        if path.endswith("/portals/self"):
            return _JsonResponse({"name": "Demo"})
        if path.endswith("/community/groups"):
            return _JsonResponse({"groups": []})
        if path.endswith("/search"):
            return _JsonResponse(
                {
                    "results": [
                        {
                            "id": "item-feature-1",
                            "title": "Parcels",
                            "type": "Feature Service",
                            "url": (
                                "https://search:secret@services.fixture.local/Parcels/FeatureServer"
                                "?token=search-token"
                            ),
                        }
                    ],
                    "nextStart": -1,
                }
            )
        if path.endswith("/content/items/item-feature-1"):
            return _JsonResponse(
                {
                    "id": "item-feature-1",
                    "title": "Parcels",
                    "url": (
                        "https://probe:secret@services.fixture.local/Parcels/FeatureServer"
                        "?token=probe-token&password=probe-password#session"
                    ),
                    "layers": [{"id": 0}],
                }
            )
        raise AssertionError(f"unexpected AGOL request: {url}")


def test_agol_scanner_sanitizes_item_urls_copied_from_esri_payloads() -> None:
    result = agol_scanner.scan(
        "https://fixture.local/sharing/rest",
        session=_AgolSession(),
    )

    assert "url" not in result["inventory"][0]
    _assert_no_secrets(
        result,
        "search-token",
        "probe-token",
        "probe-password",
        "probe:secret",
    )


class _ServerSession:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> _JsonResponse:
        self.urls.append(url)
        path = urlsplit(url).path
        if path.endswith("/services"):
            return _JsonResponse({"services": [{"name": "Parcels", "type": "FeatureServer"}]})
        if path.endswith("/services/Parcels/FeatureServer"):
            return _JsonResponse({"serviceDescription": "Parcels", "layers": [{"id": 0}]})
        raise AssertionError(f"unexpected Server request: {url}")


def test_server_scanner_sanitizes_inventory_urls_derived_from_raw_target() -> None:
    session = _ServerSession()
    result = server_scanner.scan(
        "https://alice:superpass@fixture.local/server/rest",
        session=session,
    )

    assert any("alice:superpass@" in url for url in session.urls)
    assert result["inventory"][0]["serviceUrl"] == (
        "https://fixture.local/server/rest/services/Parcels/FeatureServer"
    )
    _assert_no_secrets(result)
