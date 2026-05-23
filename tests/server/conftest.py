"""Shared fixtures for ArcGIS Server scanner tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def base_url() -> str:
    return "https://gis.example.com/arcgis"


@pytest.fixture
def rest_root(base_url: str) -> str:
    return f"{base_url}/rest/services"


@pytest.fixture
def rest_info_url(base_url: str) -> str:
    return f"{base_url}/rest/info"
