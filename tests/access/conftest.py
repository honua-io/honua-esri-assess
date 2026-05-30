"""Shared test helpers for the access-export fixture-driven tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

from honua_esri_assess.entitlements.http import HttpResponse


_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a JSON fixture by filename (without directory prefix)."""

    path = _FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class StubHttpClient:
    """Deterministic HTTP client driven by a path-suffix → handler map."""

    handlers: dict[str, Callable[[str, Mapping[str, str]], HttpResponse]] = field(
        default_factory=dict
    )
    seen: list[str] = field(default_factory=list)
    raise_on: dict[str, Exception] = field(default_factory=dict)

    def get_json(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        *,
        timeout: float | None = None,
    ) -> HttpResponse:
        self.seen.append(url)
        for key, exc in self.raise_on.items():
            if key in url:
                raise exc
        handler = _match_handler(self.handlers, url)
        if handler is None:
            raise AssertionError(f"no stub handler matched URL {url!r}")
        return handler(url, params or {})


def _match_handler(
    handlers: dict[str, Callable[[str, Mapping[str, str]], HttpResponse]], url: str
) -> Callable[[str, Mapping[str, str]], HttpResponse] | None:
    matches = sorted(
        (key for key in handlers if key in url),
        key=len,
        reverse=True,
    )
    if not matches:
        return None
    return handlers[matches[0]]


def respond(status: int, body: Any) -> Callable[[str, Mapping[str, str]], HttpResponse]:
    def handler(url: str, params: Mapping[str, str]) -> HttpResponse:
        return HttpResponse(status_code=status, body=body)

    return handler


@pytest.fixture
def stub_client() -> StubHttpClient:
    return StubHttpClient()
