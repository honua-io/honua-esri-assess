"""Process entry point for the unified migration CLI."""

from __future__ import annotations

from typing import cast

import click

from ._click_compat import CLICK_EXCEPTIONS as _CLICK_EXCEPTIONS
from ._click_compat import EXIT_EXCEPTIONS as _EXIT_EXCEPTIONS
from .app import cli_app
from .contracts import EXIT_INTERNAL_ERROR, MigrationError


def main(argv: list[str] | None = None) -> int:
    """Run the unified CLI without exposing internal tracebacks."""

    try:
        result = cli_app(args=argv, prog_name="honua-migrate", standalone_mode=False)
    except MigrationError as exc:
        click.echo(f"error: {exc}", err=True)
        return exc.exit_code
    except _EXIT_EXCEPTIONS as exc:
        return int(getattr(exc, "exit_code", 0) or 0)
    except _CLICK_EXCEPTIONS as exc:
        click_exc = cast(click.ClickException, exc)
        click_exc.show()
        return int(getattr(click_exc, "exit_code", 1))
    except Exception:
        click.echo("error: internal migration command failure", err=True)
        return EXIT_INTERNAL_ERROR
    return result if isinstance(result, int) else 0


__all__ = ["main"]
