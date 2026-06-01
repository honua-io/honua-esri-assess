"""Bundled EsriFootprint schema helpers."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from . import SCHEMA_VERSION
from .diagnostics import SchemaValidationError

SCHEMA_FILENAME = "esri-footprint-v0.2.json"


def _repo_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / SCHEMA_FILENAME


def schema_text() -> str:
    """Return the bundled schema text.

    Wheels carry the schema as a package resource. Editable installs and source
    tree test runs use the top-level schema copy.
    """

    package_path = resources.files("honua_esri_assess").joinpath(
        "schemas", SCHEMA_FILENAME
    )
    if package_path.is_file():
        return package_path.read_text(encoding="utf-8")
    return _repo_schema_path().read_text(encoding="utf-8")


def load_schema() -> dict[str, Any]:
    return json.loads(schema_text())


def validate_footprint(footprint: dict[str, Any]) -> None:
    schema = load_schema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(footprint),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        first = errors[0]
        location = _safe_error_location(first.path)
        keyword = str(first.validator or "schema")
        raise SchemaValidationError(
            f"EsriFootprint.json does not conform to schema {SCHEMA_VERSION}: "
            f"{location}: failed {keyword} validation."
        )


def validate_footprint_file(path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(
            "Could not read a valid JSON footprint from the requested path."
        ) from exc

    if not isinstance(payload, dict):
        raise SchemaValidationError("EsriFootprint.json must be a JSON object.")
    validate_footprint(payload)


def _safe_error_location(path: Any) -> str:
    parts = [_safe_location_part(part) for part in path]
    return ".".join(parts) or "<root>"


def _safe_location_part(part: object) -> str:
    if isinstance(part, int):
        return str(part)
    text = str(part)
    if text.replace("_", "").replace("-", "").isalnum():
        return text
    return "<field>"
