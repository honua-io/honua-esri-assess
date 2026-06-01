"""Registry for scanner backends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from honua_esri_assess.commands.common import ScanOptions, ScanResult


@dataclass(frozen=True)
class ScanHandler:
    name: str
    run: Callable[[ScanOptions], ScanResult]


HANDLERS: dict[str, ScanHandler] = {}


def register(handler: ScanHandler) -> None:
    HANDLERS[handler.name] = handler


def get_handler(name: str) -> ScanHandler:
    return HANDLERS[name]


def _register_default_handlers() -> None:
    from . import agol, filegdb, filegdb_workspace, rbac, server

    register(ScanHandler(name="agol", run=agol.run))
    register(ScanHandler(name="server", run=server.run))
    register(ScanHandler(name="filegdb", run=filegdb.run))
    register(ScanHandler(name="filegdb-workspace", run=filegdb_workspace.run))
    register(ScanHandler(name="rbac", run=rbac.run))


_register_default_handlers()
