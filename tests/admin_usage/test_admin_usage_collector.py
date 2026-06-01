"""Fixture-backed coverage for the Admin-API usage / data-store collector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from honua_esri_assess.entitlements.diagnostics import (
    EntitlementsRateLimitedError,
)
from honua_esri_assess.entitlements.http import HttpResponse
from honua_esri_assess.scanners.admin_usage import (
    AdminUsageCollector,
    AdminUsageResult,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_BASE = "https://gis.fixture.local/arcgis/"


def _load(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class StubClient:
    """Routes admin paths to canned :class:`HttpResponse` objects."""

    def __init__(self, routes: dict[str, HttpResponse]) -> None:
        self._routes = routes
        self.urls: list[str] = []

    def get_json(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        *,
        timeout: float | None = None,
    ) -> HttpResponse:
        self.urls.append(url)
        for suffix, response in self._routes.items():
            if url.endswith(suffix):
                return response
        raise AssertionError(f"unexpected admin request: {url}")


def _ok(name: str) -> HttpResponse:
    return HttpResponse(status_code=200, body=_load(name))


def _collect_from_fixtures() -> tuple[AdminUsageResult, StubClient]:
    client = StubClient(
        {
            "admin/usagereports": _ok("admin-usagereports.json"),
            "admin/data/items": _ok("admin-data-items.json"),
        }
    )
    result = AdminUsageCollector(_BASE, client).collect()
    return result, client


def test_only_get_is_issued_against_admin_endpoints() -> None:
    result, client = _collect_from_fixtures()
    assert result.diagnostics == ()
    # The stub exposes no write verb; the collector only calls get_json.
    assert all(url.startswith(_BASE) for url in client.urls)
    assert any(u.endswith("admin/usagereports") for u in client.urls)
    assert any(u.endswith("admin/data/items") for u in client.urls)


def test_usage_totals_are_summed_per_service() -> None:
    result, _ = _collect_from_fixtures()
    assert result.service_usage == {
        "Parcels.MapServer": 60,
        "Planning/Zoning.FeatureServer": 2,
        "Hydro/Streams.MapServer": 15,
    }


def test_registrations_classify_storage_type_from_declared_type_only() -> None:
    result, _ = _collect_from_fixtures()
    by_id = {reg.item_id: reg for reg in result.registrations}
    assert by_id["/enterpriseDatabases/parcels_egdb"].connection_kind == (
        "enterprise-geodatabase"
    )
    assert by_id["/cloudStores/imagery_s3"].connection_kind == "cloud-store"
    assert by_id["/fileShares/legacy_gdb"].connection_kind == "file-share"
    assert by_id["/bigDataFileShares/sensor_bds"].connection_kind == (
        "big-data-file-share"
    )
    # Unknown declared types fall back to unknown (never parsed from internals).
    assert by_id["/enterpriseDatabases/mystery_store"].connection_kind == "unknown"


def test_no_credentials_leak_from_data_item_registrations() -> None:
    """Connection strings / secrets in data/items must never be retained."""

    result, _ = _collect_from_fixtures()
    serialized = json.dumps(
        [
            {
                "item_id": reg.item_id,
                "type": reg.type,
                "connection_kind": reg.connection_kind,
            }
            for reg in result.registrations
        ],
        sort_keys=True,
    )
    for secret in (
        "topsecret-db-pw",
        "PASSWORD=",
        "connectionString",
        "AKIAEXAMPLE",
        "super-secret-key",
        "secret-future-conn",
        "sql.internal",
        "fileserver",
    ):
        assert secret not in serialized


def test_missing_admin_scope_degrades_to_diagnostic() -> None:
    client = StubClient(
        {
            "admin/usagereports": HttpResponse(status_code=403, body=None),
            "admin/data/items": HttpResponse(
                status_code=200, body={"error": {"code": 499}}
            ),
        }
    )
    result = AdminUsageCollector(_BASE, client).collect()
    assert result.service_usage == {}
    assert result.registrations == []
    codes = {d.code for d in result.diagnostics}
    assert codes == {"missing-permission"}
    assert all(d.severity == "warn" for d in result.diagnostics)


def test_rate_limit_raises_typed_error() -> None:
    client = StubClient(
        {
            "admin/usagereports": HttpResponse(status_code=429, body=None),
            "admin/data/items": HttpResponse(status_code=200, body={"items": []}),
        }
    )
    with pytest.raises(EntitlementsRateLimitedError):
        AdminUsageCollector(_BASE, client).collect()
