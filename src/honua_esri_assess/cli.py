"""Command-line entry point for honua-esri-assess."""

from __future__ import annotations

from typing import cast

import click

try:  # pragma: no cover - import-time wiring
    # Typer >=0.13 vendors its own copy of Click under ``typer._click``.
    # Exceptions raised by the Typer app are instances of those vendored
    # classes, which are *not* subclasses of the standalone ``click`` package's
    # exceptions, so we must catch both hierarchies here.
    from typer import _click as _typer_click  # type: ignore[attr-defined]

    _EXIT_EXCEPTIONS: tuple[type[BaseException], ...] = (
        click.exceptions.Exit,
        _typer_click.exceptions.Exit,
    )
    _CLICK_EXCEPTIONS: tuple[type[BaseException], ...] = (
        click.ClickException,
        _typer_click.exceptions.ClickException,
    )
except Exception:  # pragma: no cover - older Typer shares the standalone Click
    _EXIT_EXCEPTIONS = (click.exceptions.Exit,)
    _CLICK_EXCEPTIONS = (click.ClickException,)

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
