"""Retry behavior of the access-tier RequestsHttpClient."""

from __future__ import annotations

import io
import urllib.error
from typing import Any

import pytest

from honua_esri_assess.entitlements.http import RequestsHttpClient


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self._status = status
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def getcode(self) -> int:
        return self._status

    def read(self) -> bytes:
        return self._body


def _install_responses(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[Any],
) -> list[Any]:
    """Patch urllib.request.urlopen to pop one entry per call."""

    queue = list(responses)
    seen: list[Any] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> Any:
        seen.append(request)
        next_response = queue.pop(0)
        if isinstance(next_response, BaseException):
            raise next_response
        return next_response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return seen


def test_retries_transient_429_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    client = RequestsHttpClient(
        token=None,
        max_attempts=3,
        initial_backoff=0.0,
        backoff_factor=1.0,
        max_backoff_seconds=0.0,
        sleep=sleeps.append,
    )
    seen = _install_responses(
        monkeypatch,
        [
            _FakeResponse(429, b""),
            _FakeResponse(429, b""),
            _FakeResponse(200, b'{"ok": true}'),
        ],
    )
    resp = client.get_json("https://gis.fixture.local/arcgis/admin/security/config")
    assert resp.status_code == 200
    assert resp.body == {"ok": True}
    # Three calls means the retry actually happened.
    assert len(seen) == 3
    # Two backoffs precede the third attempt.
    assert sleeps == [0.0, 0.0]


def test_retries_transient_5xx_then_returns_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RequestsHttpClient(
        max_attempts=2,
        initial_backoff=0.0,
        backoff_factor=1.0,
        max_backoff_seconds=0.0,
        sleep=lambda _seconds: None,
    )
    _install_responses(
        monkeypatch,
        [_FakeResponse(503, b""), _FakeResponse(503, b"")],
    )
    resp = client.get_json("https://gis.fixture.local/arcgis/admin/security/config")
    # After exhausting attempts, return the terminal response so the
    # caller can route it through their own typed-error mapping.
    assert resp.status_code == 503


def test_no_retry_when_max_attempts_is_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    client = RequestsHttpClient(max_attempts=1, sleep=sleeps.append)
    seen = _install_responses(monkeypatch, [_FakeResponse(429, b"")])
    resp = client.get_json("https://gis.fixture.local/arcgis/admin/security/config")
    assert resp.status_code == 429
    assert len(seen) == 1
    assert sleeps == []


def test_retries_url_error_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RequestsHttpClient(
        max_attempts=3,
        initial_backoff=0.0,
        backoff_factor=1.0,
        max_backoff_seconds=0.0,
        sleep=lambda _seconds: None,
    )
    _install_responses(
        monkeypatch,
        [
            urllib.error.URLError("temporary dns failure"),
            urllib.error.URLError("connection reset"),
            _FakeResponse(200, b'{"ok": true}'),
        ],
    )
    resp = client.get_json("https://gis.fixture.local/arcgis/admin/security/config")
    assert resp.status_code == 200


def test_url_error_after_exhausted_attempts_raises_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RequestsHttpClient(
        max_attempts=2,
        initial_backoff=0.0,
        backoff_factor=1.0,
        max_backoff_seconds=0.0,
        sleep=lambda _seconds: None,
    )
    _install_responses(
        monkeypatch,
        [
            urllib.error.URLError("temporary dns failure"),
            urllib.error.URLError("still failing"),
        ],
    )
    with pytest.raises(ConnectionError):
        client.get_json("https://gis.fixture.local/arcgis/admin/security/config")


def test_non_retryable_status_returns_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    client = RequestsHttpClient(max_attempts=3, sleep=sleeps.append)
    seen = _install_responses(
        monkeypatch,
        [
            # A 200 with a JSON error envelope is still a single network call;
            # the wrapper does not interpret envelopes — that is the
            # collector's job.
            _FakeResponse(200, b'{"error": {"code": 401, "message": "denied"}}'),
        ],
    )
    resp = client.get_json("https://gis.fixture.local/arcgis/admin/security/config")
    assert resp.status_code == 200
    assert resp.body == {"error": {"code": 401, "message": "denied"}}
    assert len(seen) == 1
    assert sleeps == []


def test_http_error_404_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    client = RequestsHttpClient(max_attempts=3, sleep=sleeps.append)
    error = urllib.error.HTTPError(
        url="https://gis.fixture.local/arcgis/admin/security/config",
        code=404,
        msg="Not Found",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    seen = _install_responses(monkeypatch, [error])
    resp = client.get_json("https://gis.fixture.local/arcgis/admin/security/config")
    assert resp.status_code == 404
    assert len(seen) == 1
    assert sleeps == []
