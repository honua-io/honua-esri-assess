"""Version command."""

from __future__ import annotations

import typer

from honua_esri_assess import __version__, bundled_schema_version


def version_command() -> None:
    typer.echo(f"honua-esri-assess {__version__}")
    typer.echo(f"EsriFootprint schema {bundled_schema_version()}")
