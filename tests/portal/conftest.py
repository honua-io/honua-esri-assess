from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert isinstance(payload, dict)
    return payload


def register_happy_path(responses_module: Any, *, include_users: bool = True, include_service: bool = False) -> None:
    base = "https://demo.maps.arcgis.com/sharing/rest"
    responses_module.add(
        responses_module.GET,
        f"{base}/portals/self",
        json=load_fixture("portal_self.json"),
        status=200,
    )
    responses_module.add(
        responses_module.GET,
        f"{base}/community/groups",
        json=load_fixture("groups_page_1.json"),
        status=200,
    )
    if include_users:
        responses_module.add(
            responses_module.GET,
            f"{base}/community/users",
            json=load_fixture("users_count.json"),
            status=200,
        )
    responses_module.add(
        responses_module.GET,
        f"{base}/search",
        json=load_fixture("search_page_1.json"),
        status=200,
    )
    responses_module.add(
        responses_module.GET,
        f"{base}/search",
        json=load_fixture("search_page_2.json"),
        status=200,
    )
    if include_service:
        responses_module.add(
            responses_module.GET,
            "https://services.arcgis.com/demo/arcgis/rest/services/Parcels/FeatureServer",
            json=load_fixture("service_feature_server.json"),
            status=200,
        )


@pytest.fixture
def fixture_json() -> Any:
    return load_fixture


@pytest.fixture
def happy_path_responses() -> Any:
    return register_happy_path
