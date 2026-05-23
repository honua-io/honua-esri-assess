"""JSON Schema loading and validation for emitted footprints."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from honua_esri_assess.diagnostics import PortalSchemaError

SCHEMA_FILENAME = "esri-footprint-v0.1.json"
SCHEMA_PACKAGE = "honua_esri_assess.schemas"
_PACKAGE_ROOT = "honua_esri_assess"
_PACKAGE_SCHEMA_DIR = "schemas"
_SCHEMA_DIR_CANDIDATES = (
    Path("schemas"),
    Path("docs/schemas"),
    Path(__file__).resolve().parents[3] / "schemas",
    Path(__file__).resolve().parents[3] / "docs" / "schemas",
)


class FootprintSchemaNotFoundError(PortalSchemaError):
    """Raised when the declared footprint schema cannot be loaded."""


def _version_aliases(version: str) -> list[str]:
    raw = str(version).strip()
    if raw.startswith("v"):
        raw = raw[1:]
    aliases = [raw]
    parts = raw.split(".")
    if len(parts) >= 2:
        aliases.append(".".join(parts[:2]))
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _schema_file_names(version: str) -> list[str]:
    names: list[str] = []
    for alias in _version_aliases(version):
        names.append(f"esri-footprint.v{alias}.json")
        names.append(f"esri-footprint-v{alias}.json")
    return list(dict.fromkeys(names))


def _candidate_paths(version: str) -> list[Path]:
    candidates: list[Path] = []
    for base in _SCHEMA_DIR_CANDIDATES:
        for filename in _schema_file_names(version):
            candidates.append(base / filename)
    return candidates


def find_schema_path(version: str) -> Path | None:
    for candidate in _candidate_paths(version):
        if candidate.is_file():
            return candidate
    return None


def _packaged_schema_text(version: str) -> str | None:
    try:
        schema_dir = resources.files(_PACKAGE_ROOT).joinpath(_PACKAGE_SCHEMA_DIR)
    except (FileNotFoundError, ModuleNotFoundError):
        return None

    for filename in _schema_file_names(version):
        candidate = schema_dir.joinpath(filename)
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return None


def _load_schema(version: str) -> dict[str, Any]:
    path = find_schema_path(version)
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))

    schema_text = _packaged_schema_text(version)
    if schema_text is not None:
        return json.loads(schema_text)

    raise FootprintSchemaNotFoundError(
        f"schema for footprint version {version!r} was not found"
    )


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """Return the v0.1 schema bundled with the installed package."""

    try:
        traversable = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_FILENAME)
        raw = traversable.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise PortalSchemaError(
            "The EsriFootprint.json schema is not bundled with the installed package.",
            context={"schema": SCHEMA_FILENAME},
        ) from exc

    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise PortalSchemaError(
            "The bundled EsriFootprint.json schema is not valid JSON.",
            context={"schema": SCHEMA_FILENAME},
        ) from exc

    if not isinstance(payload, dict):
        raise PortalSchemaError(
            "The EsriFootprint.json schema is not a JSON object.",
            context={"schema": SCHEMA_FILENAME},
        )
    return payload


def validate_footprint(footprint: dict[str, Any], *, version: str | None = None) -> bool:
    """Validate *footprint* against the declared footprint schema."""

    schema_version = str(version or footprint.get("schemaVersion") or "")
    schema = _load_schema(schema_version) if schema_version else load_schema()

    try:
        import jsonschema
    except ImportError as exc:
        raise PortalSchemaError(
            "The jsonschema package is required to validate EsriFootprint.json."
        ) from exc

    try:
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        )
        validator.validate(footprint)
    except jsonschema.ValidationError as exc:
        field = ".".join(str(part) for part in exc.absolute_path)
        message = "Generated EsriFootprint.json does not match the v0.1 schema."
        context = {"field": field} if field else {}
        raise PortalSchemaError(message, context=context) from exc
    return True


__all__ = [
    "FootprintSchemaNotFoundError",
    "SCHEMA_FILENAME",
    "SCHEMA_PACKAGE",
    "find_schema_path",
    "load_schema",
    "validate_footprint",
]
