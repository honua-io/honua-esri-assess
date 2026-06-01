"""Fixture-driven HTTP stub for the RBAC / access-footprint scanner tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from honua_esri_assess.entitlements.http import HttpResponse

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


@dataclass
class StubHttpClient:
    """Path-suffix routed, deterministic ``HttpClient`` stub.

    Records every URL it is asked for so tests can assert that the scanner
    issued GET-only requests and that no credential leaked into the calls it
    actually emitted into the artifact.
    """

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
        matches = sorted(
            (key for key in self.handlers if key in url), key=len, reverse=True
        )
        if not matches:
            raise AssertionError(f"no stub handler matched URL {url!r}")
        return self.handlers[matches[0]](url, params or {})


def respond(status: int, body: Any) -> Callable[[str, Mapping[str, str]], HttpResponse]:
    def handler(url: str, params: Mapping[str, str]) -> HttpResponse:
        return HttpResponse(status_code=status, body=body)

    return handler


def respond_fixture(name: str) -> Callable[[str, Mapping[str, str]], HttpResponse]:
    return respond(200, load_fixture(name))
