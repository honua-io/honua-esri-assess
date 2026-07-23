"""Deprecation signal for the legacy assessment command and import surface."""

from __future__ import annotations

import sys

DEPRECATION_MESSAGE = (
    "honua_esri_assess and honua-esri-assess are compatibility surfaces; "
    "use honua-migrate assess for commands and honua_migrate for new Python "
    "integrations. Removal requires two consecutive honua-migrate minor "
    "releases and at least 90 days after replacement availability, and is no "
    "earlier than honua-migrate 1.2."
)

_WARNED_MARKER = "_honua_esri_assess_deprecation_warned"


def warn_legacy_surface(*, stacklevel: int = 2) -> None:
    """Write the transition notice at most once in this Python process.

    This deliberately does not use :mod:`warnings`: supported compatibility
    imports must continue to work when an application enables ``-W error``.
    ``stacklevel`` remains accepted for compatibility with warning-style call
    sites but does not affect the stable, single-line stderr notice.
    """

    del stacklevel
    if getattr(sys, _WARNED_MARKER, False):
        return
    setattr(sys, _WARNED_MARKER, True)
    sys.stderr.write(f"DeprecationWarning: {DEPRECATION_MESSAGE}\n")


__all__ = ["DEPRECATION_MESSAGE", "warn_legacy_surface"]
