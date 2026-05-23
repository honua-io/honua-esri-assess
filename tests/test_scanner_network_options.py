"""Network option propagation for read-only Esri scanners."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import requests

from honua_esri_assess.scanners import agol as agol_scanner
from honua_esri_assess.scanners import server as server_scanner


class _JsonResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class _RecordingAgolSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> _JsonResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        path = urlsplit(url).path
        if path.endswith("/portals/self"):
            return _JsonResponse({"id": "fixture-org", "urlKey": "fixture"})
        if path.endswith("/portals/self/users"):
            return _JsonResponse({"users": []})
        if path.endswith("/community/groups"):
            return _JsonResponse({"groups": []})
        if path.endswith("/search"):
            return _JsonResponse({"results": [], "nextStart": -1})
        raise AssertionError(f"unexpected AGOL request: {url}")


class _RecordingServerSession:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []
        self._fail_first = fail_first

    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> _JsonResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self._fail_first and len(self.calls) == 1:
            raise requests.ConnectionError("transient")
        path = urlsplit(url).path
        if path.endswith("/services"):
            return _JsonResponse({"services": [], "folders": []})
        raise AssertionError(f"unexpected Server request: {url}")


def test_agol_scanner_applies_token_user_agent_and_timeout_without_handoff_leak() -> None:
    session = _RecordingAgolSession()

    result = agol_scanner.scan(
        "https://fixture.local/sharing/rest",
        session=session,
        token="top-secret-token",
        user_agent="honua-test/1.0",
        max_retries=0,
        timeout=7.5,
    )

    assert session.headers["User-Agent"] == "honua-test/1.0"
    assert session.calls
    assert all(call["params"]["token"] == "top-secret-token" for call in session.calls)
    assert all(call["timeout"] == 7.5 for call in session.calls)
    assert "top-secret-token" not in str(result)


def test_server_scanner_applies_token_user_agent_and_timeout_without_handoff_leak() -> None:
    session = _RecordingServerSession()

    result = server_scanner.scan(
        "https://fixture.local/server/rest",
        session=session,
        token="top-secret-token",
        user_agent="honua-test/1.0",
        max_retries=0,
        timeout=7.5,
    )

    assert session.headers["User-Agent"] == "honua-test/1.0"
    assert session.calls
    assert all(call["params"]["token"] == "top-secret-token" for call in session.calls)
    assert all(call["timeout"] == 7.5 for call in session.calls)
    assert "top-secret-token" not in str(result)


def test_server_scanner_retries_transient_read_failures() -> None:
    session = _RecordingServerSession(fail_first=True)

    result = server_scanner.scan(
        "https://fixture.local/server/rest",
        session=session,
        max_retries=1,
        timeout=7.5,
    )

    assert len(session.calls) == 2
    assert result["diagnostics"] == []


def test_server_scanner_reports_terminal_read_failure_after_retry_budget() -> None:
    session = _RecordingServerSession(fail_first=True)

    result = server_scanner.scan(
        "https://fixture.local/server/rest",
        session=session,
        max_retries=0,
        timeout=7.5,
    )

    assert len(session.calls) == 1
    assert result["diagnostics"][0].code == "partial-coverage"
