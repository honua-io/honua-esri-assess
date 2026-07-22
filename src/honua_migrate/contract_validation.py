"""JSON Schema and secret-safety validation for migration artifacts."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any, Mapping
from urllib.parse import urlsplit

import jsonschema

from .contracts import EXIT_VALIDATION_ERROR, MigrationError

SCHEMA_NAMES = frozenset(
    {"diagnostic", "plan", "report", "reconciliation", "result", "run"}
)

_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|authorization|api[_-]?key|credential)",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"\bbearer\s+\S+", re.IGNORECASE)


def load_contract_schema(name: str) -> dict[str, Any]:
    """Load one packaged v1 contract schema by its stable short name."""

    if name not in SCHEMA_NAMES:
        raise ValueError(f"Unknown migration contract schema: {name}")
    schema_path = resources.files("honua_migrate.contract_schemas.v1").joinpath(
        f"{name}.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def assert_artifact_safe(value: Any, *, path: str = "$") -> None:
    """Reject secret-bearing keys, URL userinfo, tokens, and auth query values."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text):
                raise MigrationError(
                    f"Artifact contains a forbidden credential field at {path}.",
                    exit_code=EXIT_VALIDATION_ERROR,
                )
            assert_artifact_safe(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_artifact_safe(item, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    if _BEARER_VALUE.search(value):
        raise MigrationError(
            f"Artifact contains an unredacted authorization value at {path}.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    if not value.lower().startswith(("http://", "https://")):
        return
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise MigrationError(
            f"Artifact contains URL userinfo at {path}.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    if parsed.query:
        raise MigrationError(
            f"Artifact contains a URL query string at {path}.",
            exit_code=EXIT_VALIDATION_ERROR,
        )


def validate_contract(name: str, payload: Mapping[str, Any]) -> None:
    """Validate schema shape and recursive credential-safety requirements."""

    assert_artifact_safe(payload)
    try:
        jsonschema.Draft202012Validator(load_contract_schema(name)).validate(payload)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "$"
        raise MigrationError(
            f"Migration {name} contract is invalid at {location}.",
            exit_code=EXIT_VALIDATION_ERROR,
        ) from exc


__all__ = [
    "SCHEMA_NAMES",
    "assert_artifact_safe",
    "load_contract_schema",
    "validate_contract",
]
