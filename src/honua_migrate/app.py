"""Canonical Typer application for the unified ``honua-migrate`` CLI."""

from __future__ import annotations

import importlib
from collections.abc import Callable

import typer

from honua_esri_assess.app import cli_app as assess_app

from .contracts import EXIT_APPLY_REFUSED, EXIT_UNAVAILABLE, MigrationError

cli_app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Honua migration planning and service migration tooling.",
    no_args_is_help=True,
)
services_app = typer.Typer(help="Service-specific migration commands.", no_args_is_help=True)
plan_app = typer.Typer(help="Create and inspect migration plans.", no_args_is_help=True)
content_app = typer.Typer(help="Migrate content and dependencies.", no_args_is_help=True)
code_app = typer.Typer(help="Migrate code integrations.", no_args_is_help=True)
apply_app = typer.Typer(help="Apply an approved migration plan.", no_args_is_help=True)
reconcile_app = typer.Typer(help="Reconcile migration results.", no_args_is_help=True)


def unavailable(command: str, *, apply: bool = False) -> Callable[[], None]:
    """Create a safe placeholder until a command module supplies an operation."""

    def command_fn() -> None:
        code = EXIT_APPLY_REFUSED if apply else EXIT_UNAVAILABLE
        raise MigrationError(f"{command} is not available in this release.", exit_code=code)

    return command_fn


def register_service_app(name: str, app: typer.Typer, *, help: str | None = None) -> None:
    """Mount a service-owned Typer app below ``honua-migrate services``.

    Service modules must expose a named ``<service>_app`` and may call this
    function during integration tests; production discovery also mounts the
    built-in service modules listed in ``_discover_service_apps``.
    """

    services_app.add_typer(app, name=name, help=help)


def _discover_service_apps() -> None:
    for service in ("arcgis", "geoserver"):
        try:
            module = importlib.import_module(f"honua_migrate.services.{service}")
            service_app = getattr(module, f"{service}_app")
        except ModuleNotFoundError as exc:
            if exc.name in {
                "honua_migrate.services",
                f"honua_migrate.services.{service}",
            }:
                continue
            raise
        register_service_app(service, service_app)


plan_app.command("create")(unavailable("plan create"))
plan_app.command("show")(unavailable("plan show"))
content_app.command("migrate")(unavailable("content migrate"))
code_app.command("migrate")(unavailable("code migrate"))
apply_app.command("plan")(unavailable("apply plan", apply=True))
reconcile_app.command("run")(unavailable("reconcile run"))

# ``assess`` is mounted below rather than reimplementing its read-only commands.
cli_app.add_typer(assess_app, name="assess")
cli_app.add_typer(plan_app, name="plan")
cli_app.add_typer(services_app, name="services")
cli_app.add_typer(content_app, name="content")
cli_app.add_typer(code_app, name="code")
cli_app.add_typer(apply_app, name="apply")
cli_app.add_typer(reconcile_app, name="reconcile")
_discover_service_apps()

__all__ = ["cli_app", "register_service_app", "services_app"]
