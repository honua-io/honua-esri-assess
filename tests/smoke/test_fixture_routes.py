"""Regression tests for smoke fixture route matching."""

from __future__ import annotations

from typing import Any

import pytest
import requests


def test_fixture_routes_reject_unexpected_query_params(mocked_routes: Any) -> None:
    url = "https://fixture.local/sharing/rest/portals/self"
    with mocked_routes("agol/happy", assert_all_requests_are_fired=False):
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get(url, params={"f": "json", "extra": "leak"}, timeout=10)

        response = requests.get(url, params={"f": "json"}, timeout=10)

    assert response.status_code == 200
