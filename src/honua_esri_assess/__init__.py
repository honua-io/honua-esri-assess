"""Honua Esri assessment tooling."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

from ._deprecation import warn_legacy_surface

__all__ = ["SCHEMA_VERSION", "__version__", "bundled_schema_version"]

SCHEMA_VERSION = "v0.2"

# The unified CLI sets this marker only while mounting the exact same Typer app.
# Direct use of the legacy package still receives a visible stderr warning.
if not getattr(sys, "_honua_migrate_mounting_assessment", False):
    warn_legacy_surface(stacklevel=2)

try:
    __version__ = version("honua-migrate")
except PackageNotFoundError:
    __version__ = "0.7.1"


def bundled_schema_version() -> str:
    """Return the in-band EsriFootprint schema version bundled with the tool."""

    return SCHEMA_VERSION
