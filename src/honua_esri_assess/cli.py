"""Command-line entry point for honua-esri-assess."""

from __future__ import annotations

from typing import cast

import click

from honua_migrate._click_compat import CLICK_EXCEPTIONS as _CLICK_EXCEPTIONS
from honua_migrate._click_compat import EXIT_EXCEPTIONS as _EXIT_EXCEPTIONS

from .app import cli_app
from ._deprecation import warn_legacy_surface


def main(argv: list[str] | None = None) -> int:
    """Run the Typer application and return a process-style exit code."""

    warn_legacy_surface(stacklevel=2)
    try:
        result = cli_app(
            args=argv,
            prog_name="honua-esri-assess",
            standalone_mode=False,
        )
    except _EXIT_EXCEPTIONS as exc:
        return int(getattr(exc, "exit_code", 0) or 0)
    except _CLICK_EXCEPTIONS as exc:
        # Both the standalone-Click and Typer-vendored exceptions expose the
        # same ``show()`` / ``exit_code`` surface; treat them uniformly.
        click_exc = cast(click.ClickException, exc)
        click_exc.show()
        return click_exc.exit_code
    if isinstance(result, int):
        return result
    return 0


__all__ = ["main"]
