"""Load and validate the esri-assess-registry -> Honua capability-key crosswalk.

DRAFT-FIXTURE NOTICE
--------------------
The default crosswalk bundled with this tool
(``src/honua_esri_assess/data/honua-crosswalk.fixture.json``) is a **draft
placeholder**, not the canonical artifact. The canonical
``capability-keys.v1.json`` crosswalk (with an ``esri-assess-registry ->
capability`` mapping) is produced by honua-server
(honua-io/honua-server#2893) and will replace this fixture once published.
Every parsed :class:`Crosswalk` carries its own ``source`` string so output
generated against the draft is never mistaken for the reconciled mapping --
the bundled fixture's ``source`` reads
``"DRAFT-FIXTURE (replace with honua-server published artifact)"``.

Until the canonical artifact ships, override the bundled fixture with
``honua-esri-assess caps --crosswalk <path-or-url>`` (see README "Air-gapped
usage" for the offline path).

This module performs no file or network I/O of its own -- reading the
bundled resource, a local override path, or a URL override is the CLI
layer's job (``honua_esri_assess.commands.caps``); this module only parses
and validates a document that has already been loaded as text.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

from honua_esri_assess.verdict.registry import CAPABILITY_REGISTRY

_REGISTRY_KEYS: frozenset[str] = frozenset(entry.key for entry in CAPABILITY_REGISTRY)

_BUNDLED_RESOURCE_PARTS: tuple[str, ...] = ("data", "honua-crosswalk.fixture.json")


class CrosswalkError(Exception):
    """Raised when a crosswalk document fails structural or key validation."""


@dataclass(frozen=True)
class Crosswalk:
    """A parsed, validated esri-assess-registry -> capability-key crosswalk."""

    schema_version: str
    source: str
    mapping: Mapping[str, tuple[str, ...] | None]

    def capability_keys_for(self, assess_key: str) -> tuple[str, ...] | None:
        """Return the mapped capability keys for ``assess_key``.

        Returns ``None`` when the assess key is explicitly marked
        not-supported (``null`` in the crosswalk document); an empty tuple
        when it is known but not yet mapped (``[]``); and an empty tuple when
        the key is altogether absent from the crosswalk document, so a
        crosswalk that omits a registry key never silently drops it -- it is
        simply treated the same as an explicit "unmapped" entry.
        """

        if assess_key not in self.mapping:
            return ()
        return self.mapping[assess_key]


def bundled_crosswalk_text() -> str:
    """Return the raw JSON text of the bundled draft crosswalk fixture."""

    resource = resources.files("honua_esri_assess")
    for part in _BUNDLED_RESOURCE_PARTS:
        resource = resource.joinpath(part)
    return resource.read_text(encoding="utf-8")


def parse_crosswalk(payload: Any) -> Crosswalk:
    """Parse and validate a crosswalk document already loaded as JSON.

    Raises :class:`CrosswalkError` (never a raw ``KeyError``/``TypeError``)
    when the document is structurally invalid, or when it references an
    esri-assess-registry key that does not exist in
    :data:`honua_esri_assess.verdict.registry.CAPABILITY_REGISTRY` -- the
    "unknown assess keys fail loudly" contract from issue #84.
    """

    if not isinstance(payload, Mapping):
        raise CrosswalkError("Crosswalk document must be a JSON object.")

    schema_version = payload.get("schemaVersion")
    if not isinstance(schema_version, str) or not schema_version:
        raise CrosswalkError("Crosswalk document is missing a string 'schemaVersion'.")

    source = payload.get("source")
    if not isinstance(source, str) or not source:
        raise CrosswalkError("Crosswalk document is missing a string 'source'.")

    crosswalks = payload.get("crosswalks")
    if not isinstance(crosswalks, Mapping):
        raise CrosswalkError("Crosswalk document is missing a 'crosswalks' object.")

    raw_mapping = crosswalks.get("esriAssessRegistry")
    if not isinstance(raw_mapping, Mapping):
        raise CrosswalkError(
            "Crosswalk document is missing 'crosswalks.esriAssessRegistry'."
        )

    unknown = sorted(set(raw_mapping) - _REGISTRY_KEYS)
    if unknown:
        raise CrosswalkError(
            "Crosswalk references unknown esri-assess-registry key(s): "
            + ", ".join(unknown)
            + ". Known keys: "
            + ", ".join(sorted(_REGISTRY_KEYS))
            + "."
        )

    mapping: dict[str, tuple[str, ...] | None] = {}
    for key, value in raw_mapping.items():
        if value is None:
            mapping[key] = None
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            mapping[key] = tuple(value)
        else:
            raise CrosswalkError(
                f"Crosswalk entry for {key!r} must be a list of capability-key "
                "strings, or null for an explicit not-supported mapping."
            )

    return Crosswalk(schema_version=schema_version, source=source, mapping=mapping)


def parse_crosswalk_text(text: str) -> Crosswalk:
    """Parse crosswalk JSON text, wrapping decode errors as :class:`CrosswalkError`."""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CrosswalkError(f"Crosswalk document is not valid JSON: {exc}") from exc
    return parse_crosswalk(payload)


def load_bundled_crosswalk() -> Crosswalk:
    """Load and validate the bundled draft crosswalk fixture."""

    return parse_crosswalk_text(bundled_crosswalk_text())


__all__ = [
    "Crosswalk",
    "CrosswalkError",
    "bundled_crosswalk_text",
    "load_bundled_crosswalk",
    "parse_crosswalk",
    "parse_crosswalk_text",
]
