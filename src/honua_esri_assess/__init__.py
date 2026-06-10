"""Honua Esri assessment tooling."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["SCHEMA_VERSION", "__version__", "bundled_schema_version"]

SCHEMA_VERSION = "v0.2"

try:
    __version__ = version("honua-esri-assess")
except PackageNotFoundError:
    __version__ = "0.7.1"


def bundled_schema_version() -> str:
    """Return the in-band EsriFootprint schema version bundled with the tool."""

    return SCHEMA_VERSION
