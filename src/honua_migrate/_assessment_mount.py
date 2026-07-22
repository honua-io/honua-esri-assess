"""Mount the assessment implementation without presenting it as legacy use."""

from __future__ import annotations

import sys

_MARKER = "_honua_migrate_mounting_assessment"
_missing = object()
_previous = getattr(sys, _MARKER, _missing)
setattr(sys, _MARKER, True)
try:
    # Reuse the application object so every command, exit code, serializer, and
    # redaction path is identical across the successor and compatibility CLIs.
    from honua_esri_assess.app import cli_app as assess_app
finally:
    if _previous is _missing:
        delattr(sys, _MARKER)
    else:
        setattr(sys, _MARKER, _previous)

__all__ = ["assess_app"]
