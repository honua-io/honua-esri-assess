"""The entry points must map Typer's vendored Click exceptions to exit codes.

Typer relocates these classes between releases - ``Exit`` left
``typer._click.exceptions`` in 0.27.2 - and the previous resolution code looked
every name up inside one ``try`` block, so a single relocated class silently
dropped the vendored ``ClickException`` and let ``BadParameter`` escape
``main()`` as an unhandled traceback. These tests bind to the behaviour rather
than to any one Typer layout.
"""

from __future__ import annotations

import click
import pytest

from honua_migrate._click_compat import (
    CLICK_EXCEPTIONS,
    EXIT_EXCEPTIONS,
    exception_types,
)


def test_standalone_click_exceptions_are_covered() -> None:
    assert issubclass(click.ClickException, CLICK_EXCEPTIONS)
    assert issubclass(click.exceptions.Exit, EXIT_EXCEPTIONS)


def test_typer_vendored_usage_errors_are_covered() -> None:
    """A parse failure inside the Typer app is what actually reaches ``main``."""

    typer_click = pytest.importorskip("typer._click")
    assert issubclass(typer_click.exceptions.BadParameter, CLICK_EXCEPTIONS)
    assert issubclass(typer_click.exceptions.UsageError, CLICK_EXCEPTIONS)


def test_typer_exit_is_covered_wherever_typer_keeps_it() -> None:
    typer = pytest.importorskip("typer")
    assert issubclass(typer.Exit, EXIT_EXCEPTIONS)


def test_a_relocated_name_does_not_suppress_the_others() -> None:
    """The property the previous implementation lacked."""

    resolved = exception_types("ClickException", "NoSuchNameAnywhere")
    assert click.ClickException in resolved


def test_unknown_names_resolve_to_an_empty_tuple() -> None:
    assert exception_types("NoSuchNameAnywhere") == ()
