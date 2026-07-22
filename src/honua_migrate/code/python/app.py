"""Typer commands for the Python/ArcPy migration engine."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated

import typer

from ._cli import (
    _cmd_atbx,
    _cmd_gpservice,
    _cmd_pyt,
    _cmd_run,
    _cmd_scan,
    _cmd_translate,
)

python_app = typer.Typer(
    help="Scan and translate ArcPy, Python-toolbox, and ModelBuilder code.",
    no_args_is_help=True,
)


def _finish(exit_code: int) -> None:
    if exit_code:
        raise typer.Exit(code=exit_code)


@python_app.command("scan")
def scan_command(
    path: Annotated[Path, typer.Argument(help="Path to an ArcPy .py script.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write the JSON report here (default: stdout)."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace existing output files."),
    ] = False,
) -> None:
    """Classify ArcPy calls without importing ArcPy or using the network."""

    _finish(_cmd_scan(argparse.Namespace(path=path, output=output, force=force)))


@python_app.command("translate")
def translate_command(
    path: Annotated[Path, typer.Argument(help="Path to an ArcPy .py script.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write the migration plan here (default: stdout)."),
    ] = None,
    evidence: Annotated[
        Path | None,
        typer.Option("--evidence", help="Write parity evidence to this path."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace existing output files."),
    ] = False,
) -> None:
    """Translate recognized calls into built-in Honua process payloads."""

    _finish(
        _cmd_translate(
            argparse.Namespace(
                path=path,
                output=output,
                evidence=evidence,
                force=force,
            )
        )
    )


@python_app.command("run")
def run_command(
    path: Annotated[Path, typer.Argument(help="Path to an ArcPy .py script.")],
    server: Annotated[str, typer.Option("--server", help="Honua server base URL.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write execution results here (default: stdout)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Emit payloads without contacting the server."),
    ] = False,
    acknowledge: Annotated[
        bool,
        typer.Option(
            "--yes",
            "--acknowledge",
            help="Acknowledge that non-dry-run execution mutates the Honua target.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace existing output files."),
    ] = False,
) -> None:
    """Run recognized built-in processes, or preview them with ``--dry-run``."""

    _finish(
        _cmd_run(
            argparse.Namespace(
                path=path,
                server=server,
                output=output,
                dry_run=dry_run,
                acknowledge=acknowledge,
                force=force,
            )
        )
    )


@python_app.command("pyt")
def pyt_command(
    path: Annotated[Path, typer.Argument(help="Path to a .pyt Python toolbox.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write toolbox JSON here (default: stdout)."),
    ] = None,
    evidence: Annotated[
        Path | None,
        typer.Option("--evidence", help="Write aggregated parity evidence here."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace existing output files."),
    ] = False,
) -> None:
    """Parse a Python toolbox and classify its geoprocessing calls."""

    _finish(
        _cmd_pyt(
            argparse.Namespace(
                path=path,
                output=output,
                evidence=evidence,
                force=force,
            )
        )
    )


@python_app.command("atbx")
def atbx_command(
    path: Annotated[Path, typer.Argument(help="Path to a clean-room .atbx toolbox.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write toolbox JSON here (default: stdout)."),
    ] = None,
    evidence: Annotated[
        Path | None,
        typer.Option("--evidence", help="Write aggregated parity evidence here."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace existing output files."),
    ] = False,
) -> None:
    """Parse a clean-room ModelBuilder .atbx toolbox."""

    _finish(
        _cmd_atbx(
            argparse.Namespace(
                path=path,
                output=output,
                evidence=evidence,
                force=force,
            )
        )
    )


@python_app.command("gpservice")
def gpservice_command(
    path: Annotated[Path, typer.Argument(help="Path to GPServer definition JSON.")],
    url: Annotated[
        str | None,
        typer.Option("--url", help="Original GPServer URL to retain in evidence."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write service JSON here (default: stdout)."),
    ] = None,
    evidence: Annotated[
        Path | None,
        typer.Option("--evidence", help="Write aggregated parity evidence here."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace existing output files."),
    ] = False,
) -> None:
    """Classify tasks from an ArcGIS REST GPServer definition."""

    _finish(
        _cmd_gpservice(
            argparse.Namespace(
                path=path,
                url=url,
                output=output,
                evidence=evidence,
                force=force,
            )
        )
    )


__all__ = ["python_app"]
