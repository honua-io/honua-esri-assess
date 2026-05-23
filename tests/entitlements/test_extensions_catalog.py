"""Verify the static extension catalog."""

from __future__ import annotations

from honua_esri_assess.entitlements.extensions import (
    extension_catalog,
    resolve_extension,
)


def test_catalog_entries_have_code_and_name() -> None:
    for key, entry in extension_catalog().items():
        assert entry.code, key
        assert entry.name, key
        assert key == entry.code.lower()


def test_resolve_extension_returns_known_entry_case_insensitively() -> None:
    resolved = resolve_extension("SPATIAL")
    assert resolved.known is True
    assert resolved.code == "Spatial"
    assert resolved.name == "ArcGIS Spatial Analyst"


def test_resolve_extension_round_trips_unknown_code_verbatim() -> None:
    resolved = resolve_extension("ContosoCustomExt")
    assert resolved.known is False
    assert resolved.code == "ContosoCustomExt"
    assert resolved.name == "ContosoCustomExt"


def test_resolve_extension_handles_empty_code() -> None:
    resolved = resolve_extension("")
    assert resolved.known is False
    assert resolved.name == "unknown"
