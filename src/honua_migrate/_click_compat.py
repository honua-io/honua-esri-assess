"""Locate Click's exception classes across Typer's shifting vendored layout.

Typer >=0.13 vendors its own copy of Click under ``typer._click``. Exceptions
raised while the Typer app parses arguments are instances of those vendored
classes, which are *not* subclasses of the standalone ``click`` package's
exceptions, so an entry point that maps exceptions to exit codes has to catch
both hierarchies.

Where each class lives has moved between Typer releases: ``Exit`` was exported
from ``typer._click.exceptions`` and is now only ``typer.exceptions.Exit`` (a
``RuntimeError``, not a ``ClickException``), as of Typer 0.27.2. Looking every
name up independently, across every module that might hold it, means one
relocated class no longer costs us the others - which is what happened when a
single ``try`` block resolved ``Exit`` and ``ClickException`` together and the
``AttributeError`` on ``Exit`` silently dropped the vendored ``ClickException``,
letting ``BadParameter`` escape ``main()`` as an unhandled traceback.

Both entry points share this module, and it lives here rather than in
``honua_esri_assess`` because importing that package emits the legacy-surface
deprecation warning - which the successor CLI must not print.
"""

from __future__ import annotations

import click


def _candidate_modules() -> list[object]:
    modules: list[object] = [click, click.exceptions]
    try:  # pragma: no cover - depends on the installed Typer
        from typer import _click as typer_click

        modules.append(typer_click)
        modules.append(typer_click.exceptions)
    except Exception:  # pragma: no cover - older Typer shares standalone Click
        pass
    try:  # pragma: no cover - depends on the installed Typer
        import typer.exceptions as typer_exceptions

        modules.append(typer_exceptions)
    except Exception:  # pragma: no cover - Typer is a hard dependency
        pass
    return modules


def exception_types(*names: str) -> tuple[type[BaseException], ...]:
    """Return every exception class matching ``names`` that is actually present.

    Names are resolved independently, so a class missing from one module does
    not suppress the ones that are there.
    """

    found: list[type[BaseException]] = []
    for module in _candidate_modules():
        for name in names:
            candidate = getattr(module, name, None)
            if (
                isinstance(candidate, type)
                and issubclass(candidate, BaseException)
                and candidate not in found
            ):
                found.append(candidate)
    return tuple(found)


#: Raised to request a specific process exit code without an error message.
EXIT_EXCEPTIONS: tuple[type[BaseException], ...] = exception_types("Exit")

#: Raised to report a usage or runtime error the CLI should print and exit on.
CLICK_EXCEPTIONS: tuple[type[BaseException], ...] = exception_types("ClickException")

__all__ = ["CLICK_EXCEPTIONS", "EXIT_EXCEPTIONS", "exception_types"]
