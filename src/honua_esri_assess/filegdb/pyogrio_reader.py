"""pyogrio-backed FileGDB metadata reader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .scanner import FileGdbLayer, FileGdbReaderUnavailable


class PyogrioFileGdbReader:
    """Read FileGDB layer metadata through pyogrio/GDAL without mutating data."""

    def __init__(self) -> None:
        self._pyogrio: Any | None = None

    def _module(self) -> Any:
        if self._pyogrio is not None:
            return self._pyogrio
        try:
            import pyogrio
        except ImportError as exc:
            raise FileGdbReaderUnavailable(
                "The FileGDB reader dependency is not installed."
            ) from exc
        self._pyogrio = pyogrio
        return pyogrio

    def list_layers(self, workspace: Path) -> Sequence[FileGdbLayer]:
        layers = self._module().list_layers(workspace)
        return [
            FileGdbLayer(
                name=str(layer[0]),
                geometry_type=None if layer[1] is None else str(layer[1]),
            )
            for layer in layers
        ]

    def read_layer_info(
        self,
        workspace: Path,
        layer_name: str,
        *,
        force_feature_count: bool = False,
    ) -> Mapping[str, Any]:
        return self._module().read_info(
            workspace,
            layer=layer_name,
            force_feature_count=force_feature_count,
        )
