"""JSON Schema loading and validation for emitted footprints."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from honua_esri_assess.diagnostics import PortalSchemaError

SCHEMA_FILENAME = "esri-footprint-v0.1.json"
SCHEMA_PACKAGE = "honua_esri_assess.schemas"


class FootprintSchemaNotFoundError(PortalSchemaError):
    """Backward-compatible alias for fail-closed schema lookup failures."""


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
    """Validate ``footprint`` against the bundled v0.1 schema."""

    if version not in (None, "v0.1", "0.1", "0.1.0", "v0.1.0"):
        raise PortalSchemaError(
            "Unsupported EsriFootprint.json schema version.",
            context={"schema": str(version)},
        )

    schema = load_schema()
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
    "load_schema",
    "validate_footprint",
]
