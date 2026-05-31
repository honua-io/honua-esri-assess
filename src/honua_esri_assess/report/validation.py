"""Optional EsriFootprint schema validation for the report CLI."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from honua_esri_assess import SCHEMA_VERSION

_SUPPORTED_SCHEMA_VERSIONS = ("v0.1", "v0.2")


@dataclass(frozen=True)
class SchemaValidationIssue:
    message: str
    is_failure: bool
    pointer: str = "/"


def validate_footprint(footprint: Mapping[str, Any]) -> tuple[SchemaValidationIssue, ...]:
    """Validate a footprint against the matching packaged EsriFootprint schema.

    Dispatches on ``schemaVersion`` so v0.1 footprints validate against the
    v0.1 schema and v0.2 footprints (with the optional ``access`` block) get
    the v0.2 schema. Falls back to the bundled default when the field is
    missing or unrecognised. Returns every issue rather than raising — the
    report CLI surfaces them as warnings or, in ``--strict`` mode, the first
    one becomes the failure.
    """

    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        return (
            SchemaValidationIssue(
                message="Schema validation could not run because jsonschema is not installed.",
                is_failure=True,
            ),
        )

    version = _detect_schema_version(footprint)
    try:
        from honua_esri_assess.schema import load_schema

        schema = load_schema(version)
    except FileNotFoundError:
        return (
            SchemaValidationIssue(
                message=(
                    "Schema validation could not run because the packaged "
                    f"{version} schema was not found."
                ),
                is_failure=True,
            ),
        )
    except json.JSONDecodeError:
        return (
            SchemaValidationIssue(
                message=(
                    "Schema validation could not run because the packaged "
                    f"{version} schema is invalid JSON."
                ),
                is_failure=True,
            ),
        )

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(footprint), key=lambda error: list(error.path))
    return tuple(_issue_from_error(error, version) for error in errors)


def _detect_schema_version(footprint: Mapping[str, Any]) -> str:
    declared = footprint.get("schemaVersion")
    if isinstance(declared, str) and declared in _SUPPORTED_SCHEMA_VERSIONS:
        return declared
    return SCHEMA_VERSION


def _issue_from_error(error: Any, version: str) -> SchemaValidationIssue:
    pointer = "/" + "/".join(str(part) for part in error.path)
    message = f"Schema validation failed at {pointer}: {_sanitized_reason(error, version)}."
    return SchemaValidationIssue(message=message, is_failure=True, pointer=pointer)


def _sanitized_reason(error: Any, version: str) -> str:
    validator = getattr(error, "validator", None)
    return {
        "additionalProperties": f"field is not allowed by EsriFootprint {version}",
        "anyOf": f"field does not match any allowed {version} shape",
        "const": f"field does not match the required {version} value",
        "enum": f"field is not in the allowed {version} vocabulary",
        "format": "field does not match the required format",
        "oneOf": f"field does not match exactly one allowed {version} shape",
        "pattern": "field does not match the required prospect-safe format",
        "required": "required field is missing",
        "type": "field has the wrong JSON type",
    }.get(str(validator), f"schema rule `{validator}` failed")
