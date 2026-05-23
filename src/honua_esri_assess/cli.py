"""Command-line entry point for honua-esri-assess."""

from __future__ import annotations

import click

from .app import cli_app


def main(argv: list[str] | None = None) -> int:
    """Run the Typer application and return a process-style exit code."""

    try:
        result = cli_app(
            args=argv,
            prog_name="honua-esri-assess",
            standalone_mode=False,
        )
    except click.exceptions.Exit as exc:
        return int(exc.exit_code or 0)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    if isinstance(result, int):
        return result
    return 0


__all__ = ["main"]
