"""Shared fixtures for the fixture-backed CI smoke tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import responses
from jsonschema import Draft202012Validator
from responses import matchers

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXPECTED_DIR = Path(__file__).parent / "expected"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "esri-footprint-v0.2.json"


@pytest.fixture
def schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    return out


@pytest.fixture
def expected_counts() -> dict[str, dict[str, Any]]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(EXPECTED_DIR.glob("*.json"))
    }


def _build_mock(
    corpus: str, *, assert_all_requests_are_fired: bool = True
) -> responses.RequestsMock:
    """Return a configured (but not yet active) RequestsMock for the corpus."""
    corpus_dir = FIXTURES_DIR / corpus
    routes_doc = json.loads((corpus_dir / "_routes.json").read_text(encoding="utf-8"))
    rsps = responses.RequestsMock(
        assert_all_requests_are_fired=assert_all_requests_are_fired
    )
    for entry in routes_doc.get("routes", []):
        body = (corpus_dir / entry["body_file"]).read_text(encoding="utf-8")
        params = entry.get("params") or {}
        rsps.add(
            method=entry.get("method", "GET"),
            url=entry["url"],
            body=body,
            status=entry.get("status", 200),
            content_type="application/json",
            match=[
                matchers.query_param_matcher(
                    params,
                    strict_match=bool(entry.get("match_querystring", False)),
                )
            ],
        )
    return rsps


@pytest.fixture
def mocked_routes() -> Any:
    """Return a callable that builds a `responses.RequestsMock` for a corpus.

    Smoke tests use it as a context manager so that ``assert_all_requests_are_fired``
    fires at teardown — any URL drift or live-network leak fails the test loudly.

        with mocked_routes("agol/happy") as rsps:
            ...
    """

    def _factory(
        corpus: str, *, assert_all_requests_are_fired: bool = True
    ) -> responses.RequestsMock:
        return _build_mock(
            corpus, assert_all_requests_are_fired=assert_all_requests_are_fired
        )

    return _factory
