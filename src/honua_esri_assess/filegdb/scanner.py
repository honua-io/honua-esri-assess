"""FileGDB scanner that emits EsriFootprint v0.1 inventory records."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from honua_esri_assess.footprint import (
    SCHEMA_VERSION,
    TOOL_NAME,
    installed_tool_version,
    utc_timestamp,
)

JsonObject = dict[str, Any]


class FileGdbReaderUnavailable(RuntimeError):
    """Raised by a reader when its optional backend is unavailable."""


@dataclass(frozen=True)
class FileGdbLayer:
    """Minimal layer listing returned by FileGDB metadata readers."""

    name: str
    geometry_type: str | None = None


class FileGdbMetadataReader(Protocol):
    """Read-only metadata operations needed by the FileGDB scanner."""

    def list_layers(self, workspace: Path) -> Sequence[Any]:
        """Return the layers in a FileGDB workspace."""
        ...

    def read_layer_info(
        self,
        workspace: Path,
        layer_name: str,
        *,
        force_feature_count: bool = False,
    ) -> Mapping[str, Any]:
        """Return metadata for a single layer."""
        ...


@dataclass(frozen=True)
class FileGdbScanOptions:
    """Options for a read-only FileGDB inventory scan."""

    path_hash_salt: str | bytes | None = None
    captured_at: str | None = None
    generated_at: str | None = None
    force_feature_count: bool = False
    include_fields: bool = True


def scan_filegdb_workspace(
    workspace: str | Path,
    *,
    options: FileGdbScanOptions | None = None,
    reader: FileGdbMetadataReader | None = None,
) -> JsonObject:
    """Scan a local ``.gdb`` directory and return an EsriFootprint v0.1 artifact.

    The scanner only calls metadata/list operations on the reader. Recoverable
    failures are surfaced as v0.1 diagnostics; raw exception text is never copied
    into the footprint.
    """

    scan_options = options or FileGdbScanOptions()
    workspace_path = Path(workspace)
    captured_at = scan_options.captured_at or utc_timestamp()
    path_hash = hash_filegdb_path(workspace_path, salt=scan_options.path_hash_salt)
    inventory: list[JsonObject] = []
    diagnostics: list[JsonObject] = []

    workspace_diagnostic = _workspace_diagnostic(workspace_path)
    if workspace_diagnostic is not None:
        diagnostics.append(workspace_diagnostic)
        return _build_footprint(
            path_hash=path_hash,
            captured_at=captured_at,
            generated_at=scan_options.generated_at or utc_timestamp(),
            inventory=inventory,
            diagnostics=diagnostics,
        )

    metadata_reader = reader or _default_reader()
    try:
        layers = _normalize_layers(metadata_reader.list_layers(workspace_path))
    except FileGdbReaderUnavailable:
        diagnostics.append(
            _diagnostic(
                code="partial-coverage",
                severity="error",
                message=(
                    "FileGDB metadata could not be read because the reader "
                    "dependency is not installed."
                ),
                scope="filegdb",
                hint=(
                    "Install the FileGDB extra, for example: "
                    'python -m pip install "honua-migrate[filegdb]".'
                ),
            )
        )
        layers = []
    except Exception:
        diagnostics.append(
            _diagnostic(
                code="partial-coverage",
                severity="error",
                message=(
                    "FileGDB layers could not be listed by the read-only "
                    "metadata reader."
                ),
                scope="filegdb",
                hint=(
                    "Confirm the workspace is a readable FileGDB directory "
                    "supported by GDAL/OGR."
                ),
            )
        )
        layers = []

    for layer in layers:
        try:
            info = metadata_reader.read_layer_info(
                workspace_path,
                layer.name,
                force_feature_count=scan_options.force_feature_count,
            )
        except Exception:
            diagnostics.append(
                _diagnostic(
                    code="partial-coverage",
                    severity="warn",
                    message=(
                        "Skipped one FileGDB layer because its metadata could "
                        "not be read."
                    ),
                    scope=_safe_scope(layer.name),
                    hint="Confirm this layer can be opened read-only by GDAL/OGR.",
                )
            )
            continue

        item, item_diagnostics = _inventory_item(
            layer,
            info,
            include_fields=scan_options.include_fields,
        )
        inventory.append(item)
        diagnostics.extend(item_diagnostics)

    return _build_footprint(
        path_hash=path_hash,
        captured_at=captured_at,
        generated_at=scan_options.generated_at or utc_timestamp(),
        inventory=inventory,
        diagnostics=diagnostics,
    )


def hash_filegdb_path(workspace: str | Path, *, salt: str | bytes | None = None) -> str:
    """Return the prospect-safe salted path hash used for FileGDB locators."""

    if salt is None or salt == "" or salt == b"":
        salt_bytes = secrets.token_bytes(32)
    elif isinstance(salt, bytes):
        salt_bytes = salt
    else:
        salt_bytes = salt.encode("utf-8")
    canonical_path = str(Path(workspace).expanduser().resolve(strict=False))
    digest = hashlib.sha256(
        salt_bytes + b"\0" + canonical_path.encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _default_reader() -> FileGdbMetadataReader:
    from .pyogrio_reader import PyogrioFileGdbReader

    return PyogrioFileGdbReader()


def _workspace_diagnostic(workspace: Path) -> JsonObject | None:
    if not workspace.exists():
        return _diagnostic(
            code="partial-coverage",
            severity="error",
            message="FileGDB workspace could not be scanned because it does not exist.",
            scope="filegdb",
            hint="Choose a local directory ending in .gdb.",
        )
    if not workspace.is_dir():
        return _diagnostic(
            code="partial-coverage",
            severity="error",
            message="FileGDB workspace could not be scanned because it is not a directory.",
            scope="filegdb",
            hint="Choose a local directory ending in .gdb.",
        )
    if workspace.suffix.lower() != ".gdb":
        return _diagnostic(
            code="unsupported-item-type",
            severity="error",
            message=(
                "FileGDB workspace could not be scanned because the directory "
                "is not a .gdb workspace."
            ),
            scope="filegdb",
            hint="Choose a local FileGDB directory with a .gdb suffix.",
        )
    return None


def _normalize_layers(raw_layers: Sequence[Any]) -> list[FileGdbLayer]:
    layers: list[FileGdbLayer] = []
    for raw_layer in raw_layers:
        layer = _normalize_layer(raw_layer)
        if layer is not None:
            layers.append(layer)
    return layers


def _normalize_layer(raw_layer: Any) -> FileGdbLayer | None:
    if isinstance(raw_layer, FileGdbLayer):
        return raw_layer
    if isinstance(raw_layer, Mapping):
        name = raw_layer.get("name")
        geometry_type = raw_layer.get("geometry_type")
    else:
        try:
            name = raw_layer[0]
            geometry_type = raw_layer[1] if len(raw_layer) > 1 else None
        except (IndexError, TypeError):
            return None
    if name is None or str(name) == "":
        return None
    return FileGdbLayer(
        name=str(name),
        geometry_type=None if geometry_type is None else str(geometry_type),
    )


def _inventory_item(
    layer: FileGdbLayer,
    info: Mapping[str, Any],
    *,
    include_fields: bool,
) -> tuple[JsonObject, list[JsonObject]]:
    diagnostics: list[JsonObject] = []
    geometry_source = info.get("geometry_type", layer.geometry_type)
    geometry_type, supported_geometry = _geometry_type_to_esri(geometry_source)
    if not supported_geometry:
        diagnostics.append(
            _diagnostic(
                code="unsupported-item-type",
                severity="info",
                message=(
                    "Layer geometry type is not modeled in EsriFootprint v0.1 "
                    "and was emitted as null."
                ),
                scope=_safe_scope(layer.name),
            )
        )

    item: JsonObject = {
        "kind": "filegdb-feature-class",
        "name": layer.name,
        "geometryType": geometry_type,
        "sr": _spatial_reference(info.get("crs")),
    }
    feature_count = _feature_count(info.get("features"))
    if feature_count is not None:
        item["featureCount"] = feature_count
    if include_fields:
        item["fields"] = _field_descriptors(info)
    return item, diagnostics


def _build_footprint(
    *,
    path_hash: str,
    captured_at: str,
    generated_at: str,
    inventory: list[JsonObject],
    diagnostics: list[JsonObject],
) -> JsonObject:
    feature_class_count = len(inventory)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "tool": {
            "name": TOOL_NAME,
            "version": installed_tool_version(),
        },
        "source": {
            "kind": "filegdb",
            "locator": path_hash,
            "capturedAt": captured_at,
        },
        "filegdb": {
            "pathHash": path_hash,
            "featureClassCount": feature_class_count,
        },
        "inventory": inventory,
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": 0,
                "filegdb-feature-class": feature_class_count,
            },
            "layers": 0,
            "featureClasses": feature_class_count,
        },
        "diagnostics": diagnostics,
    }


def _diagnostic(
    *,
    code: str,
    severity: str,
    message: str,
    scope: str,
    hint: str | None = None,
) -> JsonObject:
    diagnostic: JsonObject = {
        "code": code,
        "severity": severity,
        "message": message,
        "scope": _safe_scope(scope),
    }
    if hint is not None:
        diagnostic["hint"] = hint
    return diagnostic


def _safe_scope(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9 ._()+:-]", "_", value).strip()
    if not safe:
        return "filegdb"
    return safe[:80]


def _geometry_type_to_esri(geometry_type: Any) -> tuple[str | None, bool]:
    if geometry_type is None:
        return None, True
    normalized = str(geometry_type).strip().lower()
    if normalized in {"", "none", "null", "unknown", "geometry"}:
        return None, True

    normalized = normalized.replace("25d", "")
    normalized = re.sub(r"\b(?:3d|measured|[zm])\b", "", normalized)
    normalized = normalized.replace("_", "").replace(" ", "")
    while True:
        prefixed = normalized.removeprefix("3d").removeprefix("measured")
        if prefixed == normalized:
            break
        normalized = prefixed

    geometry_aliases = {
        "point": "esriGeometryPoint",
        "multipoint": "esriGeometryMultipoint",
        "linestring": "esriGeometryPolyline",
        "multilinestring": "esriGeometryPolyline",
        "linearring": "esriGeometryPolyline",
        "curve": "esriGeometryPolyline",
        "compoundcurve": "esriGeometryPolyline",
        "polygon": "esriGeometryPolygon",
        "multipolygon": "esriGeometryPolygon",
        "curvepolygon": "esriGeometryPolygon",
        "surface": "esriGeometryPolygon",
        "multisurface": "esriGeometryPolygon",
        "envelope": "esriGeometryEnvelope",
    }
    if normalized not in geometry_aliases:
        for suffix in ("zm", "mz", "z", "m"):
            candidate = normalized.removesuffix(suffix)
            if candidate != normalized and candidate in geometry_aliases:
                normalized = candidate
                break

    esri_geometry = geometry_aliases.get(normalized)
    if esri_geometry is not None:
        return esri_geometry, True
    return None, False


def _spatial_reference(crs: Any) -> JsonObject:
    if crs is None:
        return {"wkt": "UNKNOWN"}
    if isinstance(crs, Mapping):
        sr: JsonObject = {}
        if _integer_or_none(crs.get("wkid")) is not None:
            sr["wkid"] = _integer_or_none(crs.get("wkid"))
        if _integer_or_none(crs.get("latestWkid")) is not None:
            sr["latestWkid"] = _integer_or_none(crs.get("latestWkid"))
        if crs.get("wkt"):
            sr["wkt"] = str(crs["wkt"])
        return sr or {"wkt": "UNKNOWN"}
    if hasattr(crs, "to_epsg"):
        epsg = _integer_or_none(crs.to_epsg())
        if epsg is not None:
            return {"wkid": epsg}
    crs_text = str(crs).strip()
    epsg_match = re.fullmatch(r"EPSG:(\d+)", crs_text, flags=re.IGNORECASE)
    if epsg_match:
        return {"wkid": int(epsg_match.group(1))}
    return {"wkt": crs_text or "UNKNOWN"}


def _feature_count(features: Any) -> int | None:
    count = _integer_or_none(features)
    if count is None or count < 0:
        return None
    return count


def _field_descriptors(info: Mapping[str, Any]) -> list[JsonObject]:
    field_names = _sequence(info.get("fields"))
    ogr_types = _sequence(info.get("ogr_types"))
    ogr_subtypes = _sequence(info.get("ogr_subtypes"))
    dtypes = _sequence(info.get("dtypes"))
    nullable_values = _sequence(info.get("nullable", info.get("nullables")))
    fid_column = info.get("fid_column")
    descriptors: list[JsonObject] = []

    for index, field_name in enumerate(field_names):
        if field_name is None or str(field_name) == "":
            continue
        descriptor: JsonObject = {
            "name": str(field_name),
            "type": _esri_field_type(
                field_name=str(field_name),
                ogr_type=_value_at(ogr_types, index),
                ogr_subtype=_value_at(ogr_subtypes, index),
                dtype=_value_at(dtypes, index),
                fid_column=None if fid_column is None else str(fid_column),
            ),
        }
        nullable = _value_at(nullable_values, index)
        if isinstance(nullable, bool):
            descriptor["nullable"] = nullable
        descriptors.append(descriptor)
    return descriptors


def _esri_field_type(
    *,
    field_name: str,
    ogr_type: Any,
    ogr_subtype: Any,
    dtype: Any,
    fid_column: str | None,
) -> str:
    normalized_name = field_name.upper()
    if fid_column is not None and field_name == fid_column:
        return "esriFieldTypeOID"
    if normalized_name in {"OBJECTID", "FID", "OID"}:
        return "esriFieldTypeOID"

    text = f"{ogr_type or ''} {ogr_subtype or ''} {dtype or ''}".lower()
    if "globalid" in text or normalized_name in {"GLOBALID", "GLOBAL_ID"}:
        return "esriFieldTypeGlobalID"
    if "guid" in text or "uuid" in text:
        return "esriFieldTypeGUID"
    if "binary" in text or "blob" in text:
        return "esriFieldTypeBlob"
    if "date" in text or "time" in text:
        return "esriFieldTypeDate"
    if "integer64" in text or "bigint" in text or "big integer" in text:
        return "esriFieldTypeBigInteger"
    if "int64" in text or "longlong" in text or "long long" in text:
        return "esriFieldTypeBigInteger"
    if "int16" in text or "small" in text:
        return "esriFieldTypeSmallInteger"
    if "int" in text:
        return "esriFieldTypeInteger"
    if "float32" in text or "single" in text:
        return "esriFieldTypeSingle"
    if "float" in text or "double" in text or "real" in text:
        return "esriFieldTypeDouble"
    return "esriFieldTypeString"


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if hasattr(value, "tolist"):
        value = value.tolist()
    try:
        return list(value)
    except TypeError:
        return [value]


def _value_at(values: Sequence[Any], index: int) -> Any:
    if index >= len(values):
        return None
    return values[index]


def _integer_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
